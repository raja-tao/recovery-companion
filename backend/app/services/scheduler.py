"""Background jobs: missed check-in detection, reminders, SLA monitoring.

POC: an asyncio loop in the API process (single replica). In AWS: EventBridge
Scheduler → ECS task (or a dedicated worker service) running `run_all_jobs`.
All jobs are idempotent (dedupe keys / unique checks), so overlapping runs are safe.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.observability import log_event
from app.models import Alert, Appointment, Checkin, Medication, Patient, SurgicalEpisode, User, WarningProtocol
from app.services.alerts import OPEN_STATUSES, create_alert
from app.services.notifications import notify
from app.services.patients import phase_for_day

logger = logging.getLogger("scheduler")


def detect_missed_checkins(db: Session, today: date | None = None) -> int:
    """Record MISSED for each enrolled day without a check-in; raise AMBER per approved protocol."""
    today = today or date.today()
    created = 0
    protocol = db.scalars(select(WarningProtocol).where(WarningProtocol.rule_id == "AMBER-MISSED-CHECKINS",
                                                        WarningProtocol.status == "APPROVED")
                          .order_by(WarningProtocol.version.desc())).first()
    threshold = 2
    if protocol:
        try:
            threshold = int(protocol.condition["value"])
        except (KeyError, TypeError, ValueError):
            pass
    for ep in db.scalars(select(SurgicalEpisode).where(SurgicalEpisode.status == "ACTIVE")):
        patient = db.get(Patient, ep.patient_id)
        if patient.enrollment_status != "ACTIVE":
            continue
        start = max(ep.discharge_date, today - timedelta(days=7))
        end = min(today - timedelta(days=1), ep.surgery_date + timedelta(days=30))
        d = start
        while d <= end:
            exists = db.scalars(select(Checkin.id).where(Checkin.patient_id == patient.id,
                                                         Checkin.checkin_date == d)).first()
            if not exists:
                db.add(Checkin(patient_id=patient.id, episode_id=ep.id, checkin_date=d,
                               recovery_day=(d - ep.surgery_date).days, status="MISSED", risk_level="GREEN"))
                created += 1
            d += timedelta(days=1)
        db.flush()
        recent = db.scalars(select(Checkin).where(Checkin.patient_id == patient.id, Checkin.checkin_date < today)
                            .order_by(Checkin.checkin_date.desc()).limit(7)).all()
        streak = 0
        for c in recent:
            if c.status != "MISSED":
                break
            streak += 1
        if streak >= threshold and protocol:
            create_alert(db, patient=patient, severity=protocol.severity, category=protocol.category,
                         source="SCHEDULER", rule_id=protocol.rule_id,
                         trigger_summary=f"{streak} missed check-ins in a row", response_minutes=protocol.response_minutes,
                         evidence=[{"fact": "consecutive_missed_checkins", "op": ">=", "threshold": threshold,
                                    "actual": streak, "last_completed": next((c.checkin_date.isoformat() for c in recent
                                                                               if c.status == "COMPLETED"), None)}],
                         assigned_team=protocol.assigned_team, episode_id=ep.id, protocol_id=protocol.id)
            if patient.user_id:
                notify(db, category="MISSED_CHECKIN", user=db.get(User, patient.user_id), patient=patient,
                       title="We missed you", body="You haven't checked in for a couple of days. "
                                                   "Please complete today's 2-minute check-in.",
                       channels=("IN_APP", "SMS"), dedupe_key=f"missed:{patient.id}:{today}")
    return created


def send_reminders(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    sent = 0
    for p in db.scalars(select(Patient).where(Patient.enrollment_status == "ACTIVE", Patient.user_id.is_not(None))):
        user = db.get(User, p.user_id)
        # Daily check-in reminder
        done = db.scalars(select(Checkin.id).where(Checkin.patient_id == p.id, Checkin.checkin_date == today,
                                                   Checkin.status == "COMPLETED")).first()
        if not done:
            sent += len(notify(db, category="CHECKIN_REMINDER", user=user, patient=p, title="Daily check-in",
                               body="Your 2-minute recovery check-in is ready.",
                               dedupe_key=f"checkin-reminder:{p.id}:{today}"))
        # Medication reminders for doses in the next hour
        for m in db.scalars(select(Medication).where(Medication.patient_id == p.id, Medication.is_active.is_(True))):
            for t in m.schedule_times or []:
                hh, mm = map(int, t.split(":"))
                sched = datetime.combine(today, time(hh, mm), tzinfo=timezone.utc)
                if now <= sched <= now + timedelta(hours=1):
                    sent += len(notify(db, category="MEDICATION_REMINDER", user=user, patient=p,
                                       title=f"Medication reminder: {m.name}",
                                       body=f"{m.name} {m.dose_text} is scheduled at {t}. {m.instructions}"[:300],
                                       dedupe_key=f"med:{m.id}:{sched.isoformat()}"))
    # Appointment reminders 24h ahead
    for a in db.scalars(select(Appointment).where(Appointment.status == "SCHEDULED",
                                                  Appointment.reminder_sent_at.is_(None),
                                                  Appointment.scheduled_at <= now + timedelta(hours=24),
                                                  Appointment.scheduled_at >= now)):
        p = db.get(Patient, a.patient_id)
        if p.user_id:
            sent += len(notify(db, category="APPOINTMENT_REMINDER", user=db.get(User, p.user_id), patient=p,
                               title="Appointment tomorrow",
                               body=f"{a.appointment_type.replace('_', ' ').title()} with {a.provider_name} at "
                                    f"{a.scheduled_at:%H:%M}, {a.location}. Your ride details are under Appointments.",
                               channels=("IN_APP", "SMS"), dedupe_key=f"appt:{a.id}"))
            a.reminder_sent_at = now
    return sent


def monitor_sla(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    breached = 0
    for a in db.scalars(select(Alert).where(Alert.status == "NEW", Alert.sla_breached.is_(False), Alert.due_at < now)):
        a.sla_breached = True
        breached += 1
        # Escalate to all nurses + surgeons on breach of a RED alert.
        if a.severity == "RED":
            for u in db.scalars(select(User).where(User.is_active.is_(True))):
                if u.role_name in ("NURSE", "SURGEON"):
                    notify(db, category="CARE_TEAM_ESCALATION", user=u, title=f"SLA BREACH: {a.patient.full_name}",
                           body=f"RED alert unacknowledged past {a.required_response_minutes} min: {a.trigger_summary}",
                           channels=("IN_APP", "SMS"), dedupe_key=f"sla:{a.id}:{u.id}")
    return breached


def complete_programs(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    n = 0
    for ep in db.scalars(select(SurgicalEpisode).where(SurgicalEpisode.status == "ACTIVE")):
        if phase_for_day((today - ep.surgery_date).days)["key"] == "COMPLETED":
            ep.status = "COMPLETED"
            n += 1
    return n


def run_all_jobs(db: Session) -> dict:
    from app.services.outbound import deliver_due
    from app.services.transport import day_before_checks

    result = {"missed_checkins_recorded": detect_missed_checkins(db), "reminders_sent": send_reminders(db),
              "sla_breaches": monitor_sla(db), "programs_completed": complete_programs(db),
              **day_before_checks(db), "outbound_delivered": deliver_due(db)}
    db.commit()
    log_event(logger, "scheduler run", **result)
    return result


async def scheduler_loop(interval_seconds: int) -> None:
    await asyncio.sleep(5)
    while True:
        try:
            db = SessionLocal()
            try:
                await asyncio.to_thread(run_all_jobs, db)
            finally:
                db.close()
        except Exception:  # never let the loop die
            logger.exception("scheduler run failed")
        await asyncio.sleep(interval_seconds)
