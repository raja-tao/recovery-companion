"""FHIR / HL7 v2 / device parsers: normalization, plausibility, identifiers, ACKs. No database."""
import json
from datetime import date

import pytest

from integrations import devices, fhir, hl7v2, ncpdp, samples
from integrations.records import ParseError, normalize, parse_datetime

NOW = "2026-11-04T08:00:00Z"


def test_units_are_converted_and_ranges_enforced():
    assert normalize("TEMPERATURE", 38.5, "Cel", parse_datetime(NOW)).value == 101.3
    assert normalize("WEIGHT", 80, "kg", parse_datetime(NOW)).value == 176.4
    with pytest.raises(ValueError, match="plausible range"):
        normalize("TEMPERATURE", 120, "[degF]", parse_datetime(NOW))
    with pytest.raises(ValueError, match="unsupported unit"):
        normalize("TEMPERATURE", 99, "kelvin", parse_datetime(NOW))


def test_fhir_discharge_bundle():
    rec = fhir.parse_bundle(samples.fhir_discharge("SYN-1", date(2026, 11, 1)))
    assert rec.patient_mrn == "SYN-1" and rec.discharge_date == date(2026, 11, 2)
    assert [m["name"] for m in rec.medications] == ["Cephalexin 500 mg capsule", "Docusate sodium 100 mg capsule"]
    assert rec.medications[1]["as_needed"] is True
    (appt,) = rec.appointments
    assert appt["appointment_type"] == "PT" and appt["duration_minutes"] == 60 and appt["provider_name"] == "Jamie Rivera, PT"


def test_fhir_vitals_with_bp_panel():
    rec = fhir.parse_bundle(samples.fhir_vitals_fever("SYN-1"))
    assert {o.kind: o.value for o in rec.observations} == {"TEMPERATURE": 101.3, "HEART_RATE": 104, "BP_SYSTOLIC": 128,
                                                           "BP_DIASTOLIC": 82}


def test_fhir_rejects_multi_patient_and_missing_mrn():
    two = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "Patient", "identifier": [{"value": "A"}]}},
        {"resource": {"resourceType": "Patient", "identifier": [{"value": "B"}]}}]}
    with pytest.raises(ParseError, match="more than one patient"):
        fhir.parse_bundle(json.dumps(two))
    with pytest.raises(ParseError, match="MRN"):
        fhir.parse_bundle(json.dumps({"resourceType": "Bundle", "entry": []}))
    with pytest.raises(ParseError, match="Bundle"):
        fhir.parse_bundle('{"resourceType": "Patient"}')


def test_fhir_bad_observation_is_an_item_error_not_a_failure():
    bundle = json.loads(samples.fhir_vitals_fever("SYN-1"))
    bundle["entry"][0]["resource"]["valueQuantity"]["value"] = 55  # 55 °C
    rec = fhir.parse_bundle(json.dumps(bundle))
    assert len(rec.errors) == 1 and "plausible range" in rec.errors[0]
    assert {o.kind for o in rec.observations} == {"HEART_RATE", "BP_SYSTOLIC", "BP_DIASTOLIC"}


def test_hl7_adt_oru_siu():
    rec, _ = hl7v2.parse(samples.hl7_adt_discharge("SYN-2", date(2026, 11, 1)))
    assert rec.message_type == "ADT^A03" and rec.patient_mrn == "SYN-2" and rec.discharge_date == date(2026, 11, 2)
    rec, _ = hl7v2.parse(samples.hl7_oru_low_grade_temp("SYN-2"))
    assert [(o.kind, o.value) for o in rec.observations] == [("TEMPERATURE", 100.6), ("HEART_RATE", 88), ("SPO2", 97)]
    rec, _ = hl7v2.parse(samples.hl7_siu_followup("SYN-2"))
    (appt,) = rec.appointments
    assert appt["appointment_type"] == "POST_OP_VISIT" and appt["provider_name"] == "Samuel Okafor"


def test_hl7_mrn_prefers_mr_identifier_and_skips_non_final_results():
    raw = ("MSH|^~\\&|A|B|C|D|20261104080000||ORU^R01|X1|P|2.5.1\r"
           "PID|1||999^^^SSA^SS~SYN-9^^^HOSP^MR\r"
           "OBX|1|NM|8310-5^Temp^LN||101.2|[degF]|||||P\r"
           "OBX|2|NM|8867-4^HR^LN||70|/min|||||F\r")
    rec, _ = hl7v2.parse(raw)
    assert rec.patient_mrn == "SYN-9"
    assert [o.kind for o in rec.observations] == ["HEART_RATE"]
    assert "result status P" in rec.errors[0]


def test_hl7_unsupported_type_and_ack_codes():
    raw = "MSH|^~\\&|A|B|C|D|20261104080000||ADT^A08|X2|P|2.5.1\rPID|1||SYN-9^^^HOSP^MR\r"
    with pytest.raises(ParseError, match="Unsupported message type ADT\\^A08"):
        hl7v2.parse(raw)
    ack = hl7v2.ack(raw, "AR", "bad | thing").split("\r")
    assert ack[0].startswith("MSH|^~\\&|RECOVERY_COMPANION|POC|A|B|") and "ACK^A08^ACK" in ack[0]
    assert ack[1] == "MSA|AR|X2|bad / thing"
    assert hl7v2.ack("garbage", "AR", "x").split("\r")[1] == "MSA|AR||x"


def test_hl7_timestamps_with_offset():
    assert hl7v2.ts("202611040800-0500").isoformat() == "2026-11-04T08:00:00-05:00"
    assert hl7v2.ts("20261104").isoformat() == "2026-11-04T00:00:00+00:00"
    assert hl7v2.ts("nonsense") is None


def test_device_feed_partial_and_required_fields():
    rec = devices.parse(json.dumps({"message_id": "m1", "patient": {"mrn": "SYN-3"}, "readings": [
        {"type": "TEMPERATURE", "value": 100.1, "unit": "[degF]", "measured_at": NOW},
        {"code": "8867-4", "value": 72, "unit": "bpm", "measured_at": NOW},
        {"type": "GLUCOSE", "value": 5, "measured_at": NOW},
        {"type": "SPO2", "value": 97, "unit": "%"}]}))
    assert rec.external_id == "m1" and [o.kind for o in rec.observations] == ["TEMPERATURE", "HEART_RATE"]
    assert len(rec.errors) == 2
    with pytest.raises(ParseError, match="patient.mrn"):
        devices.parse(json.dumps({"readings": [{}]}))
    with pytest.raises(ParseError, match="non-empty"):
        devices.parse(json.dumps({"patient": {"mrn": "x"}, "readings": []}))


def test_missing_message_id_falls_back_to_payload_hash():
    body = json.dumps({"patient": {"mrn": "SYN-3"}, "readings": [
        {"type": "STEPS", "value": 100, "unit": "{steps}", "measured_at": NOW}]})
    assert devices.parse(body).external_id == devices.parse(body).external_id
    assert devices.parse(body).external_id.startswith("sha256:")


@pytest.mark.parametrize("key", list(samples.SCENARIOS))
def test_every_sample_scenario_parses_cleanly(key):
    _, _, content_type, build, _ = samples.SCENARIOS[key]
    raw = build("SYN-1", date(2026, 11, 1))
    rec = (hl7v2.parse(raw)[0] if content_type == "text/plain" else ncpdp.parse(raw) if "xml" in content_type else
           fhir.parse_bundle(raw) if "fhir" in content_type else devices.parse(raw))
    assert rec.patient_mrn == "SYN-1" and not rec.errors


def test_ncpdp_rxfill_parse_and_replies():
    rec = ncpdp.parse(samples.ncpdp_not_dispensed("SYN-4"))
    (fill,) = rec.fills
    assert rec.patient_mrn == "SYN-4" and rec.external_id.startswith("RXF-")
    assert fill["status"] == "NOT_DISPENSED" and fill["reason"].startswith("Prescription not picked up")
    assert fill["days_supply"] == 14 and fill["quantity"] == "28 C48480"
    ok = ncpdp.status_response("RXF-1", True, "Accepted")
    assert "<Code>010</Code>" in ok and "<RelatesToMessageID>RXF-1<" in ok
    assert "<Code>900</Code>" in ncpdp.status_response(None, False, "bad <thing>")


def test_ncpdp_refuses_dtds_and_other_messages():
    with pytest.raises(ParseError, match="DOCTYPE"):
        ncpdp.parse('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Message/>')
    with pytest.raises(ParseError, match="RxFill"):
        ncpdp.parse("<Message><Header/><Body><NewRx/></Body></Message>")
    with pytest.raises(ParseError, match="well-formed"):
        ncpdp.parse("<Message>")
