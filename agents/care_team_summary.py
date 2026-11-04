"""Care-Team Summary Agent — deterministic, fact-only handoff summary.

Built from structured data so nothing is inferred. (An LLM could be used for
wording via ModelRouter task CARE_TEAM_SUMMARY, but the POC keeps this
deterministic: clinicians see exactly what the data says.)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.context import IntakeContextAgent
from app.models import Alert, Appointment, CareTeamAction, Checkin, MedicationEvent, Patient
from app.services.alerts import OPEN_STATUSES

LABELS = {
    "pain_score": "Pain (0-10)", "pain_trend": "Pain trend", "temperature": "Temperature", "wound_appearance": "Wound",
    "swelling": "Swelling", "mobility": "Mobility", "walking_minutes": "Walking (min)",
    "medication_adherence": "Medication adherence", "new_symptoms": "New symptoms",
}


class CareTeamSummaryAgent:
    def summarize(self, db: Session, patient: Patient, include_checkin_details: bool = True) -> dict:
        ctx = IntakeContextAgent().load(db, patient)
        last = db.scalars(select(Checkin).where(Checkin.patient_id == patient.id, Checkin.status == "COMPLETED")
                          .order_by(Checkin.submitted_at.desc())).first()
        open_alerts = db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.status.in_(OPEN_STATUSES))
                                 .order_by(Alert.created_at.desc())).all()
        since = datetime.now(timezone.utc) - timedelta(hours=72)
        med_counts = dict(db.execute(select(MedicationEvent.status, func.count()).where(
            MedicationEvent.patient_id == patient.id, MedicationEvent.scheduled_for >= since)
            .group_by(MedicationEvent.status)).all())
        taken = med_counts.get("TAKEN", 0)
        total = sum(med_counts.get(s, 0) for s in ("TAKEN", "MISSED", "SKIPPED"))
        next_appt = db.scalars(select(Appointment).where(
            Appointment.patient_id == patient.id, Appointment.status == "SCHEDULED",
            Appointment.scheduled_at >= datetime.now(timezone.utc)).order_by(Appointment.scheduled_at)).first()
        last_contact = db.scalars(select(CareTeamAction).where(
            CareTeamAction.patient_id == patient.id, CareTeamAction.action_type == "CONTACT_MADE")
            .order_by(CareTeamAction.created_at.desc())).first()

        bullets = [
            f"{patient.full_name}, {ctx.episode.procedure_name if ctx.episode else 'no active episode'} — "
            f"post-op day {ctx.recovery_day} ({ctx.phase['label']} phase).",
            f"Current risk: {patient.current_risk}; {len(open_alerts)} open alert(s)"
            + (": " + "; ".join(f"{a.severity} {a.trigger_summary}" for a in open_alerts[:3]) if open_alerts else "."),
        ]
        if last:
            if include_checkin_details:
                vals = {r.question_key: r.value.get("v") for r in last.responses}
                parts = [f"{LABELS.get(k, k)}: {v if not isinstance(v, list) else ', '.join(v) or 'none'}"
                         for k, v in vals.items() if k in LABELS]
                bullets.append(f"Last check-in day {last.recovery_day} ({last.risk_level}): " + "; ".join(parts))
            else:
                bullets.append(f"Last check-in day {last.recovery_day} ({last.risk_level}).")
        else:
            bullets.append("No completed check-ins yet.")
        bullets.append(f"Medication doses (72h): {taken}/{total} recorded as taken." if total else
                       "No medication doses recorded in the last 72h.")
        if next_appt:
            bullets.append(f"Next appointment: {next_appt.appointment_type.replace('_', ' ').title()} with "
                           f"{next_appt.provider_name} on {next_appt.scheduled_at:%b %d %H:%M} "
                           f"(transport: {next_appt.transportation_status}).")
        bullets.append(f"Last successful contact: {last_contact.created_at:%b %d %H:%M}." if last_contact else
                       "No successful contact recorded.")
        return {"generated_by": "care-team-summary-agent (deterministic)", "bullets": bullets,
                "risk": patient.current_risk, "recovery_day": ctx.recovery_day, "phase": ctx.phase}
