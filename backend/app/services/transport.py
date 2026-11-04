"""Rides to follow-up appointments.

Day before an appointment the patient is asked how they'll get there (in-app + SMS). They can
confirm their own ride, ask for a hospital pickup (shuttle / non-emergency medical transport) or
ask for help finding one. A pickup request becomes a coordinator task; when the coordinator books
it the patient is told the pickup time, vehicle and confirmation code, and reminded the day before.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.alerting import AlertEscalationAgent
from app.models import Alert, Appointment, Patient, TransportRequest, User
from app.services import alerts as alert_svc
from app.services import audit
from app.services.notifications import notify

OPEN = ("REQUESTED", "SCHEDULED")
MODES = {"HOSPITAL_SHUTTLE": "Hospital shuttle", "NEMT": "Medical transport van",
         "RIDESHARE": "Rideshare (booked by the hospital)", "VOLUNTEER": "Volunteer driver"}
MOBILITY = {"WALKER": "Uses a walker", "WHEELCHAIR": "Needs a wheelchair-accessible vehicle", "CANE": "Uses a cane",
            "STEP_HELP": "Needs help with steps"}
# Ask about the ride from 36 h before; if still unanswered 12 h before, a coordinator follows up.
ASK_BEFORE = timedelta(hours=36)
UNANSWERED_TASK_BEFORE = timedelta(hours=12)


def _label(appt: Appointment) -> str:
    return appt.appointment_type.replace("_", " ").lower()


def open_request(db: Session, appointment_id) -> TransportRequest | None:
    return db.scalars(select(TransportRequest).where(TransportRequest.appointment_id == appointment_id,
                                                     TransportRequest.status.in_(OPEN))
                      .order_by(TransportRequest.created_at.desc())).first()


def request_out(r: TransportRequest | None, *, staff: bool = False) -> dict | None:
    if not r:
        return None
    out = {"id": str(r.id), "status": r.status, "kind": r.kind, "return_trip": r.return_trip,
           "mobility_needs": r.mobility_needs, "companion": r.companion, "pickup_address": r.pickup_address,
           "requested_pickup_at": r.requested_pickup_at.isoformat() if r.requested_pickup_at else None,
           "patient_note": r.patient_note, "mode": r.mode, "mode_label": MODES.get(r.mode or ""), "vendor": r.vendor,
           "pickup_at": r.pickup_at.isoformat() if r.pickup_at else None, "vehicle": r.vehicle,
           "driver_name": r.driver_name, "contact_phone": r.contact_phone, "confirmation_code": r.confirmation_code,
           "cancelled_reason": r.cancelled_reason, "created_at": r.created_at.isoformat()}
    if staff:
        out["alert_id"] = str(r.alert_id) if r.alert_id else None
        out["arranged_at"] = r.arranged_at.isoformat() if r.arranged_at else None
    return out


def create_request(db: Session, actor: User, patient: Patient, appt: Appointment, *, kind: str,
                   pickup_address: str | None, requested_pickup_at: datetime | None, return_trip: bool,
                   mobility_needs: list[str], companion: bool, note: str | None) -> TransportRequest:
    if appt.status != "SCHEDULED" or appt.scheduled_at < datetime.now(timezone.utc):
        raise HTTPException(409, "Rides can only be requested for upcoming appointments")
    if kind == "HOSPITAL_PICKUP" and not pickup_address:
        raise HTTPException(422, "A pickup address is required for a hospital pickup")
    if open_request(db, appt.id):
        raise HTTPException(409, "A ride is already requested for this appointment")
    r = TransportRequest(appointment_id=appt.id, patient_id=patient.id, kind=kind, pickup_address=pickup_address,
                         requested_pickup_at=requested_pickup_at, return_trip=return_trip,
                         mobility_needs=[m for m in mobility_needs if m in MOBILITY], companion=companion,
                         patient_note=note)
    db.add(r)
    db.flush()
    appt.transportation_status, appt.transportation_note = "NEEDS_HELP", note
    what = "Hospital pickup requested" if kind == "HOSPITAL_PICKUP" else "Help finding a ride"
    needs = ", ".join(MOBILITY[m] for m in r.mobility_needs)
    alert = AlertEscalationAgent().from_policy(
        db, patient, "APPT-TRANSPORT", f"{what} for {_label(appt)} on {appt.scheduled_at:%b %d %H:%M}",
        [{"fact": "transportation_status", "actual": "NEEDS_HELP", "appointment_id": str(appt.id),
          "transport_request_id": str(r.id), "kind": kind, "mobility_needs": r.mobility_needs, "note": note}],
        source="APPOINTMENT", actor=actor, episode_id=appt.episode_id, dedupe_open=False)
    r.alert_id = alert.id
    audit.record(db, "TRANSPORT_REQUESTED", actor=actor, patient_id=patient.id, resource_type="transport_request",
                 resource_id=r.id, details={"appointment_id": str(appt.id), "kind": kind, "needs": needs,
                                            "return_trip": return_trip, "alert": str(alert.id)})
    return r


def schedule(db: Session, actor: User, r: TransportRequest, *, mode: str, vendor: str | None, pickup_at: datetime,
             vehicle: str | None, driver_name: str | None, contact_phone: str | None,
             confirmation_code: str | None) -> TransportRequest:
    if r.status not in OPEN:
        raise HTTPException(409, f"Request is {r.status}")
    appt = db.get(Appointment, r.appointment_id)
    if pickup_at >= appt.scheduled_at:
        raise HTTPException(422, "Pickup must be before the appointment time")
    r.status, r.mode, r.vendor, r.pickup_at = "SCHEDULED", mode, vendor, pickup_at
    r.vehicle, r.driver_name, r.contact_phone, r.confirmation_code = vehicle, driver_name, contact_phone, confirmation_code
    r.arranged_by_id, r.arranged_at = actor.id, datetime.now(timezone.utc)
    appt.transportation_status = "ARRANGED"
    patient = db.get(Patient, r.patient_id)
    _resolve_task(db, r, actor, f"Ride booked: {MODES[mode]}, pickup {pickup_at:%b %d %H:%M}")
    if patient.user_id:
        notify(db, category="TRANSPORT", user=db.get(User, patient.user_id), patient=patient,
               title="Your ride is booked",
               body=f"{MODES[mode]} will pick you up on {pickup_at:%b %d at %H:%M} for your {_label(appt)}."
                    + (f" Confirmation {confirmation_code}." if confirmation_code else "")
                    + " Details are in the app under Appointments.",
               channels=("IN_APP", "SMS"), dedupe_key=f"ride-booked:{r.id}:{pickup_at.isoformat()}")
    audit.record(db, "TRANSPORT_SCHEDULED", actor=actor, patient_id=r.patient_id, resource_type="transport_request",
                 resource_id=r.id, details={"mode": mode, "vendor": vendor, "pickup_at": pickup_at.isoformat()})
    return r


def cancel(db: Session, actor: User, r: TransportRequest, reason: str | None) -> TransportRequest:
    if r.status not in OPEN:
        raise HTTPException(409, f"Request is {r.status}")
    r.status, r.cancelled_reason = "CANCELLED", reason
    appt = db.get(Appointment, r.appointment_id)
    by_patient = actor.role_name == "PATIENT"
    # The patient cancelling means they have their own ride; staff cancelling reopens the question.
    appt.transportation_status = "CONFIRMED" if by_patient else "UNKNOWN"
    _resolve_task(db, r, actor, f"Ride request cancelled{' by patient' if by_patient else ''}: {reason or 'no reason'}")
    patient = db.get(Patient, r.patient_id)
    if not by_patient and patient.user_id:
        notify(db, category="TRANSPORT", user=db.get(User, patient.user_id), patient=patient,
               title="Ride cancelled", body=f"Your ride for your {_label(appt)} was cancelled. Please open the app "
                                            "to tell us how you'll get there.",
               channels=("IN_APP", "SMS"), dedupe_key=f"ride-cancelled:{r.id}")
    audit.record(db, "TRANSPORT_CANCELLED", actor=actor, patient_id=r.patient_id, resource_type="transport_request",
                 resource_id=r.id, details={"reason": reason, "by_patient": by_patient})
    return r


def complete(db: Session, actor: User, r: TransportRequest) -> TransportRequest:
    if r.status != "SCHEDULED":
        raise HTTPException(409, "Only a scheduled ride can be completed")
    r.status = "COMPLETED"
    audit.record(db, "TRANSPORT_COMPLETED", actor=actor, patient_id=r.patient_id, resource_type="transport_request",
                 resource_id=r.id)
    return r


def _resolve_task(db: Session, r: TransportRequest, actor: User, text: str) -> None:
    alert = db.get(Alert, r.alert_id) if r.alert_id else None
    if alert and alert.status in alert_svc.OPEN_STATUSES:
        alert_svc.resolve(db, alert, actor, text, outcome="TRANSPORT")


def day_before_checks(db: Session, now: datetime | None = None) -> dict:
    """Ask about rides the day before, remind booked pickups, flag unanswered questions to a coordinator."""
    now = now or datetime.now(timezone.utc)
    asked = reminded = tasks = 0
    appts = db.scalars(select(Appointment).where(Appointment.status == "SCHEDULED", Appointment.scheduled_at > now,
                                                 Appointment.scheduled_at <= now + ASK_BEFORE)).all()
    for a in appts:
        p = db.get(Patient, a.patient_id)
        if p.enrollment_status != "ACTIVE":
            continue
        user = db.get(User, p.user_id) if p.user_id else None
        when = f"{a.scheduled_at:%a %b %d at %H:%M}"
        if a.transportation_status == "UNKNOWN":
            if user:
                asked += bool(notify(db, category="TRANSPORT", user=user, patient=p,
                                     title="How are you getting to your appointment?",
                                     body=f"Your {_label(a)} is {when}. Open the app to confirm your ride or ask the "
                                          "hospital to pick you up.",
                                     channels=("IN_APP", "SMS"), dedupe_key=f"transport-check:{a.id}"))
            already = db.scalars(select(Alert.id).where(
                Alert.patient_id == p.id, Alert.rule_id == "APPT-TRANSPORT-UNCONFIRMED",
                Alert.created_at >= a.scheduled_at - ASK_BEFORE)).first()
            if a.scheduled_at - now <= UNANSWERED_TASK_BEFORE and not already:
                AlertEscalationAgent().from_policy(
                    db, p, "APPT-TRANSPORT-UNCONFIRMED", f"No ride confirmed for {_label(a)} {when}",
                    [{"fact": "transportation_status", "actual": "UNKNOWN", "appointment_id": str(a.id)}],
                    source="SCHEDULER", episode_id=a.episode_id)
                tasks += 1
        r = open_request(db, a.id)
        if r and r.status == "SCHEDULED" and r.pickup_at and user:
            reminded += bool(notify(db, category="TRANSPORT", user=user, patient=p, title="Ride reminder",
                                    body=f"Pickup {r.pickup_at:%a %b %d at %H:%M} ({MODES.get(r.mode or '', 'ride')})"
                                         + (f", confirmation {r.confirmation_code}" if r.confirmation_code else "")
                                         + ". Please be ready 10 minutes early.",
                                    channels=("IN_APP", "SMS"), dedupe_key=f"ride-reminder:{r.id}:{r.pickup_at.isoformat()}"))
    return {"transport_asked": asked, "ride_reminders": reminded, "transport_tasks": tasks}
