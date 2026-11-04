"""Caregiver view — only the scopes the patient explicitly granted. Never clinical
notes, check-in answers, free text, alerts detail or full medical history."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import caregiver_link, require
from app.api.patients import medication_slots, patient_status_message
from app.api.serializers import iso
from app.core.database import get_db
from app.core.security import Perm
from app.models import Appointment, Caregiver, Checkin, Patient, User
from app.services import audit
from app.services.patients import active_episode, approved_plan_version, phase_for_day, recovery_day, tasks_for_day

router = APIRouter(prefix="/caregiver", tags=["Caregiver"])


@router.get("/patients", summary="Patients who authorized this caregiver")
def my_patients(user: User = Depends(require(Perm.CAREGIVER_VIEW)), db: Session = Depends(get_db)):
    links = db.scalars(select(Caregiver).where(Caregiver.user_id == user.id)).all()
    out = []
    for link in links:
        p = db.get(Patient, link.patient_id)
        out.append({"patient_id": str(p.id), "first_name": p.first_name, "relationship": link.relationship_to_patient,
                    "status": link.status, "scopes": [x.scope for x in link.permissions if x.revoked_at is None]
                    if link.status == "ACTIVE" else [], "revoked_at": iso(link.revoked_at)})
    return out


@router.get("/patients/{patient_id}", summary="Limited, consented view of a patient's recovery")
def caregiver_view(patient_id: uuid.UUID, user: User = Depends(require(Perm.CAREGIVER_VIEW)),
                   db: Session = Depends(get_db)):
    link = caregiver_link(db, user, patient_id)
    scopes = {p.scope for p in link.permissions if p.revoked_at is None}
    p = db.get(Patient, patient_id)
    ep = active_episode(db, p.id)
    day = recovery_day(ep) if ep else 0
    view: dict = {"patient_first_name": p.first_name, "relationship": link.relationship_to_patient,
                  "granted_scopes": sorted(scopes),
                  "notice": "You can see only what the patient chose to share. Clinical details are not included."}
    if "RECOVERY_STATUS" in scopes:
        status = patient_status_message(db, p)
        view["recovery_status"] = {"phase": phase_for_day(day), "recovery_day": day,
                                   "care_team_following_up": bool(status),
                                   "message": "The care team is following up." if status else "On track — no open follow-ups."}
    if "PROGRESS" in scopes:
        done = db.scalars(select(Checkin).where(Checkin.patient_id == p.id, Checkin.checkin_date == date.today(),
                                                Checkin.status == "COMPLETED")).first()
        view["progress"] = {"recovery_day": day, "progress_pct": max(0, min(100, round(day / 30 * 100))),
                            "checked_in_today": done is not None}
    if "TASKS" in scopes:
        _, version = approved_plan_version(db, p.id)
        view["tasks"] = [{k: t[k] for k in ("title", "category", "completed")}
                         for t in tasks_for_day(db, p, version, day) if t["caregiver_visible"]]
    if "REMINDERS" in scopes:
        view["reminders"] = [{"name": s["name"], "time": s["time"], "status": s["status"]}
                             for s in medication_slots(db, p, date.today())]
        view["reminders_note"] = "Medication names and times only."
    if "APPOINTMENTS" in scopes:
        appts = db.scalars(select(Appointment).where(Appointment.patient_id == p.id,
                                                     Appointment.status == "SCHEDULED",
                                                     Appointment.scheduled_at >= datetime.now(timezone.utc))
                           .order_by(Appointment.scheduled_at)).all()
        view["appointments"] = [{"type": a.appointment_type, "scheduled_at": iso(a.scheduled_at),
                                 "location": a.location} for a in appts]
    audit.record(db, "CAREGIVER_VIEW", actor=user, patient_id=p.id, details={"scopes": sorted(scopes)})
    db.commit()
    return view
