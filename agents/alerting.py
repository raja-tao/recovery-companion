"""Alert / Escalation Agent — turns deterministic findings into care-team work items.

Severity, thresholds and response times always come from approved protocols or
fixed system policy below — never from an LLM.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from sqlalchemy import select

from app.models import Alert, Patient, User
from app.services import audit
from app.services.alerts import OPEN_STATUSES, create_alert
from rules.engine import SEVERITY_ORDER, RuleMatch

# System policy for AI-originated work items (documented in SAFETY_AND_GUARDRAILS.md).
AI_POLICY = {
    "AI-RED-EMERGENCY": dict(severity="RED", category="AI_SAFETY", minutes=15, team="NURSE"),
    "AI-AMBER-SYMPTOM": dict(severity="AMBER", category="SYMPTOM_REPORT", minutes=240, team="NURSE"),
    # Medication questions go to the doctor: only the doctor decides treatment.
    "AI-MED-DOSE-QUESTION": dict(severity="AMBER", category="MEDICATION_QUESTION", minutes=240, team="SURGEON"),
    "AI-MED-QUESTION": dict(severity="INFO", category="MEDICATION_QUESTION", minutes=1440, team="SURGEON"),
    "AI-UNANSWERED": dict(severity="INFO", category="UNANSWERED_QUESTION", minutes=1440, team="NURSE"),
    "APPT-TRANSPORT": dict(severity="AMBER", category="TRANSPORTATION", minutes=1440, team="COORDINATOR"),
    "MED-ADHERENCE-MISSED": dict(severity="AMBER", category="MEDICATION_ADHERENCE", minutes=1440, team="NURSE"),
    # New medications received from the EHR have no approved missed-dose guidance yet.
    "INT-MED-RECONCILE": dict(severity="INFO", category="MEDICATION_RECONCILIATION", minutes=1440, team="SURGEON"),
    # The pharmacy reported a prescription was not dispensed / picked up.
    "INT-RX-NOT-FILLED": dict(severity="AMBER", category="MEDICATION_FILL", minutes=480, team="NURSE"),
    # Wellbeing (mood asked at sign-in).
    "MOOD-SAFETY": dict(severity="RED", category="AI_SAFETY", minutes=15, team="NURSE"),
    "MOOD-LOW-TREND": dict(severity="AMBER", category="MOOD", minutes=1440, team="NURSE"),
    "MOOD-CONTACT-REQUEST": dict(severity="INFO", category="MOOD", minutes=1440, team="NURSE"),
    # Transport: no answer to the day-before ride question close to the appointment.
    "APPT-TRANSPORT-UNCONFIRMED": dict(severity="INFO", category="TRANSPORTATION", minutes=240, team="COORDINATOR"),
}


class AlertEscalationAgent:
    def from_rule_match(self, db: Session, patient: Patient, match: RuleMatch, *, episode_id=None, checkin_id=None,
                        source: str = "CHECKIN", actor: User | None = None) -> Alert:
        return create_alert(
            db, patient=patient, severity=match.severity, category=match.category, source=source,
            rule_id=match.rule_id, trigger_summary=match.name, evidence=match.evidence,
            response_minutes=match.response_minutes, assigned_team=match.assigned_team, episode_id=episode_id,
            checkin_id=checkin_id, protocol_id=match.protocol_id, actor=actor,
        )

    def from_checkin(self, db: Session, patient: Patient, matches: list[RuleMatch], *, episode_id=None,
                     checkin_id=None, actor: User | None = None) -> Alert:
        """One alert per check-in, carrying every matched rule as evidence.

        Primary rule = highest severity (matches are pre-sorted). Response time = the
        strictest matched protocol. If an open check-in alert of the same or higher
        severity already exists, the new findings are appended to it instead.
        """
        primary = matches[0]
        evidence = [{"rule_id": m.rule_id, "name": m.name, "severity": m.severity, "evidence": m.evidence}
                    for m in matches]
        summary = " + ".join(dict.fromkeys(m.name for m in matches))
        existing = db.scalars(select(Alert).where(
            Alert.patient_id == patient.id, Alert.source == "CHECKIN", Alert.status.in_(OPEN_STATUSES))
            .order_by(Alert.created_at.desc())).first()
        if existing and SEVERITY_ORDER[existing.severity] >= SEVERITY_ORDER[primary.severity]:
            existing.evidence = list(existing.evidence or []) + [{"checkin_id": str(checkin_id), "rules": evidence}]
            existing.checkin_id = checkin_id
            audit.record(db, "ALERT_REPEAT_TRIGGER", actor=actor, patient_id=patient.id, resource_type="alert",
                         resource_id=existing.id, details={"rules": [m.rule_id for m in matches]})
            return existing
        return create_alert(
            db, patient=patient, severity=primary.severity, category=primary.category, source="CHECKIN",
            rule_id=primary.rule_id, trigger_summary=summary, evidence=evidence,
            response_minutes=min(m.response_minutes for m in matches if m.severity == primary.severity),
            assigned_team=primary.assigned_team, episode_id=episode_id, checkin_id=checkin_id,
            protocol_id=primary.protocol_id, actor=actor, dedupe_open=False,
        )

    def from_policy(self, db: Session, patient: Patient, rule_id: str, summary: str, evidence: list, *,
                    source: str = "AI_ASSISTANT", actor: User | None = None, episode_id=None,
                    dedupe_open: bool = True) -> Alert:
        p = AI_POLICY[rule_id]
        return create_alert(
            db, patient=patient, severity=p["severity"], category=p["category"], source=source, rule_id=rule_id,
            trigger_summary=summary, evidence=evidence, response_minutes=p["minutes"], assigned_team=p["team"],
            actor=actor, episode_id=episode_id, dedupe_open=dedupe_open,
        )
