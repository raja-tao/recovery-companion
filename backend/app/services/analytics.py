"""Program analytics vs. configurable BRD targets (illustrative, not clinical guarantees)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Alert, Appointment, Checkin, Escalation, MedicationEvent, Message, Patient, SurgicalEpisode


def _rate(num: int, den: int):
    return round(num / den, 3) if den else None


def program_metrics(db: Session) -> dict:
    s = get_settings()
    today = date.today()
    now = datetime.now(timezone.utc)

    # Check-in completion: completed / expected, one expected per day from discharge to yesterday (max day 30).
    expected = 0
    for ep in db.scalars(select(SurgicalEpisode).where(SurgicalEpisode.status == "ACTIVE")):
        end = min(today - timedelta(days=1), ep.surgery_date + timedelta(days=30))
        expected += max(0, (end - ep.discharge_date).days + 1)
    completed = db.scalar(select(func.count(func.distinct(func.concat(Checkin.patient_id, Checkin.checkin_date))))
                          .where(Checkin.status == "COMPLETED", Checkin.checkin_date < today)) or 0
    missed = db.scalar(select(func.count()).select_from(Checkin).where(Checkin.status == "MISSED")) or 0

    med = dict(db.execute(select(MedicationEvent.status, func.count()).group_by(MedicationEvent.status)).all())
    med_den = med.get("TAKEN", 0) + med.get("MISSED", 0) + med.get("SKIPPED", 0)

    appt = dict(db.execute(select(Appointment.status, func.count()).where(Appointment.scheduled_at < now)
                           .group_by(Appointment.status)).all())
    appt_den = appt.get("COMPLETED", 0) + appt.get("MISSED", 0)

    red = db.scalars(select(Alert).where(Alert.severity == "RED")).all()
    contact_minutes = [(a.first_contact_at - a.created_at).total_seconds() / 60 for a in red if a.first_contact_at]
    ack_minutes = [(a.acknowledged_at - a.created_at).total_seconds() / 60 for a in red if a.acknowledged_at]
    within = sum(1 for m in contact_minutes if m <= s.target_red_alert_contact_minutes)

    alert_counts = dict(db.execute(select(Alert.severity, func.count()).group_by(Alert.severity)).all())
    open_counts = dict(db.execute(select(Alert.severity, func.count()).where(
        Alert.status.in_(["NEW", "ACKNOWLEDGED", "CONTACT_IN_PROGRESS", "ESCALATED"])).group_by(Alert.severity)).all())
    by_category = dict(db.execute(select(Alert.category, func.count()).group_by(Alert.category)).all())

    esc = db.scalars(select(Escalation).where(Escalation.responded_at.is_not(None))).all()
    esc_minutes = [(e.responded_at - e.created_at).total_seconds() / 60 for e in esc]

    ai_msgs = db.scalars(select(Message).where(Message.sender_type == "ASSISTANT")).all()
    ai_total = len(ai_msgs)
    ai_answered = sum(1 for m in ai_msgs if m.answered_from_content)
    ai_by_level = {}
    for m in ai_msgs:
        ai_by_level[m.safety_level or "UNKNOWN"] = ai_by_level.get(m.safety_level or "UNKNOWN", 0) + 1
    latencies = [m.latency_ms for m in ai_msgs if m.latency_ms is not None]
    models = {}
    for m in ai_msgs:
        models[m.model or "rules-engine"] = models.get(m.model or "rules-engine", 0) + 1

    risk = dict(db.execute(select(Patient.current_risk, func.count()).group_by(Patient.current_risk)).all())

    def kpi(name, value, target, higher_is_better=True, unit="ratio", detail=""):
        met = None
        if value is not None:
            met = value >= target if higher_is_better else value <= target
        return {"name": name, "value": value, "target": target, "met": met, "unit": unit, "detail": detail,
                "higher_is_better": higher_is_better}

    return {
        "generated_at": now.isoformat(),
        "disclaimer": "Targets are configurable illustrative program goals from the BRD, not clinical guarantees. "
                      "All data is synthetic.",
        "kpis": [
            kpi("Check-in completion", _rate(completed, expected), s.target_checkin_completion,
                detail=f"{completed} of {expected} expected check-ins"),
            kpi("Medication adherence", _rate(med.get("TAKEN", 0), med_den), s.target_medication_adherence,
                detail=f"{med.get('TAKEN', 0)} of {med_den} recorded doses taken"),
            kpi("Follow-up attendance", _rate(appt.get("COMPLETED", 0), appt_den), s.target_followup_attendance,
                detail=f"{appt.get('COMPLETED', 0)} of {appt_den} past appointments attended"),
            kpi("RED alert → nurse contact (median)", round(median(contact_minutes), 1) if contact_minutes else None,
                s.target_red_alert_contact_minutes, higher_is_better=False, unit="minutes",
                detail=f"{within} of {len(contact_minutes)} contacted within target"),
        ],
        "patients": {"total": sum(risk.values()), "by_risk": risk},
        "checkins": {"completed": completed, "expected": expected, "missed_recorded": missed},
        "medications": med,
        "appointments": appt,
        "alerts": {"total_by_severity": alert_counts, "open_by_severity": open_counts, "by_category": by_category,
                   "red_median_ack_minutes": round(median(ack_minutes), 1) if ack_minutes else None},
        "escalations": {"responded": len(esc_minutes),
                        "median_response_minutes": round(median(esc_minutes), 1) if esc_minutes else None},
        "ai": {"responses": ai_total, "answered_from_content": ai_answered,
               "refused_or_routed": ai_total - ai_answered, "by_safety_level": ai_by_level,
               "median_latency_ms": median(latencies) if latencies else None, "by_model": models,
               "tokens": {"input": sum(m.input_tokens or 0 for m in ai_msgs),
                          "output": sum(m.output_tokens or 0 for m in ai_msgs)}},
        "window": {"from": (today - timedelta(days=30)).isoformat(), "to": today.isoformat()},
    }
