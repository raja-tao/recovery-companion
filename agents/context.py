"""Intake / Context Agent — assembles the minimum patient context a workflow needs."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Medication, Patient, RecoveryPlanVersion, SurgicalEpisode
from app.services.patients import active_episode, approved_plan_version, phase_for_day, recovery_day


@dataclass
class PatientContext:
    patient: Patient
    episode: SurgicalEpisode | None
    plan_version: RecoveryPlanVersion | None
    recovery_day: int
    phase: dict
    medications: list[Medication]

    @property
    def procedure_type(self) -> str | None:
        return self.episode.procedure_type if self.episode else None

    def prompt_dict(self) -> dict:
        return {"procedure_name": self.episode.procedure_name if self.episode else "unknown",
                "recovery_day": self.recovery_day, "phase": self.phase["label"]}


class IntakeContextAgent:
    def load(self, db: Session, patient: Patient) -> PatientContext:
        ep = active_episode(db, patient.id)
        _, version = approved_plan_version(db, patient.id)
        day = recovery_day(ep) if ep else 0
        meds = db.scalars(select(Medication).where(Medication.patient_id == patient.id,
                                                   Medication.is_active.is_(True))).all()
        return PatientContext(patient, ep, version, day, phase_for_day(day), list(meds))
