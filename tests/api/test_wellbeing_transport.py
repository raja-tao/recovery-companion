"""Mood at sign-in, rides to appointments, outcome surveys and doctor-approved medication guidance."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.conftest import login


@pytest.fixture()
def me(client, fresh_patient):
    return {"id": fresh_patient["id"], "h": login(client, fresh_patient["email"])}


def _alerts(db, pid, rule):
    from app.models import Alert

    db.expire_all()
    return db.scalars(select(Alert).where(Alert.patient_id == uuid.UUID(pid), Alert.rule_id == rule)).all()


def _mood(client, me, mood, **kw):
    r = client.post(f"/api/patients/{me['id']}/mood", headers=me["h"], json={"mood": mood, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- wellbeing
def test_mood_reply_is_personal_and_suggests_next_steps(client, me):
    body = _mood(client, me, "OKAY", feelings=["TIRED", "ANXIOUS"])
    reply = body["reply"]
    assert "Day 5" in reply["message"] or "day 5" in reply["message"]
    assert "tired" in reply["message"].lower() and "worried" in reply["message"].lower()
    assert {"to": "/patient/checkin", "label": "Do today's 2-minute check-in"} in reply["nudges"]
    assert reply["level"] == "GREEN" and not reply["alert_id"]
    hist = client.get(f"/api/patients/{me['id']}/mood", headers=me["h"]).json()
    assert hist["entries"][0]["emoji"] == "😐"


def test_crisis_note_raises_red_alert_with_988(client, db, me):
    reply = _mood(client, me, "BAD", note="I feel hopeless and want to end my life")["reply"]
    assert reply["level"] == "RED" and "988" in reply["message"] and "911" in reply["message"]
    (a,) = _alerts(db, me["id"], "MOOD-SAFETY")
    assert a.severity == "RED" and a.required_response_minutes == 15


def test_low_mood_three_days_creates_nurse_check_in(client, db, me):
    from app.models import MoodEntry

    now = datetime.now(timezone.utc)
    for d in (2, 1):
        db.add(MoodEntry(patient_id=uuid.UUID(me["id"]), mood="LOW", score=2, recorded_at=now - timedelta(days=d)))
    db.commit()
    reply = _mood(client, me, "LOW")["reply"]
    assert reply["level"] == "AMBER" and "nurse" in reply["message"]
    (a,) = _alerts(db, me["id"], "MOOD-LOW-TREND")
    assert a.category == "MOOD" and a.assigned_team == "NURSE"


def test_contact_request_and_access_rules(client, db, me, tokens):
    _mood(client, me, "GOOD", contact_me=True)
    assert _alerts(db, me["id"], "MOOD-CONTACT-REQUEST")
    assert client.post(f"/api/patients/{me['id']}/mood", headers=me["h"],
                       json={"mood": "GOOD", "feelings": ["NOPE"]}).status_code == 422
    assert client.get(f"/api/patients/{me['id']}/mood", headers=tokens["nurse"]).status_code == 200
    assert client.get(f"/api/patients/{me['id']}/mood", headers=tokens["admin"]).status_code == 403
    assert client.post(f"/api/patients/{me['id']}/mood", headers=tokens["nurse"], json={"mood": "GOOD"}).status_code == 403


# --------------------------------------------------------------------------- transport
def _future_appt(db, pid, hours=20):
    from app.models import Appointment

    a = Appointment(patient_id=uuid.UUID(pid), appointment_type="PT", provider_name="Jamie Rivera, PT",
                    location="Synthetic PT Clinic", scheduled_at=datetime.now(timezone.utc) + timedelta(hours=hours))
    db.add(a)
    db.commit()
    return a


def test_hospital_pickup_request_booking_and_reminder(client, db, me, tokens):
    from app.models import Notification
    from app.services.transport import day_before_checks

    appt = _future_appt(db, me["id"])
    base = f"/api/patients/{me['id']}/appointments/{appt.id}"
    assert client.post(f"{base}/transport-request", headers=me["h"],
                       json={"kind": "HOSPITAL_PICKUP"}).status_code == 422  # address required
    r = client.post(f"{base}/transport-request", headers=me["h"], json={
        "kind": "HOSPITAL_PICKUP", "pickup_address": "12 Synthetic Lane", "mobility_needs": ["WALKER"],
        "note": "Second floor, no elevator"}).json()
    assert r["transportation_status"] == "NEEDS_HELP" and r["transport"]["status"] == "REQUESTED"
    assert client.post(f"{base}/transport-request", headers=me["h"],
                       json={"kind": "HELP_FINDING_RIDE"}).status_code == 409  # one open request
    (task,) = _alerts(db, me["id"], "APPT-TRANSPORT")
    assert task.assigned_team == "COORDINATOR"

    # Doctors don't arrange rides; nurses / coordinators do.
    assert client.get("/api/transport-requests", headers=tokens["doctor"]).status_code == 403
    queue = client.get("/api/transport-requests", headers=tokens["nurse"]).json()
    req = next(q for q in queue if q["id"] == r["transport"]["id"])
    assert req["pickup_address"] == "12 Synthetic Lane" and req["mobility_needs"] == ["WALKER"]
    too_late = (appt.scheduled_at + timedelta(minutes=5)).isoformat()
    assert client.post(f"/api/transport-requests/{req['id']}/schedule", headers=tokens["nurse"],
                       json={"mode": "NEMT", "pickup_at": too_late}).status_code == 422
    pickup = (appt.scheduled_at - timedelta(hours=1)).isoformat()
    booked = client.post(f"/api/transport-requests/{req['id']}/schedule", headers=tokens["nurse"],
                         json={"mode": "NEMT", "vendor": "Synthetic Medical Rides", "pickup_at": pickup,
                               "vehicle": "White van, wheelchair lift", "confirmation_code": "RIDE42"}).json()
    assert booked["status"] == "SCHEDULED"
    db.expire_all()
    assert db.get(type(task), task.id).status == "RESOLVED"

    mine = client.get(f"/api/patients/{me['id']}/appointments", headers=me["h"]).json()
    a = next(x for x in mine if x["id"] == str(appt.id))
    assert a["transportation_status"] == "ARRANGED" and a["transport"]["confirmation_code"] == "RIDE42"

    day_before_checks(db)
    db.commit()
    titles = set(db.scalars(select(Notification.title).where(Notification.patient_id == uuid.UUID(me["id"]))))
    assert {"Your ride is booked", "Ride reminder"} <= titles
    sms = db.scalars(select(Notification).where(Notification.patient_id == uuid.UUID(me["id"]),
                                                Notification.channel == "SMS", Notification.title == "Ride reminder")).one()
    assert "RIDE42" not in sms.body  # SMS stays PHI-minimal


def test_day_before_question_and_unanswered_task(client, db, me):
    from app.models import Notification
    from app.services.transport import day_before_checks

    appt = _future_appt(db, me["id"], hours=10)
    day_before_checks(db)
    day_before_checks(db)  # idempotent
    db.commit()
    asked = db.scalars(select(Notification).where(Notification.patient_id == uuid.UUID(me["id"]),
                                                  Notification.dedupe_key.like(f"transport-check:{appt.id}%"))).all()
    assert {n.channel for n in asked} == {"IN_APP", "SMS"}
    assert len(_alerts(db, me["id"], "APPT-TRANSPORT-UNCONFIRMED")) == 1


def test_own_ride_cancels_open_request(client, db, me):
    appt = _future_appt(db, me["id"])
    base = f"/api/patients/{me['id']}/appointments/{appt.id}"
    client.post(f"{base}/transportation", headers=me["h"], json={"status": "NEEDS_HELP"})
    r = client.post(f"{base}/transportation", headers=me["h"], json={"status": "CONFIRMED"}).json()
    assert r["transportation_status"] == "CONFIRMED" and r["transport"] is None


# --------------------------------------------------------------------------- surveys
def test_koos_jr_survey_window_scoring_and_outbound(client, db, me):
    from app.models import OutboundMessage, SurgicalEpisode

    ep = db.scalars(select(SurgicalEpisode).where(SurgicalEpisode.patient_id == uuid.UUID(me["id"]))).one()
    url = f"/api/patients/{me['id']}/surveys/KOOS_JR/POSTOP_2W"
    items = client.get("/api/surveys/KOOS_JR", headers=me["h"]).json()["items"]
    answers = {i["id"]: 1 for i in items}
    assert client.post(url, headers=me["h"], json={"answers": answers}).status_code == 409  # day 5: not open
    ep.surgery_date = date.today() - timedelta(days=15)
    db.commit()
    assert [s["state"] for s in client.get(f"/api/patients/{me['id']}/surveys", headers=me["h"]).json()] == \
        ["DUE", "UPCOMING"]
    assert client.post(url, headers=me["h"], json={"answers": {**answers, items[0]["id"]: 7}}).status_code == 422
    r = client.post(url, headers=me["h"], json={"answers": answers}).json()
    assert r["raw_score"] == 7 and r["max_score"] == 28
    assert client.post(url, headers=me["h"], json={"answers": answers}).status_code == 409  # once per time point
    out = db.scalars(select(OutboundMessage).where(OutboundMessage.related_id == r["id"])).one()
    assert out.resource_type == "QuestionnaireResponse" and out.status == "PENDING"


# --------------------------------------------------------------------------- doctor-only treatment decisions
def test_only_the_doctor_approves_missed_dose_guidance(client, db, me, tokens):
    meds = client.get(f"/api/patients/{me['id']}/medications", headers=tokens["nurse"]).json()["medications"]
    mid = meds[0]["id"]
    url = f"/api/patients/{me['id']}/medications/{mid}/guidance"
    text = {"missed_dose_guidance": "Take it when you remember unless it is nearly time for the next dose."}
    assert client.post(url, headers=tokens["nurse"], json=text).status_code == 403
    assert client.post(url, headers=me["h"], json=text).status_code == 403
    r = client.post(url, headers=tokens["doctor"], json=text).json()
    assert r["missed_dose_guidance"] == text["missed_dose_guidance"] and r["guidance_approved_by"].startswith("Dr.")
