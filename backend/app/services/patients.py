"""Patient journey helpers: recovery day, phase, active episode, approved plan."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Patient, RecoveryPlan, RecoveryPlanVersion, RecoveryTask, SurgicalEpisode, TaskCompletion,
)

PHASES = [
    ("STABILIZE", 0, 3, "Stabilize", "Rest, manage pain, protect the incision and start gentle movement."),
    ("MONITOR", 4, 7, "Monitor", "Watch for warning signs and build a daily routine."),
    ("PROGRESS", 8, 14, "Progress", "Increase activity and exercises as instructed."),
    ("TRANSITION", 15, 30, "Transition", "Return to normal routines and prepare for discharge from the program."),
]


def phase_for_day(day: int) -> dict:
    for key, start, end, label, desc in PHASES:
        if start <= day <= end:
            return {"key": key, "label": label, "start_day": start, "end_day": end, "description": desc}
    if day < 0:
        return {"key": "PRE_OP", "label": "Pre-op", "start_day": None, "end_day": -1, "description": "Before surgery"}
    return {"key": "COMPLETED", "label": "Completed", "start_day": 31, "end_day": None,
            "description": "30-day program complete"}


def recovery_day(episode: SurgicalEpisode, on: date | None = None) -> int:
    return ((on or date.today()) - episode.surgery_date).days


def active_episode(db: Session, patient_id: uuid.UUID) -> SurgicalEpisode | None:
    return db.scalars(
        select(SurgicalEpisode).where(SurgicalEpisode.patient_id == patient_id)
        .order_by(SurgicalEpisode.surgery_date.desc())
    ).first()


def approved_plan_version(db: Session, patient_id: uuid.UUID) -> tuple[RecoveryPlan | None, RecoveryPlanVersion | None]:
    """Only APPROVED plan versions are presented to patients as clinical guidance."""
    plan = db.scalars(select(RecoveryPlan).where(RecoveryPlan.patient_id == patient_id)
                      .order_by(RecoveryPlan.created_at.desc())).first()
    if not plan:
        return None, None
    version = db.scalars(
        select(RecoveryPlanVersion).where(RecoveryPlanVersion.plan_id == plan.id,
                                          RecoveryPlanVersion.status == "APPROVED")
        .order_by(RecoveryPlanVersion.version.desc())
    ).first()
    return plan, version


def tasks_for_day(db: Session, patient: Patient, version: RecoveryPlanVersion | None, day: int,
                  on: date | None = None) -> list[dict]:
    if not version:
        return []
    on = on or date.today()
    tasks = db.scalars(select(RecoveryTask).where(
        RecoveryTask.plan_version_id == version.id, RecoveryTask.day_from <= day, RecoveryTask.day_to >= day,
    ).order_by(RecoveryTask.category, RecoveryTask.title)).all()
    done = set(db.scalars(select(TaskCompletion.task_id).where(
        TaskCompletion.patient_id == patient.id, TaskCompletion.for_date == on)).all())
    return [{"id": str(t.id), "category": t.category, "title": t.title, "detail": t.detail,
             "completed": t.id in done, "caregiver_visible": t.caregiver_visible} for t in tasks]


def patient_context(db: Session, patient: Patient) -> dict:
    ep = active_episode(db, patient.id)
    day = recovery_day(ep) if ep else 0
    return {
        "patient_id": str(patient.id), "name": patient.full_name,
        "procedure_type": ep.procedure_type if ep else None, "procedure_name": ep.procedure_name if ep else None,
        "surgery_date": ep.surgery_date.isoformat() if ep else None, "recovery_day": day,
        "phase": phase_for_day(day)["key"], "episode_id": str(ep.id) if ep else None,
    }
