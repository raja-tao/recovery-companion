"""Patient-scoped endpoints (patient self-service + care-team views)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.alerting import AlertEscalationAgent
from agents.care_team_summary import CareTeamSummaryAgent
from agents.checkin_analysis import CheckinAnalysisAgent, questions_for
from agents.recovery_plan import RecoveryPlanAgent
from app.api.deps import get_current_user, my_patient, patient_access, require
from app.api.serializers import (
    alert_out, appointment_out, caregiver_out, checkin_out, iso, medication_out, message_out, patient_out,
)
from app.core.database import get_db
from app.core.security import CAREGIVER_SCOPES, Perm, Role, has_perm
from app.models import (
    Alert, Appointment, Caregiver, CaregiverPermission, CareTeamAction, Checkin, Conversation, Medication,
    MedicationEvent, Message, MoodEntry, Patient, RecoveryTask, TaskCompletion, User,
)
from app.schemas import (
    AppointmentCreate, CaregiverAuthorize, CareTeamMessage, CheckinResult, CheckinSubmit, MedicationEventCreate,
    MedicationGuidance, NoteCreate, TransportationUpdate,
)
from app.services import audit
from app.services.alerts import OPEN_STATUSES, record_action
from app.services.notifications import notify
from app.services.patients import (
    active_episode, approved_plan_version, phase_for_day, recovery_day, tasks_for_day,
)
from app.services.timeline import build_timeline
from app.services import proms
from app.services import transport as transport_svc

router = APIRouter(prefix="/patients", tags=["Patients"])


# =========================================================================== helpers
def medication_slots(db: Session, patient: Patient, on: date) -> list[dict]:
    meds = db.scalars(select(Medication).where(Medication.patient_id == patient.id, Medication.is_active.is_(True))
                      .order_by(Medication.name)).all()
    start = datetime.combine(on, time.min, tzinfo=timezone.utc)
    events = db.scalars(select(MedicationEvent).where(
        MedicationEvent.patient_id == patient.id, MedicationEvent.scheduled_for >= start,
        MedicationEvent.scheduled_for < start + timedelta(days=1))).all()
    by_slot = {(e.medication_id, e.scheduled_for.astimezone(timezone.utc).strftime("%H:%M")): e for e in events}
    now = datetime.now(timezone.utc)
    slots = []
    for m in meds:
        if m.start_date > on or (m.end_date and m.end_date < on):
            continue
        for t in (m.schedule_times or []):
            hh, mm = map(int, t.split(":"))
            sched = datetime.combine(on, time(hh, mm), tzinfo=timezone.utc)
            ev = by_slot.get((m.id, t))
            status = ev.status if ev else ("OVERDUE" if sched < now - timedelta(hours=2) else
                                           "DUE" if sched <= now + timedelta(minutes=30) else "UPCOMING")
            slots.append({"medication_id": str(m.id), "name": m.name, "dose_text": m.dose_text, "time": t,
                          "scheduled_for": sched.isoformat(), "status": status, "recorded": ev is not None,
                          "instructions": m.instructions, "as_needed": False})
        if m.as_needed:
            taken_today = sum(1 for e in events if e.medication_id == m.id and e.status == "TAKEN")
            slots.append({"medication_id": str(m.id), "name": m.name, "dose_text": m.dose_text, "time": "As needed",
                          "scheduled_for": None, "status": f"TAKEN x{taken_today}" if taken_today else "AS_NEEDED",
                          "recorded": False, "instructions": m.instructions, "as_needed": True})
    slots.sort(key=lambda s: (s["as_needed"], s["time"]))
    return slots


def _care_messages(db: Session, patient_id) -> list[Message]:
    conv = db.scalars(select(Conversation).where(Conversation.patient_id == patient_id,
                                                 Conversation.channel == "CARE_TEAM")).first()
    if not conv:
        return []
    return list(db.scalars(select(Message).where(Message.conversation_id == conv.id)
                           .order_by(Message.created_at.desc()).limit(30)))


def patient_status_message(db: Session, patient: Patient) -> dict | None:
    """Patient-facing escalation status (no internal detail)."""
    open_alert = db.scalars(select(Alert).where(
        Alert.patient_id == patient.id, Alert.status.in_(OPEN_STATUSES), Alert.severity.in_(["RED", "AMBER"]))
        .order_by(Alert.created_at.desc())).first()
    if not open_alert:
        return None
    text = {
        "NEW": "Your care team has been notified and will contact you.",
        "ACKNOWLEDGED": "A nurse is reviewing your information now.",
        "CONTACT_IN_PROGRESS": "Your care team is contacting you.",
        "ESCALATED": "Your nurse has asked your surgeon's team to review your information.",
    }[open_alert.status]
    return {"severity": open_alert.severity, "status": open_alert.status, "message": text,
            "since": iso(open_alert.created_at)}


# =========================================================================== self
@router.get("/me", summary="Current patient's profile")
def get_me(user: User = Depends(require(Perm.SELF_PLAN_READ)), db: Session = Depends(get_db)):
    p = my_patient(db, user)
    ep = active_episode(db, p.id)
    return patient_out(p) | {"episode": _episode_out(ep)}


def _episode_out(ep):
    if not ep:
        return None
    day = recovery_day(ep)
    return {"id": str(ep.id), "procedure_type": ep.procedure_type, "procedure_name": ep.procedure_name,
            "surgery_date": iso(ep.surgery_date), "discharge_date": iso(ep.discharge_date), "hospital": ep.hospital,
            "surgeon": ep.surgeon.full_name if ep.surgeon else None, "recovery_day": day,
            "phase": phase_for_day(day)}


@router.get("", summary="Patient list (care team / admin)")
def list_patients(user: User = Depends(require(Perm.PATIENT_LIST)), db: Session = Depends(get_db),
                  risk: str | None = None, q: str | None = None):
    stmt = select(Patient).order_by(Patient.last_name)
    if risk:
        stmt = stmt.where(Patient.current_risk == risk)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Patient.first_name + " " + Patient.last_name).like(like) |
                          func.lower(Patient.mrn).like(like))
    out = []
    for p in db.scalars(stmt):
        ep = active_episode(db, p.id)
        out.append(patient_out(p) | {"episode": _episode_out(ep)})
    return out


@router.get("/{patient_id}", summary="Patient profile + episode")
def get_patient(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_PLAN_READ, staff_perm=Perm.PATIENT_SUMMARY,
                       audit_action="PHI_VIEW_PROFILE")
    db.commit()
    return patient_out(p) | {"episode": _episode_out(active_episode(db, p.id))}


@router.get("/{patient_id}/dashboard", summary="Patient home screen data")
def dashboard(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_PLAN_READ, staff_perm=Perm.PATIENT_SUMMARY)
    ep = active_episode(db, p.id)
    today = date.today()
    day = recovery_day(ep) if ep else 0
    _, version = approved_plan_version(db, p.id)
    todays = db.scalars(select(Checkin).where(Checkin.patient_id == p.id, Checkin.checkin_date == today,
                                              Checkin.status == "COMPLETED").order_by(Checkin.submitted_at.desc())).first()
    next_appt = db.scalars(select(Appointment).where(
        Appointment.patient_id == p.id, Appointment.status == "SCHEDULED",
        Appointment.scheduled_at >= datetime.now(timezone.utc)).order_by(Appointment.scheduled_at)).first()
    completed = db.scalar(select(func.count()).select_from(Checkin).where(Checkin.patient_id == p.id,
                                                                          Checkin.status == "COMPLETED")) or 0
    msgs = _care_messages(db, p.id)
    return {
        "patient": patient_out(p), "episode": _episode_out(ep), "recovery_day": day, "phase": phase_for_day(day),
        "phases": RecoveryPlanAgent.phases(), "progress_pct": max(0, min(100, round(day / 30 * 100))),
        "plan_approved": version is not None,
        "tasks": tasks_for_day(db, p, version, day, today),
        "checkin": {"completed_today": todays is not None, "risk_level": todays.risk_level if todays else None,
                    "submitted_at": iso(todays.submitted_at) if todays else None, "total_completed": completed},
        "medications": medication_slots(db, p, today),
        "next_appointment": _appointment_with_ride(db, next_appt) if next_appt else None,
        "care_team_messages": [message_out(m) for m in msgs[:5]],
        "unread_messages": sum(1 for m in msgs if m.sender_type == "CARE_TEAM" and not m.read_at),
        "escalation_status": patient_status_message(db, p),
        "current_risk": p.current_risk,
        "mood": _recent_moods(db, p),
        "surveys_due": [s for s in proms.surveys_for(db, p.id, ep.procedure_type if ep else None,
                                                      day if ep else None) if s["state"] == "DUE"],
    }


def _appointment_with_ride(db: Session, a: Appointment) -> dict:
    return appointment_out(a) | {"transport": transport_svc.request_out(transport_svc.open_request(db, a.id))}


def _recent_moods(db: Session, p: Patient) -> list[dict]:
    rows = db.scalars(select(MoodEntry).where(MoodEntry.patient_id == p.id,
                                              MoodEntry.recorded_at >= datetime.now(timezone.utc) - timedelta(days=7))
                      .order_by(MoodEntry.recorded_at.desc())).all()
    latest: dict = {}
    for r in rows:  # newest first → keep the latest entry per day
        latest.setdefault(r.recorded_at.date(), r)
    return [{"date": d.isoformat(), "mood": r.mood, "score": r.score} for d, r in sorted(latest.items())]


# =========================================================================== recovery plan
@router.get("/{patient_id}/recovery-plan", summary="Approved 30-day recovery plan")
def recovery_plan(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_PLAN_READ, staff_perm=Perm.PATIENT_SUMMARY)
    plan, version = approved_plan_version(db, p.id)
    ep = active_episode(db, p.id)
    if not version:
        return {"approved": False, "message": "Your recovery plan is waiting for clinician approval. "
                                              "Please follow your printed discharge instructions and contact your care team."}
    day = recovery_day(ep) if ep else 0
    tasks = db.scalars(select(RecoveryTask).where(RecoveryTask.plan_version_id == version.id)
                       .order_by(RecoveryTask.day_from, RecoveryTask.category)).all()
    return {
        "approved": True, "plan_id": str(plan.id), "title": plan.title, "version": version.version,
        "status": version.status, "created_by": version.created_by.full_name if version.created_by else None,
        "approved_by": version.approved_by.full_name if version.approved_by else None,
        "approved_at": iso(version.approved_at), "procedure_type": ep.procedure_type if ep else None,
        "procedure_name": ep.procedure_name if ep else None, "surgery_date": iso(ep.surgery_date) if ep else None,
        "recovery_day": day, "phase": phase_for_day(day), "phases": RecoveryPlanAgent.phases(),
        "content": version.content,
        "tasks": [{"id": str(t.id), "day_from": t.day_from, "day_to": t.day_to, "category": t.category,
                   "title": t.title, "detail": t.detail} for t in tasks],
    }


@router.post("/{patient_id}/tasks/{task_id}/complete", summary="Mark today's task done")
def complete_task(patient_id: uuid.UUID, task_id: uuid.UUID, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=None)
    task = db.get(RecoveryTask, task_id)
    if not task or task.patient_id != p.id:
        raise HTTPException(404, "Task not found")
    exists = db.scalars(select(TaskCompletion).where(TaskCompletion.task_id == task.id,
                                                     TaskCompletion.for_date == date.today())).first()
    if exists:
        db.delete(exists)
        done = False
    else:
        db.add(TaskCompletion(task_id=task.id, patient_id=p.id, for_date=date.today(), completed_by_id=user.id))
        done = True
    audit.record(db, "TASK_TOGGLED", actor=user, patient_id=p.id, resource_type="recovery_task", resource_id=task.id,
                 details={"completed": done})
    db.commit()
    return {"task_id": str(task.id), "completed": done}


# =========================================================================== check-ins
@router.get("/{patient_id}/checkin-questions", summary="Configured check-in questions for this patient's procedure")
def checkin_questions(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=Perm.CHECKIN_READ)
    ep = active_episode(db, p.id)
    return [{"key": q.key, "text": q.text, "answer_type": q.answer_type, "options": q.options,
             "min_value": q.min_value, "max_value": q.max_value, "unit": q.unit, "required": q.required,
             "help_text": q.help_text} for q in questions_for(db, ep.procedure_type if ep else None)]


@router.post("/{patient_id}/checkins", response_model=CheckinResult, summary="Submit daily check-in")
def submit_checkin(patient_id: uuid.UUID, body: CheckinSubmit, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=None)
    outcome = CheckinAnalysisAgent().submit(db, p, user, body.answers)
    db.commit()
    return {
        "checkin_id": str(outcome.checkin.id), "recovery_day": outcome.checkin.recovery_day,
        "risk_level": outcome.evaluation.risk_level, "rules_triggered": outcome.evaluation.as_json(),
        "alerts_created": [str(a.id) for a in outcome.alerts], "patient_message": outcome.patient_message,
        "emergency": any(m.severity == "RED" and m.category == "EMERGENCY" for m in outcome.evaluation.matches),
    }


@router.get("/{patient_id}/checkins", summary="Check-in history")
def list_checkins(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  limit: int = Query(30, le=100)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=Perm.CHECKIN_READ,
                       audit_action="PHI_VIEW_CHECKINS")
    db.commit()
    rows = db.scalars(select(Checkin).where(Checkin.patient_id == p.id)
                      .order_by(Checkin.checkin_date.desc(), Checkin.submitted_at.desc()).limit(limit))
    return [checkin_out(c) for c in rows]


# =========================================================================== medications
@router.get("/{patient_id}/medications", summary="Medication list + today's schedule")
def list_medications(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_MEDS, staff_perm=Perm.MEDICATION_READ,
                       audit_action="PHI_VIEW_MEDICATIONS")
    db.commit()
    meds = db.scalars(select(Medication).where(Medication.patient_id == p.id).order_by(Medication.name)).all()
    events = db.scalars(select(MedicationEvent).where(MedicationEvent.patient_id == p.id)
                        .order_by(MedicationEvent.scheduled_for.desc()).limit(80)).all()
    names = {m.id: m.name for m in meds}
    counts = {"TAKEN": 0, "MISSED": 0, "SKIPPED": 0, "UNKNOWN": 0}
    for e in events:
        counts[e.status] = counts.get(e.status, 0) + 1
    denom = counts["TAKEN"] + counts["MISSED"] + counts["SKIPPED"]
    return {
        "medications": [medication_out(m) for m in meds],
        "today": medication_slots(db, p, date.today()),
        "recent_events": [{"id": str(e.id), "medication_id": str(e.medication_id), "name": names.get(e.medication_id),
                           "scheduled_for": iso(e.scheduled_for), "status": e.status, "recorded_at": iso(e.recorded_at)}
                          for e in events[:30]],
        "adherence": {"counts": counts, "rate": round(counts["TAKEN"] / denom, 3) if denom else None},
        "notice": "Doses and schedules are set by your prescriber. The app and assistant cannot change them.",
    }


@router.post("/{patient_id}/medications/{medication_id}/events", summary="Record dose TAKEN/MISSED/SKIPPED/UNKNOWN")
def record_med_event(patient_id: uuid.UUID, medication_id: uuid.UUID, body: MedicationEventCreate,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_MEDS, staff_perm=None)
    med = db.get(Medication, medication_id)
    if not med or med.patient_id != p.id:
        raise HTTPException(404, "Medication not found")
    sched = body.scheduled_for or datetime.now(timezone.utc)
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    existing = None
    if not med.as_needed:
        existing = db.scalars(select(MedicationEvent).where(MedicationEvent.medication_id == med.id,
                                                            MedicationEvent.scheduled_for == sched)).first()
    if existing:
        existing.status, existing.note, existing.recorded_at = body.status, body.note, datetime.now(timezone.utc)
        ev = existing
    else:
        ev = MedicationEvent(medication_id=med.id, patient_id=p.id, scheduled_for=sched, status=body.status,
                             recorded_by_id=user.id, note=body.note)
        db.add(ev)
    db.flush()
    audit.record(db, "MEDICATION_EVENT", actor=user, patient_id=p.id, resource_type="medication_event",
                 resource_id=ev.id, details={"medication": med.name, "status": body.status, "scheduled_for": iso(sched)})
    alert_id = None
    # Two or more missed doses in 48h → adherence follow-up (deterministic system policy).
    if body.status == "MISSED":
        since = datetime.now(timezone.utc) - timedelta(hours=48)
        missed = db.scalar(select(func.count()).select_from(MedicationEvent).where(
            MedicationEvent.patient_id == p.id, MedicationEvent.status == "MISSED",
            MedicationEvent.scheduled_for >= since)) or 0
        if missed >= 2:
            a = AlertEscalationAgent().from_policy(db, p, "MED-ADHERENCE-MISSED",
                                                   f"{missed} missed medication doses in 48 h",
                                                   [{"fact": "missed_doses_48h", "op": ">=", "threshold": 2,
                                                     "actual": missed}], source="MEDICATION", actor=user)
            alert_id = str(a.id)
    db.commit()
    return {"id": str(ev.id), "status": ev.status, "scheduled_for": iso(ev.scheduled_for), "alert_id": alert_id}


@router.post("/{patient_id}/medications/{medication_id}/guidance",
             summary="Doctor approves missed-dose guidance for a medication (treatment decision)")
def approve_guidance(patient_id: uuid.UUID, medication_id: uuid.UUID, body: MedicationGuidance,
                     user: User = Depends(require(Perm.MEDICATION_GUIDANCE)), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=None, staff_perm=Perm.MEDICATION_GUIDANCE)
    med = db.get(Medication, medication_id)
    if not med or med.patient_id != p.id:
        raise HTTPException(404, "Medication not found")
    previous = med.missed_dose_guidance
    med.missed_dose_guidance, med.guidance_approved_by = body.missed_dose_guidance.strip(), user.full_name
    audit.record(db, "MEDICATION_GUIDANCE_APPROVED", actor=user, patient_id=p.id, resource_type="medication",
                 resource_id=med.id, details={"medication": med.name, "replaced_existing": previous is not None})
    # Close the reconciliation task once every active medication has approved guidance.
    pending = db.scalar(select(func.count()).select_from(Medication).where(
        Medication.patient_id == p.id, Medication.is_active.is_(True), Medication.as_needed.is_(False),
        Medication.missed_dose_guidance.is_(None))) or 0
    if not pending:
        from app.services import alerts as alert_svc

        for a in db.scalars(select(Alert).where(Alert.patient_id == p.id, Alert.rule_id == "INT-MED-RECONCILE",
                                                Alert.status.in_(OPEN_STATUSES))):
            alert_svc.resolve(db, a, user, "Medications reconciled; missed-dose guidance approved by the doctor.")
    db.commit()
    return medication_out(med) | {"pending_guidance": pending}


# =========================================================================== appointments
@router.get("/{patient_id}/appointments", summary="Appointments")
def list_appointments(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_APPOINTMENTS, staff_perm=Perm.APPOINTMENT_READ)
    rows = db.scalars(select(Appointment).where(Appointment.patient_id == p.id).order_by(Appointment.scheduled_at))
    return [_appointment_with_ride(db, a) for a in rows]


@router.post("/{patient_id}/appointments", summary="Create appointment (care team)")
def create_appointment(patient_id: uuid.UUID, body: AppointmentCreate, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=None, staff_perm=Perm.APPOINTMENT_WRITE)
    ep = active_episode(db, p.id)
    appt = Appointment(patient_id=p.id, episode_id=ep.id if ep else None, created_by_id=user.id, **body.model_dump())
    db.add(appt)
    db.flush()
    audit.record(db, "APPOINTMENT_CREATED", actor=user, patient_id=p.id, resource_type="appointment",
                 resource_id=appt.id, details=body.model_dump(mode="json"))
    if p.user_id:
        notify(db, category="APPOINTMENT_REMINDER", user=db.get(User, p.user_id), patient=p,
               title="New appointment scheduled",
               body=f"{appt.appointment_type.replace('_', ' ').title()} with {appt.provider_name} on "
                    f"{appt.scheduled_at:%b %d at %H:%M}, {appt.location}.")
    db.commit()
    return appointment_out(appt)


@router.post("/{patient_id}/appointments/{appointment_id}/transportation",
             summary="Answer the transportation question; NEEDS_HELP creates a coordinator task")
def transportation(patient_id: uuid.UUID, appointment_id: uuid.UUID, body: TransportationUpdate,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_APPOINTMENTS, staff_perm=Perm.APPOINTMENT_WRITE)
    appt = db.get(Appointment, appointment_id)
    if not appt or appt.patient_id != p.id:
        raise HTTPException(404, "Appointment not found")
    alert_id = None
    if body.status == "NEEDS_HELP":
        r = transport_svc.create_request(db, user, p, appt, kind="HELP_FINDING_RIDE", pickup_address=None,
                                         requested_pickup_at=None, return_trip=True, mobility_needs=[],
                                         companion=False, note=body.note)
        alert_id = str(r.alert_id)
    else:
        existing = transport_svc.open_request(db, appt.id)
        if existing:
            transport_svc.cancel(db, user, existing, "Patient has their own ride")
        appt.transportation_status, appt.transportation_note = "CONFIRMED", body.note
    audit.record(db, "TRANSPORTATION_UPDATED", actor=user, patient_id=p.id, resource_type="appointment",
                 resource_id=appt.id, details={"status": body.status, "alert": alert_id})
    db.commit()
    return _appointment_with_ride(db, appt) | {"alert_id": alert_id,
                                    "message": "A care coordinator will contact you to help arrange transportation."
                                    if alert_id else "Thanks — see you at your appointment."}


# =========================================================================== timeline / summary / alerts
@router.get("/{patient_id}/timeline", summary="Complete, timestamped patient timeline")
def timeline(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_PLAN_READ, staff_perm=Perm.PATIENT_TIMELINE,
                       audit_action="PHI_VIEW_TIMELINE")
    db.commit()
    internal = user.role_name != Role.PATIENT.value
    return build_timeline(db, p, include_internal=internal)


@router.get("/{patient_id}/summary", summary="Care-team summary (Care-Team Summary Agent)")
def summary(patient_id: uuid.UUID, user: User = Depends(require(Perm.PATIENT_SUMMARY)), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=None, staff_perm=Perm.PATIENT_SUMMARY,
                       audit_action="PHI_VIEW_SUMMARY")
    db.commit()
    return CareTeamSummaryAgent().summarize(db, p, include_checkin_details=has_perm(user.role_name, Perm.CHECKIN_READ))


@router.get("/{patient_id}/alerts", summary="Alerts for a patient")
def patient_alerts(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=None, staff_perm=Perm.ALERT_READ)
    q = select(Alert).where(Alert.patient_id == p.id).order_by(Alert.created_at.desc())
    return [alert_out(a) for a in db.scalars(q)]


@router.get("/{patient_id}/notes", summary="Care-team actions and notes (internal)")
def notes(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=None, staff_perm=Perm.NOTE_READ)
    rows = db.scalars(select(CareTeamAction).where(CareTeamAction.patient_id == p.id)
                      .order_by(CareTeamAction.created_at.desc()))
    return [{"id": str(a.id), "action_type": a.action_type, "contact_method": a.contact_method, "outcome": a.outcome,
             "note": a.note, "alert_id": str(a.alert_id) if a.alert_id else None, "created_at": iso(a.created_at),
             "actor": a.actor.full_name if a.actor else None} for a in rows]


@router.post("/{patient_id}/notes", summary="Add internal care-team note")
def add_note(patient_id: uuid.UUID, body: NoteCreate, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=None, staff_perm=Perm.NOTE_WRITE)
    alert = db.get(Alert, uuid.UUID(body.alert_id)) if body.alert_id else None
    act = record_action(db, alert=alert, patient_id=p.id, actor=user, action_type="NOTE", note=body.note)
    db.commit()
    return {"id": str(act.id)}


# =========================================================================== messages
@router.get("/{patient_id}/messages", summary="Care-team ↔ patient messages")
def messages(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_PLAN_READ, staff_perm=Perm.MESSAGE_PATIENT)
    msgs = _care_messages(db, p.id)
    if user.role_name == Role.PATIENT.value:
        now = datetime.now(timezone.utc)
        for m in msgs:
            if m.sender_type == "CARE_TEAM" and not m.read_at:
                m.read_at = now
        db.commit()
    return [message_out(m) for m in reversed(msgs)]


@router.post("/{patient_id}/messages", summary="Send a message (care team → patient, or patient → care team)")
def send_message(patient_id: uuid.UUID, body: CareTeamMessage, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_PLAN_READ, staff_perm=Perm.MESSAGE_PATIENT)
    conv = db.scalars(select(Conversation).where(Conversation.patient_id == p.id,
                                                 Conversation.channel == "CARE_TEAM")).first()
    if not conv:
        conv = Conversation(patient_id=p.id, user_id=p.user_id, channel="CARE_TEAM")
        db.add(conv)
        db.flush()
    is_patient = user.role_name == Role.PATIENT.value
    msg = Message(conversation_id=conv.id, patient_id=p.id, sender_type="PATIENT" if is_patient else "CARE_TEAM",
                  sender_user_id=user.id, content=body.content)
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc)
    db.flush()
    if not is_patient and p.user_id:
        notify(db, category="MESSAGE", user=db.get(User, p.user_id), patient=p,
               title=f"Message from {user.full_name}", body=body.content[:300], channels=("IN_APP", "SMS"))
        record_action(db, alert=None, patient_id=p.id, actor=user, action_type="MESSAGE", contact_method="IN_APP",
                      note=body.content, internal=False)
    audit.record(db, "MESSAGE_SENT", actor=user, patient_id=p.id, resource_type="message", resource_id=msg.id)
    db.commit()
    return message_out(msg)


# =========================================================================== caregivers
@router.get("/{patient_id}/caregivers", summary="Caregivers authorized by the patient")
def list_caregivers(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CAREGIVERS, staff_perm=Perm.PATIENT_SUMMARY)
    rows = db.scalars(select(Caregiver).where(Caregiver.patient_id == p.id).order_by(Caregiver.authorized_at.desc()))
    return {"caregivers": [caregiver_out(c) for c in rows], "available_scopes": CAREGIVER_SCOPES}


@router.post("/{patient_id}/caregivers", summary="Authorize a caregiver (patient only)")
def authorize_caregiver(patient_id: uuid.UUID, body: CaregiverAuthorize, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CAREGIVERS, staff_perm=None)
    cg_user = db.scalars(select(User).where(func.lower(User.email) == body.caregiver_email.lower())).first()
    if not cg_user or cg_user.role_name != Role.CAREGIVER.value:
        raise HTTPException(404, "No caregiver account with that email. Ask them to register first.")
    link = db.scalars(select(Caregiver).where(Caregiver.user_id == cg_user.id, Caregiver.patient_id == p.id)).first()
    now = datetime.now(timezone.utc)
    if not link:
        link = Caregiver(user_id=cg_user.id, patient_id=p.id, relationship_to_patient=body.relationship_to_patient)
        db.add(link)
        db.flush()
    link.status, link.revoked_at, link.authorized_at = "ACTIVE", None, now
    link.relationship_to_patient = body.relationship_to_patient
    for perm in list(link.permissions):
        db.delete(perm)
    db.flush()
    link.permissions = [CaregiverPermission(scope=s) for s in sorted(set(body.scopes))]
    audit.record(db, "CAREGIVER_AUTHORIZED", actor=user, patient_id=p.id, resource_type="caregiver",
                 resource_id=link.id, details={"caregiver": cg_user.email, "scopes": sorted(set(body.scopes))})
    notify(db, category="MESSAGE", user=cg_user, title="Caregiver access granted",
           body=f"{p.first_name} has shared limited recovery information with you.")
    db.commit()
    db.refresh(link)
    return caregiver_out(link)


@router.delete("/{patient_id}/caregivers/{caregiver_id}", summary="Revoke caregiver access immediately")
def revoke_caregiver(patient_id: uuid.UUID, caregiver_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CAREGIVERS, staff_perm=None)
    link = db.get(Caregiver, caregiver_id)
    if not link or link.patient_id != p.id:
        raise HTTPException(404, "Caregiver not found")
    now = datetime.now(timezone.utc)
    link.status, link.revoked_at = "REVOKED", now
    for perm in link.permissions:
        perm.revoked_at = perm.revoked_at or now
    audit.record(db, "CAREGIVER_REVOKED", actor=user, patient_id=p.id, resource_type="caregiver", resource_id=link.id)
    db.commit()
    return caregiver_out(link)
