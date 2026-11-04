"""Alerts, care-team worklist and escalations."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.serializers import alert_out, iso
from app.core.database import get_db
from app.core.security import Perm, Role
from app.models import Alert, Appointment, Checkin, Escalation, MedicationEvent, Patient, User
from app.schemas import AlertContact, AlertEscalate, AlertNote, AlertResolve, EscalationRespond
from app.services import alerts as svc
from app.services import audit
from app.services.alerts import OPEN_STATUSES, severity_rank

router = APIRouter(tags=["Care Team & Alerts"])

MEDICATION_CATEGORIES = ("MEDICATION_QUESTION", "MEDICATION_ADHERENCE", "MEDICATION_RECONCILIATION",
                         "MEDICATION_FILL")
ACTION_LABEL = {
    "CLINICAL": "Nurse review", "AI_SAFETY": "Nurse review — urgent", "SYMPTOM_REPORT": "Nurse review",
    "MISSED_CHECKIN": "Outreach", "MEDICATION_QUESTION": "Doctor review", "MEDICATION_ADHERENCE": "Outreach",
    "UNANSWERED_QUESTION": "Answer question", "TRANSPORTATION": "Coordinator: arrange transport",
    "EMERGENCY": "Nurse review — emergency", "MEDICATION_RECONCILIATION": "Doctor: reconcile medications",
    "MEDICATION_FILL": "Outreach: prescription not filled", "MOOD": "Nurse: wellbeing check-in",
}


def _get_alert(db: Session, alert_id: uuid.UUID, user: User) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return alert


@router.get("/care-team/worklist", summary="Prioritized worklist: patients needing attention")
def worklist(user: User = Depends(require(Perm.ALERT_READ)), db: Session = Depends(get_db),
             include_info: bool = True):
    stmt = select(Alert).where(Alert.status.in_(OPEN_STATUSES))
    if not include_info:
        stmt = stmt.where(Alert.severity != "INFO")
    alerts = db.scalars(stmt).all()
    last_checkins = dict(db.execute(select(Checkin.patient_id, func.max(Checkin.submitted_at))
                                    .where(Checkin.status == "COMPLETED").group_by(Checkin.patient_id)).all())
    rows = []
    for a in alerts:
        rows.append(alert_out(a) | {
            "patient_mrn": a.patient.mrn, "reason": a.trigger_summary,
            "last_checkin_at": iso(last_checkins.get(a.patient_id)),
            "action": ACTION_LABEL.get(a.category, "Review"),
        })
    rows.sort(key=lambda r: (-severity_rank(r["severity"]), r["due_at"]))

    now = datetime.now(timezone.utc)
    counts = {
        "red": sum(1 for r in rows if r["severity"] == "RED"),
        "amber": sum(1 for r in rows if r["severity"] == "AMBER"),
        "info": sum(1 for r in rows if r["severity"] == "INFO"),
        "missed_checkins": sum(1 for r in rows if r["category"] == "MISSED_CHECKIN"),
        "medication_issues": sum(1 for r in rows if r["category"] in MEDICATION_CATEGORIES),
        "sla_breached": sum(1 for r in rows if r["sla"]["state"] == "BREACHED"),
    }
    upcoming = []
    appts = db.scalars(select(Appointment).where(
        Appointment.status == "SCHEDULED", Appointment.scheduled_at >= now,
        Appointment.scheduled_at <= now + timedelta(days=3)).order_by(Appointment.scheduled_at)).all()
    for ap in appts:
        p = db.get(Patient, ap.patient_id)
        upcoming.append({"appointment_id": str(ap.id), "patient_id": str(p.id), "patient_name": p.full_name,
                         "type": ap.appointment_type, "scheduled_at": iso(ap.scheduled_at),
                         "provider": ap.provider_name, "transportation_status": ap.transportation_status})
    counts["upcoming_followups"] = len(upcoming)
    return {"counts": counts, "items": rows, "upcoming_followups": upcoming, "generated_at": iso(now)}


@router.get("/alerts", summary="List alerts (filterable)")
def list_alerts(user: User = Depends(require(Perm.ALERT_READ)), db: Session = Depends(get_db),
                status: str | None = None, severity: str | None = None, category: str | None = None,
                patient_id: uuid.UUID | None = None, limit: int = Query(100, le=500)):
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Alert.status.in_(status.split(",")))
    if severity:
        stmt = stmt.where(Alert.severity.in_(severity.split(",")))
    if category:
        stmt = stmt.where(Alert.category.in_(category.split(",")))
    if patient_id:
        stmt = stmt.where(Alert.patient_id == patient_id)
    return [alert_out(a) for a in db.scalars(stmt)]


@router.get("/alerts/{alert_id}", summary="Alert detail with evidence and action history")
def get_alert(alert_id: uuid.UUID, user: User = Depends(require(Perm.ALERT_READ)), db: Session = Depends(get_db)):
    a = _get_alert(db, alert_id, user)
    from app.models import CareTeamAction

    actions = db.scalars(select(CareTeamAction).where(CareTeamAction.alert_id == a.id)
                         .order_by(CareTeamAction.created_at)).all()
    escalations = db.scalars(select(Escalation).where(Escalation.alert_id == a.id)).all()
    audit.record(db, "PHI_VIEW_ALERT", actor=user, patient_id=a.patient_id, resource_type="alert", resource_id=a.id)
    db.commit()
    return alert_out(a) | {
        "actions": [{"action_type": x.action_type, "contact_method": x.contact_method, "outcome": x.outcome,
                     "note": x.note, "actor": x.actor.full_name if x.actor else None, "created_at": iso(x.created_at)}
                    for x in actions],
        "escalations": [{"id": str(e.id), "to_role": e.to_role, "reason": e.reason, "status": e.status,
                         "response_note": e.response_note, "created_at": iso(e.created_at)} for e in escalations],
    }


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: uuid.UUID, body: AlertNote | None = None, user: User = Depends(require(Perm.ALERT_WORK)),
                db: Session = Depends(get_db)):
    a = svc.acknowledge(db, _get_alert(db, alert_id, user), user, body.note if body else None)
    db.commit()
    return alert_out(a)


@router.post("/alerts/{alert_id}/contact", summary="Record patient outreach (call/SMS/video)")
def contact(alert_id: uuid.UUID, body: AlertContact, user: User = Depends(require(Perm.ALERT_WORK)),
            db: Session = Depends(get_db)):
    a = svc.record_contact(db, _get_alert(db, alert_id, user), user, body.method, body.outcome, body.note)
    db.commit()
    return alert_out(a)


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: uuid.UUID, body: AlertResolve, user: User = Depends(require(Perm.ALERT_WORK)),
            db: Session = Depends(get_db)):
    a = svc.resolve(db, _get_alert(db, alert_id, user), user, body.resolution, body.outcome)
    db.commit()
    return alert_out(a)


@router.post("/alerts/{alert_id}/escalate", summary="Escalate (e.g. nurse → surgeon)")
def escalate(alert_id: uuid.UUID, body: AlertEscalate, user: User = Depends(require(Perm.ALERT_WORK)),
             db: Session = Depends(get_db)):
    a = _get_alert(db, alert_id, user)
    esc = svc.escalate(db, a, user, body.to_role, body.reason)
    db.commit()
    return alert_out(a) | {"escalation_id": str(esc.id)}


@router.post("/alerts/{alert_id}/close")
def close(alert_id: uuid.UUID, body: AlertNote | None = None, user: User = Depends(require(Perm.ALERT_WORK)),
          db: Session = Depends(get_db)):
    a = svc.close(db, _get_alert(db, alert_id, user), user, body.note if body else None)
    db.commit()
    return alert_out(a)


@router.get("/escalations", summary="Escalations (surgeon review queue)")
def list_escalations(user: User = Depends(require(Perm.ESCALATION_REVIEW, Perm.ALERT_WORK)),
                     db: Session = Depends(get_db), status: str = "OPEN,ACKNOWLEDGED"):
    stmt = select(Escalation).where(Escalation.status.in_(status.split(","))).order_by(Escalation.created_at.desc())
    if user.role_name == Role.SURGEON.value:
        stmt = stmt.where((Escalation.to_user_id == user.id) | (Escalation.to_role == "SURGEON"))
    out = []
    for e in db.scalars(stmt):
        a = db.get(Alert, e.alert_id)
        out.append({"id": str(e.id), "alert": alert_out(a), "to_role": e.to_role, "reason": e.reason,
                    "status": e.status, "from": e.from_user.full_name if e.from_user else None,
                    "created_at": iso(e.created_at), "response_note": e.response_note})
    return out


@router.post("/escalations/{escalation_id}/respond", summary="Doctor response to an escalation")
def respond(escalation_id: uuid.UUID, body: EscalationRespond,
            user: User = Depends(require(Perm.ESCALATION_REVIEW, Perm.MEDICATION_TASKS)), db: Session = Depends(get_db)):
    e = db.get(Escalation, escalation_id)
    if not e:
        raise HTTPException(404, "Escalation not found")
    e.response_note, e.responded_at = body.response_note, datetime.now(timezone.utc)
    e.status = "COMPLETED" if body.complete else "ACKNOWLEDGED"
    a = db.get(Alert, e.alert_id)
    if a.status == "ESCALATED":
        svc._transition(a, "ACKNOWLEDGED")
    svc.record_action(db, alert=a, patient_id=a.patient_id, actor=user, action_type="NOTE",
                      note=f"Escalation response: {body.response_note}", outcome="ESCALATION_RESPONSE")
    db.commit()
    return {"id": str(e.id), "status": e.status, "alert": alert_out(a)}
