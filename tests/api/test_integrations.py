"""Inbound integrations end to end: auth, idempotency, record updates, protocol alerts, admin console."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from integrations import samples

KEY = "dev-integration-key"
DEVICE = {"X-Integration-Key": f"{KEY}-rpm-devices"}
FHIR = {"X-Integration-Key": f"{KEY}-ehr-fhir"}
HL7 = {"X-Integration-Key": f"{KEY}-ehr-hl7"}
RX = {"X-Integration-Key": f"{KEY}-pharmacy-network"}


@pytest.fixture()
def patient(fresh_patient, db):
    from app.models import Patient

    p = db.get(Patient, uuid.UUID(fresh_patient["id"]))
    return {"id": fresh_patient["id"], "mrn": p.mrn}


def _reading(mrn, value, unit="[degF]", kind="TEMPERATURE", when=None, message_id=None):
    when = when or datetime.now(timezone.utc)
    return json.dumps({"message_id": message_id or uuid.uuid4().hex, "patient": {"mrn": mrn},
                       "device": {"type": "THERMOMETER"},
                       "readings": [{"type": kind, "value": value, "unit": unit, "measured_at": when.isoformat()}]})


def _alerts(db, patient_id):
    from app.models import Alert

    db.expire_all()
    return db.scalars(select(Alert).where(Alert.patient_id == uuid.UUID(patient_id))).all()


def test_inbound_requires_a_valid_key_for_the_right_channel(client):
    assert client.post("/api/integrations/devices", content="{}").status_code == 401
    assert client.post("/api/integrations/devices", content="{}", headers={"X-Integration-Key": "nope"}).status_code == 401
    assert client.post("/api/integrations/fhir", content="{}", headers=DEVICE).status_code == 403
    # A user JWT is not an integration credential.
    assert client.post("/api/integrations/devices", content="{}",
                       headers={"Authorization": "Bearer x"}).status_code == 401


def test_device_fever_raises_red_alert_through_approved_protocol(client, db, patient):
    r = client.post("/api/integrations/devices", content=_reading(patient["mrn"], 38.6, "Cel"), headers=DEVICE)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "PROCESSED"
    assert body["result"]["readings"]["rules_triggered"] == ["RED-FEVER"]
    (alert,) = [a for a in _alerts(db, patient["id"]) if a.rule_id == "RED-FEVER"]
    assert alert.severity == "RED" and alert.source == "INTEGRATION" and alert.required_response_minutes == 15
    assert any(e.get("readings") for e in alert.evidence)
    assert "patient_id" not in body and "name" not in json.dumps(body["result"])  # receipts carry no PHI


def test_duplicate_delivery_is_idempotent(client, db, patient):
    raw = _reading(patient["mrn"], 98.6, message_id="dup-" + uuid.uuid4().hex)
    first = client.post("/api/integrations/devices", content=raw, headers=DEVICE).json()
    second = client.post("/api/integrations/devices", content=raw, headers=DEVICE).json()
    assert second["duplicate"] is True and second["message_id"] == first["message_id"]
    from app.models import DeviceReading

    assert db.query(DeviceReading).filter(DeviceReading.patient_id == uuid.UUID(patient["id"])).count() == 1


def test_stale_readings_are_stored_but_never_alert(client, db, patient):
    old = datetime.now(timezone.utc) - timedelta(days=3)
    body = client.post("/api/integrations/devices", content=_reading(patient["mrn"], 102, when=old),
                       headers=DEVICE).json()
    assert body["result"]["readings"]["stored"] == 1 and body["result"]["readings"]["not_evaluated"] == 1
    assert not [a for a in _alerts(db, patient["id"]) if a.rule_id == "RED-FEVER"]


def test_unknown_mrn_is_rejected_and_never_enrolls(client, db):
    r = client.post("/api/integrations/devices", content=_reading("NOT-ENROLLED-1", 99), headers=DEVICE)
    assert r.status_code == 422 and r.json()["status"] == "REJECTED"
    from app.models import Patient

    assert not db.scalars(select(Patient).where(Patient.mrn == "NOT-ENROLLED-1")).first()


def test_fhir_discharge_bundle_updates_record_and_creates_doctor_task(client, db, patient):
    from app.models import Appointment, Medication

    r = client.post("/api/integrations/fhir", content=samples.fhir_discharge(patient["mrn"]), headers=FHIR)
    body = r.json()
    assert body["status"] == "PROCESSED", body
    assert body["result"]["medications"] == {"created": 2, "updated": 0, "unchanged": 0}
    assert body["result"]["appointments"]["created"] == 1
    db.expire_all()
    pid = uuid.UUID(patient["id"])
    meds = {m.name: m for m in db.scalars(select(Medication).where(Medication.patient_id == pid))}
    assert meds["Cephalexin 500 mg capsule"].missed_dose_guidance is None  # the doctor must approve guidance
    assert db.scalars(select(Appointment).where(Appointment.patient_id == pid,
                                                Appointment.appointment_type == "PT")).first()
    (task,) = [a for a in _alerts(db, patient["id"]) if a.rule_id == "INT-MED-RECONCILE"]
    assert task.assigned_team == "SURGEON" and task.category == "MEDICATION_RECONCILIATION"
    # Re-sending the same medications (new message id) updates nothing and creates no second task.
    again = client.post("/api/integrations/fhir", content=samples.fhir_discharge(patient["mrn"]), headers=FHIR).json()
    assert again["result"]["medications"]["created"] == 0


def test_hl7_returns_ack_codes(client, patient):
    ok = client.post("/api/integrations/hl7v2", content=samples.hl7_oru_low_grade_temp(patient["mrn"]), headers=HL7)
    assert ok.status_code == 200 and "\rMSA|AA|" in ok.text
    bad = client.post("/api/integrations/hl7v2", content="not hl7", headers=HL7)
    assert bad.status_code == 200 and "MSA|AR|" in bad.text


def test_far_off_discharge_is_held_for_review(client, db, patient):
    from app.models import SurgicalEpisode

    ep = db.scalars(select(SurgicalEpisode).where(SurgicalEpisode.patient_id == uuid.UUID(patient["id"]))).one()
    before = ep.discharge_date
    raw = samples.hl7_adt_discharge(patient["mrn"], ep.surgery_date + timedelta(days=60))
    client.post("/api/integrations/hl7v2", content=raw, headers=HL7)
    db.expire_all()
    assert db.get(SurgicalEpisode, ep.id).discharge_date == before


def test_disabled_source_is_refused(client, tokens, db):
    from app.models import IntegrationSource

    src = db.scalars(select(IntegrationSource).where(IntegrationSource.slug == "patient-wearables")).one()
    client.post(f"/api/admin/integrations/sources/{src.id}/active?active=false", headers=tokens["admin"])
    wearable = {"X-Integration-Key": f"{KEY}-patient-wearables"}
    assert client.post("/api/integrations/devices", content="{}", headers=wearable).status_code == 403
    client.post(f"/api/admin/integrations/sources/{src.id}/active?active=true", headers=tokens["admin"])


def test_rotated_key_replaces_the_old_one(client, tokens, db):
    from app.models import IntegrationSource
    from app.services.integrations import demo_key, hash_key

    src = db.scalars(select(IntegrationSource).where(IntegrationSource.slug == "patient-wearables")).one()
    new_key = client.post(f"/api/admin/integrations/sources/{src.id}/rotate-key", headers=tokens["admin"]).json()["key"]
    old = {"X-Integration-Key": f"{KEY}-patient-wearables"}
    assert client.post("/api/integrations/devices", content="{}", headers=old).status_code == 401
    assert client.post("/api/integrations/devices", content="{}",
                       headers={"X-Integration-Key": new_key}).status_code == 422  # authenticated; body invalid
    # Restore the dev key for other tests.
    db.expire_all()
    src = db.get(IntegrationSource, src.id)
    src.key_hash, src.key_rotated_at = hash_key(demo_key(src.slug)), None
    db.commit()


def test_admin_console_is_admin_only_and_payload_view_is_audited(client, tokens, patient):
    for role in ("nurse", "doctor", "patient"):
        assert client.get("/api/admin/integrations", headers=tokens[role]).status_code == 403
    overview = client.get("/api/admin/integrations", headers=tokens["admin"]).json()
    assert "PLANNED" not in {u["status"] for u in overview["use_cases"]}
    assert overview["outbound"]["mode"] == "SIMULATED"
    assert {s["slug"] for s in overview["sources"]} == {"ehr-fhir", "ehr-hl7", "rpm-devices", "patient-wearables", "pharmacy-network"}

    sim = client.post("/api/admin/integrations/simulate", headers=tokens["admin"],
                      json={"scenario": "hl7_oru_temp", "mrn": patient["mrn"]}).json()
    assert sim["message"]["status"] == "PROCESSED" and sim["message"]["simulated"] and "MSA|AA|" in sim["ack"]
    assert sim["message"]["result"]["readings"]["rules_triggered"] == ["AMBER-LOW-GRADE-TEMP"]

    log = client.get("/api/admin/integrations/messages?limit=5", headers=tokens["admin"]).json()
    assert "payload" not in log[0]
    detail = client.get(f"/api/admin/integrations/messages/{sim['message']['id']}", headers=tokens["admin"]).json()
    assert detail["payload"].startswith("MSH|")
    events = client.get("/api/audit?action=PHI_VIEW_INBOUND_MESSAGE&limit=3", headers=tokens["admin"]).json()
    assert events and events[0]["resource_id"] == sim["message"]["id"]


def test_pharmacy_not_dispensed_creates_nurse_outreach(client, db, patient):
    from app.models import PharmacyFill

    r = client.post("/api/integrations/ncpdp", content=samples.ncpdp_not_dispensed(patient["mrn"]), headers=RX)
    assert r.status_code == 200 and "<Code>010</Code>" in r.text
    (task,) = [a for a in _alerts(db, patient["id"]) if a.rule_id == "INT-RX-NOT-FILLED"]
    assert task.severity == "AMBER" and task.assigned_team == "NURSE" and task.category == "MEDICATION_FILL"
    (fill,) = db.scalars(select(PharmacyFill).where(PharmacyFill.patient_id == uuid.UUID(patient["id"]))).all()
    assert fill.medication_id and fill.status == "NOT_DISPENSED"  # matched to the patient's apixaban
    bad = client.post("/api/integrations/ncpdp", content="<Message><Body/></Message>", headers=RX)
    assert bad.status_code == 422 and "<Code>900</Code>" in bad.text


def test_red_alerts_are_queued_and_delivered_to_the_ehr(client, db, tokens, patient):
    from app.models import OutboundMessage
    from app.services.outbound import deliver_due

    client.post("/api/integrations/devices", content=_reading(patient["mrn"], 38.9, "Cel"), headers=DEVICE)
    (alert,) = [a for a in _alerts(db, patient["id"]) if a.rule_id == "RED-FEVER"]
    out = db.scalars(select(OutboundMessage).where(OutboundMessage.related_id == str(alert.id))).one()
    assert out.resource_type == "Communication" and json.loads(out.payload)["priority"] == "stat"
    deliver_due(db)
    db.commit()
    db.expire_all()
    out = db.get(OutboundMessage, out.id)
    assert out.status == "SENT" and out.delivery_mode == "SIMULATED"  # no OUTBOUND_FHIR_URL in tests
    listed = client.get("/api/admin/integrations/outbound?limit=5", headers=tokens["admin"]).json()
    assert listed and "payload" not in listed[0]
    detail = client.get(f"/api/admin/integrations/outbound/{out.id}", headers=tokens["admin"]).json()
    assert json.loads(detail["payload"])["resourceType"] == "Communication"
    assert client.get("/api/admin/integrations/outbound", headers=tokens["nurse"]).status_code == 403


def test_outbound_http_failure_retries_with_backoff(db, patient, monkeypatch):
    import httpx

    from app.core.config import get_settings
    from app.models import OutboundMessage
    from app.services import outbound

    m = OutboundMessage(destination="ehr-fhir", resource_type="Communication", dedupe_key=f"t:{uuid.uuid4()}",
                        payload="{}", status="PENDING")
    db.add(m)
    db.flush()
    monkeypatch.setattr(get_settings(), "outbound_fhir_url", "http://ehr.invalid/fhir")

    def boom(*a, **kw):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "post", boom)
    for _ in range(outbound.MAX_ATTEMPTS):
        m.status = "PENDING" if m.status == "PENDING" else m.status
        outbound.deliver(db, m)
    assert m.status == "FAILED" and m.attempts == outbound.MAX_ATTEMPTS and "ConnectError" in m.last_error
    db.rollback()
