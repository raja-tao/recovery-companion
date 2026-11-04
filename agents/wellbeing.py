"""Wellbeing Companion — asks how the patient feels at each sign-in and answers personally.

Deterministic templates only: the reply uses the patient's name, recovery day and plan phase,
acknowledges the feelings they picked and points to the right part of the app. It never gives
medical advice. Safety rules:
  * A note with emergency or self-harm language → RED nurse alert and 911 / 988 guidance.
  * Low or bad mood on 3 separate days within 5 days → AMBER nurse wellbeing check-in.
  * "Please contact me" → INFO nurse task.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.alerting import AlertEscalationAgent
from app.models import Appointment, Checkin, MoodEntry, Patient, User
from app.services.patients import active_episode, phase_for_day, recovery_day
from rules.safety import classify

MOODS = {  # key → (score, label, emoji)
    "GREAT": (5, "Great", "😄"), "GOOD": (4, "Good", "🙂"), "OKAY": (3, "Okay", "😐"),
    "LOW": (2, "Low", "😟"), "BAD": (1, "Bad", "😣"),
}
FEELINGS = {
    "HOPEFUL": "Hopeful", "CALM": "Calm", "TIRED": "Tired", "IN_PAIN": "In pain", "ANXIOUS": "Worried",
    "FRUSTRATED": "Frustrated", "LONELY": "Lonely", "POOR_SLEEP": "Slept badly", "SAD": "Sad",
}
LOW_SCORE = 2
LOW_TREND_DAYS = 3
LOW_TREND_WINDOW = timedelta(days=5)

_FEELING_REPLY = {
    "IN_PAIN": "If your pain is worse than usual, please note it in today's check-in so your care team sees it.",
    "ANXIOUS": "Lots of people feel worried after surgery. You can message your care team any time.",
    "LONELY": "Recovery can feel isolating. You can give a family member or friend access under Caregiver access.",
    "TIRED": "Feeling tired is very common in the first weeks — rest is part of your plan.",
    "POOR_SLEEP": "Poor sleep is common after surgery. If it keeps happening, mention it in your check-in.",
    "FRUSTRATED": "Progress can feel slow. Every day of your plan you complete counts.",
    "SAD": "Thank you for telling me. It's okay to have hard days.",
}
_PHASE_CHEER = {
    "STABILIZE": "These first days are about rest and protecting your wound.",
    "MONITOR": "You're building up a little more each day.",
    "PROGRESS": "You're in the progress phase — your exercises are really paying off now.",
    "TRANSITION": "You're nearly through the program. Great work getting here.",
}
CRISIS_MESSAGE = (
    "I'm really sorry you're feeling this way, and I'm glad you told me. If you might hurt yourself or are in "
    "danger, call or text 988 (Suicide & Crisis Lifeline) or call 911 now. Your nurse has been alerted and will "
    "contact you."
)


@dataclass
class MoodReply:
    message: str
    level: str = "GREEN"  # GREEN | AMBER | RED
    actions: list[str] = field(default_factory=list)
    nudges: list[dict] = field(default_factory=list)  # [{label, to}]
    alert_id: str | None = None


def _greeting(now: datetime) -> str:
    h = now.hour
    return "Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 18 else "Good evening"


class WellbeingAgent:
    def record(self, db: Session, actor: User, patient: Patient, mood: str, feelings: list[str],
               note: str | None, contact_me: bool, now: datetime | None = None) -> tuple[MoodEntry, MoodReply]:
        now = now or datetime.now(timezone.utc)
        score = MOODS[mood][0]
        entry = MoodEntry(patient_id=patient.id, user_id=actor.id, recorded_at=now, mood=mood, score=score,
                          feelings=[f for f in feelings if f in FEELINGS], note=note or None)
        db.add(entry)
        db.flush()
        reply = self._reply(db, patient, entry, now)
        alerting = AlertEscalationAgent()
        ep = active_episode(db, patient.id)
        ep_id = ep.id if ep else None

        if note and classify(note).is_emergency:
            alert = alerting.from_policy(db, patient, "MOOD-SAFETY", "Wellbeing note describes an emergency or "
                                         "self-harm risk", [{"fact": "mood_note", "actual": note, "mood": mood}],
                                         source="WELLBEING", actor=actor, episode_id=ep_id, dedupe_open=False)
            entry.alert_id = alert.id
            return entry, MoodReply(CRISIS_MESSAGE, "RED", ["Nurse alerted (15 min)"], alert_id=str(alert.id))

        if score <= LOW_SCORE:
            low_days = self._low_days(db, patient, now)
            if low_days >= LOW_TREND_DAYS:
                alert = alerting.from_policy(db, patient, "MOOD-LOW-TREND",
                                             f"Low mood on {low_days} days in the last 5 days",
                                             [{"fact": "low_mood_days_5d", "op": ">=", "threshold": LOW_TREND_DAYS,
                                               "actual": low_days, "feelings": entry.feelings}],
                                             source="WELLBEING", actor=actor, episode_id=ep_id)
                entry.alert_id = alert.id
                reply.level, reply.alert_id = "AMBER", str(alert.id)
                reply.actions.append("Your nurse will check in with you")
                reply.message += " You've had a few hard days, so I've asked your nurse to check in with you."
        if contact_me and not entry.alert_id:
            alert = alerting.from_policy(db, patient, "MOOD-CONTACT-REQUEST", "Patient asked to be contacted "
                                         f"(mood: {MOODS[mood][1].lower()})",
                                         [{"fact": "contact_requested", "actual": True, "mood": mood,
                                           "feelings": entry.feelings}],
                                         source="WELLBEING", actor=actor, episode_id=ep_id)
            entry.alert_id = alert.id
            reply.alert_id = str(alert.id)
            reply.actions.append("Your care team will contact you")
            reply.message += " I've let your care team know you'd like them to contact you."
        return entry, reply

    def _low_days(self, db: Session, patient: Patient, now: datetime) -> int:
        rows = db.scalars(select(MoodEntry).where(MoodEntry.patient_id == patient.id,
                                                  MoodEntry.recorded_at >= now - LOW_TREND_WINDOW)).all()
        # A day counts as low when the latest entry that day is low.
        latest: dict = {}
        for r in sorted(rows, key=lambda r: r.recorded_at):
            latest[r.recorded_at.date()] = r.score
        return sum(1 for s in latest.values() if s <= LOW_SCORE)

    def _reply(self, db: Session, patient: Patient, entry: MoodEntry, now: datetime) -> MoodReply:
        ep = active_episode(db, patient.id)
        day = recovery_day(ep) if ep else None
        phase = phase_for_day(day)["key"] if day is not None else None
        name = patient.first_name
        if entry.score >= 4:
            msg = f"That's lovely to hear, {name}!"
            if day:
                msg += f" Day {day} and feeling {MOODS[entry.mood][1].lower()} — {_PHASE_CHEER.get(phase, 'keep going.')}"
        elif entry.score == 3:
            msg = f"Thanks for telling me, {name}. Some days are just okay, and that's normal"
            msg += f" on day {day} of recovery." if day else "."
        else:
            msg = (f"I'm sorry you're feeling {MOODS[entry.mood][1].lower()} today, {name}. Recovery has hard days, "
                   "and it's okay to say so.")
        extra = [_FEELING_REPLY[f] for f in entry.feelings if f in _FEELING_REPLY][:2]
        if extra:
            msg += " " + " ".join(extra)
        reply = MoodReply(f"{_greeting(now)}. {msg}")

        # Gentle next steps.
        if ep and not db.scalars(select(Checkin.id).where(Checkin.patient_id == patient.id,
                                                          Checkin.checkin_date == now.date(),
                                                          Checkin.status == "COMPLETED")).first():
            reply.nudges.append({"label": "Do today's 2-minute check-in", "to": "/patient/checkin"})
        appt = db.scalars(select(Appointment).where(
            Appointment.patient_id == patient.id, Appointment.status == "SCHEDULED",
            Appointment.scheduled_at >= now, Appointment.scheduled_at <= now + timedelta(hours=48))
            .order_by(Appointment.scheduled_at)).first()
        if appt and appt.transportation_status == "UNKNOWN":
            reply.nudges.append({"label": f"Tell us how you'll get to your {appt.appointment_type.replace('_', ' ').lower()}",
                                 "to": "/patient/appointments"})
        if "ANXIOUS" in entry.feelings or entry.score <= LOW_SCORE:
            reply.nudges.append({"label": "Message your care team", "to": "/patient/messages"})
        return reply
