"""Alert lifecycle: creation (with de-duplication), state machine, SLA, escalation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.observability import metrics
from app.models import Alert, CareTeamAction, Escalation, Patient, RoleModel, User
from app.services import audit
from app.services.notifications import notify
from app.services.outbound import queue_alert
from rules.engine import SEVERITY_ORDER, max_severity

OPEN_STATUSES = ("NEW", "ACKNOWLEDGED", "CONTACT_IN_PROGRESS", "ESCALATED")

# Allowed transitions. RESOLVED → CLOSED is the normal end; CLOSED is terminal.
TRANSITIONS = {
    "NEW": {"ACKNOWLEDGED", "CONTACT_IN_PROGRESS", "ESCALATED", "RESOLVED", "CLOSED"},
    "ACKNOWLEDGED": {"CONTACT_IN_PROGRESS", "ESCALATED", "RESOLVED", "CLOSED"},
    "CONTACT_IN_PROGRESS": {"ESCALATED", "RESOLVED", "CLOSED"},
    "ESCALATED": {"ACKNOWLEDGED", "CONTACT_IN_PROGRESS", "RESOLVED", "CLOSED"},
    "RESOLVED": {"CLOSED", "ACKNOWLEDGED"},
    "CLOSED": set(),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def create_alert(db: Session, *, patient: Patient, severity: str, category: str, source: str, rule_id: str,
                 trigger_summary: str, evidence: list, response_minutes: int, assigned_team: str,
                 episode_id=None, checkin_id=None, protocol_id=None, actor: User | None = None,
                 dedupe_open: bool = True) -> Alert:
    """Create an alert; if an open alert with the same rule exists, append evidence instead."""
    if dedupe_open:
        existing = db.scalars(select(Alert).where(
            Alert.patient_id == patient.id, Alert.rule_id == rule_id, Alert.status.in_(OPEN_STATUSES))).first()
        if existing:
            existing.evidence = list(existing.evidence or []) + [{"repeat_at": now().isoformat(), "evidence": evidence}]
            if checkin_id:
                existing.checkin_id = checkin_id
            audit.record(db, "ALERT_REPEAT_TRIGGER", actor=actor, patient_id=patient.id, resource_type="alert",
                         resource_id=existing.id, details={"rule_id": rule_id, "evidence": evidence})
            return existing

    created = now()
    alert = Alert(
        patient_id=patient.id, episode_id=episode_id, checkin_id=checkin_id, protocol_id=protocol_id,
        rule_id=rule_id, severity=severity, category=category, source=source,
        trigger_summary=trigger_summary[:500], evidence=evidence, status="NEW",
        required_response_minutes=response_minutes, due_at=created + timedelta(minutes=response_minutes),
        assigned_team=assigned_team, assigned_user_id=patient.assigned_nurse_id if assigned_team == "NURSE" else None,
    )
    db.add(alert)
    db.flush()
    refresh_patient_risk(db, patient)
    queue_alert(db, alert, patient)  # RED / AMBER alerts are also written to the EHR
    metrics.inc("alerts_created", severity=severity, category=category)
    audit.record(db, "ALERT_CREATED", actor=actor, patient_id=patient.id, resource_type="alert", resource_id=alert.id,
                 details={"rule_id": rule_id, "severity": severity, "category": category, "source": source,
                          "trigger": trigger_summary, "evidence": evidence, "response_minutes": response_minutes,
                          "assigned_team": assigned_team})
    # Notify the assigned care team (in-app; SMS for RED to the on-call nurse).
    team_users = db.scalars(select(User).join(RoleModel, RoleModel.id == User.role_id).where(
        User.is_active.is_(True), RoleModel.name == _team_role(assigned_team))).unique().all()
    for u in team_users:
        notify(db, category="CARE_TEAM_ESCALATION", user=u,
               title=f"{severity} alert: {patient.full_name}",
               body=f"{trigger_summary} — respond within {response_minutes} min.",
               channels=("IN_APP", "SMS") if severity == "RED" else ("IN_APP",),
               dedupe_key=f"alert:{alert.id}:{u.id}")
    return alert


def _team_role(team: str) -> str:
    return {"NURSE": "NURSE", "COORDINATOR": "NURSE", "SURGEON": "SURGEON"}.get(team, "NURSE")


def refresh_patient_risk(db: Session, patient: Patient) -> str:
    sev = db.scalars(select(Alert.severity).where(
        Alert.patient_id == patient.id, Alert.status.in_(OPEN_STATUSES))).all()
    patient.current_risk = max_severity(s for s in sev if s in ("RED", "AMBER"))  # INFO tasks don't raise risk
    return patient.current_risk


def _transition(alert: Alert, new_status: str) -> None:
    if new_status == alert.status:
        return
    if new_status not in TRANSITIONS.get(alert.status, set()):
        raise HTTPException(409, f"Cannot move alert from {alert.status} to {new_status}")
    alert.status = new_status


def record_action(db: Session, *, alert: Alert | None, patient_id, actor: User, action_type: str,
                  note: str | None = None, contact_method: str | None = None, outcome: str | None = None,
                  internal: bool = True) -> CareTeamAction:
    action = CareTeamAction(alert_id=alert.id if alert else None, patient_id=patient_id, actor_id=actor.id,
                            action_type=action_type, note=note, contact_method=contact_method, outcome=outcome,
                            internal=internal)
    db.add(action)
    db.flush()
    audit.record(db, f"CARE_TEAM_{action_type}", actor=actor, patient_id=patient_id, resource_type="alert",
                 resource_id=alert.id if alert else None,
                 details={"contact_method": contact_method, "outcome": outcome, "has_note": bool(note),
                          "alert_status": alert.status if alert else None})
    return action


def acknowledge(db: Session, alert: Alert, actor: User, note: str | None = None) -> Alert:
    _transition(alert, "ACKNOWLEDGED")
    alert.acknowledged_at = alert.acknowledged_at or now()
    alert.acknowledged_by_id = actor.id
    alert.assigned_user_id = alert.assigned_user_id or actor.id
    record_action(db, alert=alert, patient_id=alert.patient_id, actor=actor, action_type="ACKNOWLEDGE", note=note)
    metrics.observe("alert_ack_minutes", (alert.acknowledged_at - alert.created_at).total_seconds() / 60 * 1000,
                    severity=alert.severity)
    return alert


def record_contact(db: Session, alert: Alert, actor: User, method: str, outcome: str, note: str | None) -> Alert:
    """outcome: REACHED | NO_ANSWER | LEFT_VOICEMAIL | WRONG_NUMBER"""
    if alert.status in ("NEW", "ACKNOWLEDGED", "ESCALATED"):
        if alert.status == "NEW":
            acknowledge(db, alert, actor)
        _transition(alert, "CONTACT_IN_PROGRESS")
    if outcome == "REACHED" and not alert.first_contact_at:
        alert.first_contact_at = now()
        metrics.observe("alert_time_to_contact_ms", (alert.first_contact_at - alert.created_at).total_seconds() * 1000,
                        severity=alert.severity)
    record_action(db, alert=alert, patient_id=alert.patient_id, actor=actor,
                  action_type="CONTACT_MADE" if outcome == "REACHED" else "CONTACT_ATTEMPT",
                  contact_method=method, outcome=outcome, note=note)
    return alert


def resolve(db: Session, alert: Alert, actor: User, resolution: str, outcome: str | None = None) -> Alert:
    _transition(alert, "RESOLVED")
    alert.resolved_at = now()
    alert.resolution = resolution
    record_action(db, alert=alert, patient_id=alert.patient_id, actor=actor, action_type="RESOLVE",
                  note=resolution, outcome=outcome)
    db.flush()
    refresh_patient_risk(db, alert.patient)
    return alert


def close(db: Session, alert: Alert, actor: User, note: str | None = None) -> Alert:
    _transition(alert, "CLOSED")
    alert.closed_at = now()
    record_action(db, alert=alert, patient_id=alert.patient_id, actor=actor, action_type="CLOSE", note=note)
    db.flush()
    refresh_patient_risk(db, alert.patient)
    return alert


def escalate(db: Session, alert: Alert, actor: User, to_role: str, reason: str,
             to_user_id: uuid.UUID | None = None) -> Escalation:
    _transition(alert, "ESCALATED")
    if to_user_id is None and to_role == "SURGEON":
        from app.services.patients import active_episode

        ep = active_episode(db, alert.patient_id)
        to_user_id = ep.surgeon_id if ep else None
    esc = Escalation(alert_id=alert.id, patient_id=alert.patient_id, from_user_id=actor.id, to_role=to_role,
                     to_user_id=to_user_id, reason=reason)
    db.add(esc)
    db.flush()
    record_action(db, alert=alert, patient_id=alert.patient_id, actor=actor, action_type="ESCALATE",
                  note=reason, outcome=f"ESCALATED_TO_{to_role}")
    target = db.get(User, to_user_id) if to_user_id else None
    if target:
        notify(db, category="CARE_TEAM_ESCALATION", user=target, title=f"Escalation: {alert.patient.full_name}",
               body=f"{actor.full_name} escalated a {alert.severity} alert: {reason}", channels=("IN_APP", "EMAIL"),
               dedupe_key=f"esc:{esc.id}")
    metrics.inc("escalations_created", to_role=to_role)
    return esc


def sla_status(alert: Alert, at: datetime | None = None) -> dict:
    at = at or now()
    if alert.status in ("RESOLVED", "CLOSED"):
        return {"state": "MET" if not alert.sla_breached else "BREACHED", "minutes_remaining": None}
    remaining = (alert.due_at - at).total_seconds() / 60
    # Response SLA is satisfied once a human has acknowledged the alert.
    if alert.acknowledged_at:
        met = alert.acknowledged_at <= alert.due_at
        return {"state": "MET" if met else "BREACHED", "minutes_remaining": round(remaining)}
    state = "BREACHED" if remaining < 0 else ("DUE_SOON" if remaining < max(5, alert.required_response_minutes * 0.25)
                                              else "ON_TRACK")
    return {"state": state, "minutes_remaining": round(remaining)}


def severity_rank(sev: str) -> int:
    return SEVERITY_ORDER.get(sev, 0)
