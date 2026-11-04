"""Patient journey + care-team workflow through the HTTP API (acceptance criteria 1–12, 18–19)."""
from datetime import datetime, timedelta, timezone

from tests.conftest import NORMAL, login


def test_patient_sees_30_day_plan_and_dashboard(client, tokens):
    pid = client.get("/api/auth/me", headers=tokens["patient"]).json()["patient_id"]
    plan = client.get(f"/api/patients/{pid}/recovery-plan", headers=tokens["patient"]).json()
    assert plan["approved"] and plan["approved_by"] and plan["version"] == 1
    assert [p["key"] for p in plan["phases"]] == ["STABILIZE", "MONITOR", "PROGRESS", "TRANSITION"]
    for key in ("walking_goals", "wound_care", "hydration", "pt_exercises", "warning_signs", "appointment_schedule"):
        assert key in plan["content"]
    dash = client.get(f"/api/patients/{pid}/dashboard", headers=tokens["patient"]).json()
    assert dash["phase"]["key"] == "MONITOR" and dash["recovery_day"] == 5
    assert dash["tasks"] and dash["medications"] and dash["next_appointment"]


def test_unapproved_plan_not_presented(client, tokens, db):
    from sqlalchemy import select

    from app.models import Patient

    steven = db.scalars(select(Patient).where(Patient.first_name == "Steven")).one()
    r = client.get(f"/api/patients/{steven.id}/recovery-plan", headers=tokens["nurse"]).json()
    assert r["approved"] is False
    pending = client.get("/api/plans/pending", headers=tokens["doctor"]).json()
    v = next(x for x in pending if x["patient_id"] == str(steven.id))
    assert client.post(f"/api/plans/versions/{v['version_id']}/approve", headers=tokens["doctor"]).status_code == 200
    r = client.get(f"/api/patients/{steven.id}/recovery-plan", headers=tokens["nurse"]).json()
    assert r["approved"] and r["approved_by"] == "Dr. Samuel Okafor"


def test_checkin_green_amber_red_and_nurse_workflow(client, tokens, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    pid = fresh_patient["id"]
    qs = client.get(f"/api/patients/{pid}/checkin-questions", headers=hdr).json()
    assert {"pain_score", "temperature", "wound_appearance", "medication_adherence"} <= {q["key"] for q in qs}

    r = client.post(f"/api/patients/{pid}/checkins", headers=hdr, json={"answers": NORMAL}).json()
    assert r["risk_level"] == "GREEN" and r["alerts_created"] == []

    r = client.post(f"/api/patients/{pid}/checkins", headers=hdr,
                    json={"answers": NORMAL | {"pain_score": 5, "pain_trend": "WORSE"}}).json()
    assert r["risk_level"] == "AMBER"

    r = client.post(f"/api/patients/{pid}/checkins", headers=hdr, json={"answers": NORMAL | {
        "pain_score": 7, "pain_trend": "WORSE", "temperature": 101.8, "wound_appearance": "MORE_RED"}}).json()
    assert r["risk_level"] == "RED" and len(r["alerts_created"]) == 1
    rule_ids = {x["rule_id"] for x in r["rules_triggered"]}
    assert {"RED-FEVER", "RED-INFECTION-COMBO", "RED-PAIN-WORSENING"} <= rule_ids
    alert_id = r["alerts_created"][0]

    # Red alert reaches the worklist, sorted first
    wl = client.get("/api/care-team/worklist", headers=tokens["nurse"]).json()
    item = next(i for i in wl["items"] if i["id"] == alert_id)
    assert item["severity"] == "RED" and item["required_response_minutes"] == 15 and item["sla"]["state"] == "ON_TRACK"
    assert wl["items"][0]["severity"] == "RED"
    for key in ("patient_id", "severity", "trigger", "rule_id", "evidence", "created_at", "required_response_minutes",
                "assigned_team", "status"):
        assert item[key] not in (None, ""), key

    # Patient sees escalation status, not internal detail
    dash = client.get(f"/api/patients/{pid}/dashboard", headers=hdr).json()
    assert dash["escalation_status"]["severity"] == "RED" and dash["current_risk"] == "RED"

    n = tokens["nurse"]
    assert client.post(f"/api/alerts/{alert_id}/acknowledge", headers=n, json={"note": "on it"}).json()["status"] == \
        "ACKNOWLEDGED"
    a = client.post(f"/api/alerts/{alert_id}/contact", headers=n,
                    json={"method": "PHONE", "outcome": "REACHED", "note": "Spoke with patient"}).json()
    assert a["status"] == "CONTACT_IN_PROGRESS" and a["first_contact_at"]
    a = client.post(f"/api/alerts/{alert_id}/escalate", headers=n,
                    json={"to_role": "SURGEON", "reason": "Possible infection"}).json()
    assert a["status"] == "ESCALATED"
    escs = client.get("/api/escalations", headers=tokens["doctor"]).json()
    esc = next(e for e in escs if e["alert"]["id"] == alert_id)
    r = client.post(f"/api/escalations/{esc['id']}/respond", headers=tokens["doctor"],
                    json={"response_note": "See in wound clinic today", "complete": True})
    assert r.status_code == 200
    a = client.post(f"/api/alerts/{alert_id}/resolve", headers=n,
                    json={"resolution": "Seen in clinic; antibiotics started by surgeon", "outcome": "RESOLVED"}).json()
    assert a["status"] == "RESOLVED"
    assert client.post(f"/api/alerts/{alert_id}/close", headers=n, json={}).json()["status"] == "CLOSED"
    # Invalid transition after close
    assert client.post(f"/api/alerts/{alert_id}/acknowledge", headers=n, json={}).status_code == 409

    detail = client.get(f"/api/alerts/{alert_id}", headers=n).json()
    assert [x["action_type"] for x in detail["actions"]][:3] == ["ACKNOWLEDGE", "CONTACT_MADE", "ESCALATE"]

    tl = client.get(f"/api/patients/{pid}/timeline", headers=n).json()
    types = {e["type"] for e in tl}
    assert {"SURGERY", "ENROLLMENT", "RECOVERY_PLAN", "CHECKIN", "ALERT", "CARE_TEAM_ACTION", "ESCALATION",
            "RESOLUTION"} <= types
    assert all(e["timestamp"] for e in tl)
    # Patient's own timeline hides internal notes
    ptl = client.get(f"/api/patients/{pid}/timeline", headers=hdr).json()
    assert not any(e["type"] == "ESCALATION" for e in ptl)


def test_checkin_validation(client, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    r = client.post(f"/api/patients/{fresh_patient['id']}/checkins", headers=hdr,
                    json={"answers": NORMAL | {"pain_score": 14}})
    assert r.status_code == 422
    r = client.post(f"/api/patients/{fresh_patient['id']}/checkins", headers=hdr, json={"answers": {"pain_score": 2}})
    assert r.status_code == 422


def test_medications_and_adherence(client, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    pid = fresh_patient["id"]
    meds = client.get(f"/api/patients/{pid}/medications", headers=hdr).json()
    names = {m["name"] for m in meds["medications"]}
    assert {"Acetaminophen", "Oxycodone", "Apixaban"} <= names
    assert meds["today"] and "cannot change" in meds["notice"]
    apx = next(m for m in meds["medications"] if m["name"] == "Apixaban")
    sched = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    r = client.post(f"/api/patients/{pid}/medications/{apx['id']}/events", headers=hdr,
                    json={"status": "TAKEN", "scheduled_for": sched.isoformat()})
    assert r.status_code == 200 and r.json()["status"] == "TAKEN"
    for status in ("MISSED", "SKIPPED", "UNKNOWN"):
        r = client.post(f"/api/patients/{pid}/medications/{apx['id']}/events", headers=hdr,
                        json={"status": status, "scheduled_for": (sched - timedelta(days=1)).isoformat()})
        assert r.status_code == 200
    r = client.post(f"/api/patients/{pid}/medications/{apx['id']}/events", headers=hdr, json={"status": "DOUBLED"})
    assert r.status_code == 422
    # two MISSED within 48h → adherence alert
    acet = next(m for m in meds["medications"] if m["name"] == "Acetaminophen")
    for h in (6, 14):
        r = client.post(f"/api/patients/{pid}/medications/{acet['id']}/events", headers=hdr,
                        json={"status": "MISSED", "scheduled_for": (sched.replace(hour=h) - timedelta(days=1)).isoformat()})
    assert r.json()["alert_id"]


def test_appointments_and_transportation(client, tokens, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    pid = fresh_patient["id"]
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = client.post(f"/api/patients/{pid}/appointments", headers=tokens["nurse"], json={
        "appointment_type": "WOUND_CHECK", "provider_name": "Clinic Nurse", "location": "Clinic B",
        "scheduled_at": when})
    assert r.status_code == 200
    appts = client.get(f"/api/patients/{pid}/appointments", headers=hdr).json()
    assert len(appts) >= 2
    r = client.post(f"/api/patients/{pid}/appointments/{r.json()['id']}/transportation", headers=hdr,
                    json={"status": "NEEDS_HELP", "note": "No ride"}).json()
    assert r["transportation_status"] == "NEEDS_HELP" and r["alert_id"]
    wl = client.get("/api/care-team/worklist", headers=tokens["nurse"]).json()
    item = next(i for i in wl["items"] if i["id"] == r["alert_id"])
    assert item["category"] == "TRANSPORTATION" and item["assigned_team"] == "COORDINATOR"
    # patient can't create appointments
    assert client.post(f"/api/patients/{pid}/appointments", headers=hdr, json={
        "appointment_type": "X", "provider_name": "x", "location": "x", "scheduled_at": when}).status_code == 403


def test_caregiver_authorize_limited_view_and_revoke(client, tokens, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    pid = fresh_patient["id"]
    r = client.post(f"/api/patients/{pid}/caregivers", headers=hdr, json={
        "caregiver_email": "caregiver2@example.com", "relationship_to_patient": "Son",
        "scopes": ["RECOVERY_STATUS", "APPOINTMENTS"]})
    assert r.status_code == 200 and sorted(r.json()["scopes"]) == ["APPOINTMENTS", "RECOVERY_STATUS"]
    cg = login(client, "caregiver2@example.com")
    view = client.get(f"/api/caregiver/patients/{pid}", headers=cg).json()
    assert "recovery_status" in view and "appointments" in view
    for hidden in ("tasks", "reminders", "progress", "checkins", "notes", "medications", "alerts"):
        assert hidden not in view
    assert "Demo" in view["patient_first_name"] and "last_name" not in view
    client.delete(f"/api/patients/{pid}/caregivers/{r.json()['id']}", headers=hdr)
    assert client.get(f"/api/caregiver/patients/{pid}", headers=cg).status_code == 403
    # a non-caregiver account cannot be authorized
    r = client.post(f"/api/patients/{pid}/caregivers", headers=hdr, json={
        "caregiver_email": "nurse@example.com", "relationship_to_patient": "x", "scopes": ["PROGRESS"]})
    assert r.status_code == 404


def test_ai_chat_endpoint_contract(client, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    r = client.post(f"/api/patients/{fresh_patient['id']}/questions", headers=hdr,
                    json={"message": "When can I drive?"}).json()
    for key in ("answer", "citations", "retrieval", "safety_level", "model", "prompt_version", "disclaimer"):
        assert key in r
    c = r["citations"][0]
    assert c["title"] and c["section"] == "Driving" and c["version"] == 1 and c["authority"] == "SURGEON_APPROVED"
    assert r["retrieval"]["top_score"] > 0
    hist = client.get("/api/ai/conversation", headers=hdr).json()
    assert [m["sender_type"] for m in hist[-2:]] == ["PATIENT", "ASSISTANT"]


def test_care_team_message_reaches_patient(client, tokens, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    pid = fresh_patient["id"]
    client.post(f"/api/patients/{pid}/messages", headers=tokens["nurse"], json={"content": "How is your knee today?"})
    dash = client.get(f"/api/patients/{pid}/dashboard", headers=hdr).json()
    assert dash["unread_messages"] == 1
    msgs = client.get(f"/api/patients/{pid}/messages", headers=hdr).json()
    assert msgs[-1]["content"] == "How is your knee today?"
    notes = client.get("/api/notifications/me", headers=hdr).json()
    assert any(n["category"] == "MESSAGE" for n in notes["items"])


def test_task_completion(client, fresh_patient):
    hdr = login(client, fresh_patient["email"])
    pid = fresh_patient["id"]
    task = client.get(f"/api/patients/{pid}/dashboard", headers=hdr).json()["tasks"][0]
    assert client.post(f"/api/patients/{pid}/tasks/{task['id']}/complete", headers=hdr).json()["completed"] is True
    assert client.post(f"/api/patients/{pid}/tasks/{task['id']}/complete", headers=hdr).json()["completed"] is False
