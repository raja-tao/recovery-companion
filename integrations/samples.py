"""Sample inbound messages for the admin simulator and tests. Synthetic data only.

Each scenario builds a realistic message for a given MRN with fresh ids and timestamps,
so it runs through exactly the same pipeline as a message from a real sender.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _hl7_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S") + "+0000"


def _segment(name: str, fields: dict[int, str]) -> str:
    """Build a segment from {field number: value} so positions match the HL7 spec exactly."""
    values = [""] * max(fields)
    for n, v in fields.items():
        values[n - 1] = v
    return "|".join([name, *values])


def _discharge_time(surgery_date: date | None) -> datetime:
    """The day after surgery (a typical joint-replacement stay), or a few hours ago when unknown."""
    if surgery_date:
        return datetime.combine(surgery_date + timedelta(days=1), time(14, 0), tzinfo=timezone.utc)
    return _now() - timedelta(hours=3)


def _mrn_ident(mrn: str) -> dict:
    return {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]},
            "system": "urn:oid:2.16.840.1.113883.3.0000.1", "value": mrn}


def fhir_discharge(mrn: str, surgery_date: date | None = None) -> str:
    now, discharged = _now(), _discharge_time(surgery_date)
    subject = {"identifier": _mrn_ident(mrn)}
    resources = [
        {"resourceType": "Patient", "id": "p1", "identifier": [_mrn_ident(mrn)]},
        {"resourceType": "Encounter", "id": "enc1", "status": "finished", "class": {"code": "IMP"},
         "subject": subject, "period": {"start": (discharged - timedelta(days=2)).isoformat(),
                                        "end": discharged.isoformat()},
         "hospitalization": {"dischargeDisposition": {"text": "Home with self-care"}}},
        {"resourceType": "MedicationRequest", "id": "mr1", "status": "active", "intent": "order", "subject": subject,
         "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                                   "code": "309114", "display": "Cephalexin 500 MG Oral Capsule"}],
                                       "text": "Cephalexin 500 mg capsule"},
         "authoredOn": now.date().isoformat(), "requester": {"display": "Dr. Samuel Okafor"},
         "reasonCode": [{"text": "infection prevention"}],
         "dosageInstruction": [{"text": "1 capsule by mouth every 6 hours for 5 days",
                                "timing": {"code": {"text": "Every 6 hours"}}, "route": {"text": "oral"}}]},
        {"resourceType": "MedicationRequest", "id": "mr2", "status": "active", "intent": "order", "subject": subject,
         "medicationCodeableConcept": {"text": "Docusate sodium 100 mg capsule"},
         "authoredOn": now.date().isoformat(), "requester": {"display": "Dr. Samuel Okafor"},
         "reasonCode": [{"text": "constipation"}],
         "dosageInstruction": [{"text": "1 capsule by mouth twice daily as needed", "asNeededBoolean": True,
                                "timing": {"code": {"text": "Twice daily as needed"}}}]},
        {"resourceType": "Appointment", "id": "ap1", "status": "booked",
         "serviceType": [{"text": "Outpatient physical therapy"}],
         "start": (now + timedelta(days=3)).replace(hour=15, minute=0, second=0).isoformat(),
         "end": (now + timedelta(days=3)).replace(hour=16, minute=0, second=0).isoformat(),
         "participant": [{"actor": {"reference": "Patient/p1"}},
                         {"actor": {"reference": "Practitioner/pt1", "display": "Jamie Rivera, PT"}},
                         {"actor": {"reference": "Location/l1", "display": "Synthetic Rehab Center, Suite 200"}}]},
    ]
    return json.dumps({"resourceType": "Bundle", "id": f"discharge-{uuid.uuid4().hex[:12]}", "type": "collection",
                       "timestamp": now.isoformat(), "entry": [{"resource": r} for r in resources]}, indent=2)


def fhir_vitals_fever(mrn: str, surgery_date: date | None = None) -> str:
    now = _now()
    subject = {"identifier": _mrn_ident(mrn)}

    def obs(i, code, display, value, unit):
        return {"resourceType": "Observation", "id": f"o{i}", "status": "final", "subject": subject,
                "category": [{"coding": [{"code": "vital-signs"}]}],
                "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
                "effectiveDateTime": now.isoformat(), "device": {"display": "Home vitals kit"},
                "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit}}

    resources = [obs(1, "8310-5", "Body temperature", 38.5, "Cel"), obs(2, "8867-4", "Heart rate", 104, "/min"),
                 {"resourceType": "Observation", "id": "o3", "status": "final", "subject": subject,
                  "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
                  "effectiveDateTime": now.isoformat(),
                  "component": [
                      {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                       "valueQuantity": {"value": 128, "code": "mm[Hg]"}},
                      {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                       "valueQuantity": {"value": 82, "code": "mm[Hg]"}}]}]
    return json.dumps({"resourceType": "Bundle", "id": f"vitals-{uuid.uuid4().hex[:12]}", "type": "collection",
                       "entry": [{"resource": r} for r in resources]}, indent=2)


def hl7_adt_discharge(mrn: str, surgery_date: date | None = None) -> str:
    now, discharged = _now(), _discharge_time(surgery_date)
    return "\r".join([
        f"MSH|^~\\&|EHR_ADT|SYNTH_HOSP|RECOVERY|POC|{_hl7_ts(now)}||ADT^A03^ADT_A03|ADT{uuid.uuid4().hex[:12]}|P|2.5.1",
        f"EVN|A03|{_hl7_ts(discharged)}",
        f"PID|1||{mrn}^^^SYNTH_HOSP^MR||Synthetic^Patient||19600101|U",
        _segment("PV1", {1: "1", 2: "I", 3: "ORTHO^412^A^SYNTH_HOSP", 36: "01",
                         44: _hl7_ts(discharged - timedelta(days=2)), 45: _hl7_ts(discharged)}),
    ]) + "\r"


def hl7_oru_low_grade_temp(mrn: str, surgery_date: date | None = None) -> str:
    now = _now()
    return "\r".join([
        f"MSH|^~\\&|EHR_RESULTS|SYNTH_HOSP|RECOVERY|POC|{_hl7_ts(now)}||ORU^R01^ORU_R01|ORU{uuid.uuid4().hex[:12]}|P|2.5.1",
        f"PID|1||{mrn}^^^SYNTH_HOSP^MR||Synthetic^Patient||19600101|U",
        f"OBR|1||RES{uuid.uuid4().hex[:8]}|85353-1^Vital signs panel^LN|||{_hl7_ts(now)}",
        f"OBX|1|NM|8310-5^Body temperature^LN||100.6|[degF]^degF^UCUM|||||F|||{_hl7_ts(now)}",
        f"OBX|2|NM|8867-4^Heart rate^LN||88|/min^beats per minute^UCUM|||||F|||{_hl7_ts(now)}",
        f"OBX|3|NM|59408-5^Oxygen saturation^LN||97|%^percent^UCUM|||||F|||{_hl7_ts(now)}",
    ]) + "\r"


def hl7_siu_followup(mrn: str, surgery_date: date | None = None) -> str:
    now = _now()
    start = (now + timedelta(days=7)).replace(hour=14, minute=30, second=0)
    return "\r".join([
        f"MSH|^~\\&|EHR_SCHED|SYNTH_HOSP|RECOVERY|POC|{_hl7_ts(now)}||SIU^S12^SIU_S12|SIU{uuid.uuid4().hex[:12]}|P|2.5.1",
        _segment("SCH", {1: f"APT{uuid.uuid4().hex[:8]}", 7: "POSTOP^Post-op follow-up visit", 9: "30", 10: "min",
                         11: f"^^30^{_hl7_ts(start)}"}),
        f"PID|1||{mrn}^^^SYNTH_HOSP^MR||Synthetic^Patient||19600101|U",
        "RGS|1",
        f"AIS|1||POSTOP^Post-op follow-up visit|{_hl7_ts(start)}|||30",
        "AIP|1||1234^Okafor^Samuel^^^Dr.",
        "AIL|1||ORTHO-CLINIC^^^Synthetic Orthopedic Clinic",
    ]) + "\r"


def _device(mrn: str, device: dict, readings: list[dict]) -> str:
    return json.dumps({"message_id": f"rpm-{uuid.uuid4().hex[:16]}", "patient": {"mrn": mrn}, "device": device,
                       "readings": readings}, indent=2)


def device_fever(mrn: str, surgery_date: date | None = None) -> str:
    t = _now().isoformat()
    return _device(mrn, {"type": "THERMOMETER", "model": "Cellular thermometer (synthetic)", "serial": "TH-0042"},
                   [{"type": "TEMPERATURE", "value": 101.4, "unit": "[degF]", "measured_at": t}])


def device_normal_vitals(mrn: str, surgery_date: date | None = None) -> str:
    t = _now().isoformat()
    return _device(mrn, {"type": "VITALS_HUB", "model": "Bluetooth vitals hub (synthetic)", "serial": "HUB-7781"},
                   [{"type": "TEMPERATURE", "value": 98.9, "unit": "[degF]", "measured_at": t},
                    {"type": "HEART_RATE", "value": 76, "unit": "/min", "measured_at": t},
                    {"type": "SPO2", "value": 97, "unit": "%", "measured_at": t},
                    {"type": "BP_SYSTOLIC", "value": 124, "unit": "mm[Hg]", "measured_at": t},
                    {"type": "BP_DIASTOLIC", "value": 78, "unit": "mm[Hg]", "measured_at": t}])


def wearable_steps(mrn: str, surgery_date: date | None = None) -> str:
    t = _now().isoformat()
    return _device(mrn, {"type": "WEARABLE", "model": "Phone health app sync (synthetic)"},
                   [{"type": "STEPS", "value": 3240, "unit": "{steps}", "measured_at": t},
                    {"type": "HEART_RATE", "value": 82, "unit": "/min", "measured_at": t}])


def _rx_fill(mrn: str, fills: list[tuple[str, str, str]]) -> str:
    """fills: (drug description, FillStatus element, note)."""
    import uuid

    today = _now().date().isoformat()
    parts = []
    for drug, status, note in fills:
        status_xml = f"<{status}><Note>{note}</Note></{status}>" if note else f"<{status}/>"
        parts.append(
            f"<RxFill><FillStatus>{status_xml}</FillStatus>"
            f"<Patient><HumanPatient><Identification><MedicalRecordIdentificationNumberEHR>{mrn}"
            f"</MedicalRecordIdentificationNumberEHR></Identification></HumanPatient></Patient>"
            f"<Pharmacy><Identification><NCPDPID>9900012</NCPDPID></Identification>"
            f"<BusinessName>Main Street Pharmacy (synthetic)</BusinessName></Pharmacy>"
            f"<MedicationDispensed><DrugDescription>{drug}</DrugDescription>"
            f"<Quantity><Value>28</Value><QuantityUnitOfMeasure><Code>C48480</Code></QuantityUnitOfMeasure></Quantity>"
            f"<DaysSupply>14</DaysSupply><LastFillDate><Date>{today}</Date></LastFillDate></MedicationDispensed>"
            f"</RxFill>")
    return (f'<?xml version="1.0" encoding="UTF-8"?><Message xmlns="http://www.ncpdp.org/schema/SCRIPT" '
            f'version="2017071"><Header><To>RECOVERY_COMPANION</To><From>PHARMACY_NETWORK</From>'
            f"<MessageID>RXF-{uuid.uuid4().hex[:12]}</MessageID><SentTime>{_now().isoformat()}</SentTime></Header>"
            f"<Body>{''.join(parts)}</Body></Message>")


def ncpdp_dispensed(mrn: str, surgery_date: date | None = None) -> str:
    return _rx_fill(mrn, [("Apixaban 2.5 mg tablet", "Dispensed", None)])


def ncpdp_not_dispensed(mrn: str, surgery_date: date | None = None) -> str:
    return _rx_fill(mrn, [("Apixaban 2.5 mg tablet", "NotDispensed", "Prescription not picked up within 48 hours")])


# key -> (title, source slug, content type, builder, what to expect)
SCENARIOS = {
    "fhir_discharge": ("FHIR discharge bundle", "ehr-fhir", "application/fhir+json", fhir_discharge,
                       "Discharge confirmed, 2 discharge medications, 1 PT appointment, doctor reconciliation task"),
    "fhir_vitals_fever": ("FHIR vitals: 38.5 °C", "ehr-fhir", "application/fhir+json", fhir_vitals_fever,
                          "38.5 °C = 101.3 °F → RED fever protocol → nurse alert (15 min)"),
    "hl7_adt_discharge": ("HL7 ADT^A03 discharge", "ehr-hl7", "text/plain", hl7_adt_discharge,
                          "Discharge date confirmed against the episode; ACK AA returned"),
    "hl7_oru_temp": ("HL7 ORU^R01 vitals: 100.6 °F", "ehr-hl7", "text/plain", hl7_oru_low_grade_temp,
                     "AMBER low-grade temperature alert (4 h)"),
    "hl7_siu_followup": ("HL7 SIU^S12 follow-up visit", "ehr-hl7", "text/plain", hl7_siu_followup,
                         "Post-op visit added to the patient's appointments"),
    "device_fever": ("Thermometer: 101.4 °F", "rpm-devices", "application/json", device_fever,
                     "RED fever protocol → nurse alert + SMS to on-call nurse"),
    "device_normal": ("Vitals hub: normal readings", "rpm-devices", "application/json", device_normal_vitals,
                      "Readings stored, no protocol matched (GREEN)"),
    "wearable_steps": ("Wearable: daily steps", "patient-wearables", "application/json", wearable_steps,
                       "Steps and heart rate stored for the care team; no alert"),
    "ncpdp_dispensed": ("Pharmacy: prescription picked up", "pharmacy-network", "application/xml", ncpdp_dispensed,
                        "Fill recorded against the patient's medication; NCPDP Status 010 returned"),
    "ncpdp_not_dispensed": ("Pharmacy: prescription not picked up", "pharmacy-network", "application/xml",
                            ncpdp_not_dispensed, "AMBER nurse outreach task: patient may not have their medication"),
}
