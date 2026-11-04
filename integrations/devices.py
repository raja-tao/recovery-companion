"""Remote patient monitoring (RPM) / wearable reading feed.

Shape (one patient per message), as posted by a device-vendor cloud or the patient app
(Apple HealthKit / Google Health Connect sync):

    {"message_id": "...", "patient": {"mrn": "SYN-100200"},
     "device": {"type": "THERMOMETER", "model": "...", "serial": "..."},
     "readings": [{"type": "TEMPERATURE", "value": 100.8, "unit": "[degF]",
                   "measured_at": "2026-11-04T08:15:00Z"}]}

`type` may be a reading kind (TEMPERATURE, HEART_RATE, SPO2, BP_SYSTOLIC, BP_DIASTOLIC, WEIGHT,
STEPS, PAIN_SCORE) or a LOINC code via `code`.
"""
from __future__ import annotations

import json

from integrations.records import InboundRecord, ParseError, kind_for, normalize, parse_datetime, payload_id


def parse(raw: str | bytes) -> InboundRecord:
    try:
        body = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ParseError(f"Body is not valid JSON: {exc}") from None
    if not isinstance(body, dict):
        raise ParseError("Expected a JSON object")
    mrn = (body.get("patient") or {}).get("mrn")
    if not mrn:
        raise ParseError("patient.mrn is required")
    readings = body.get("readings")
    if not isinstance(readings, list) or not readings:
        raise ParseError("readings must be a non-empty list")
    if len(readings) > 500:
        raise ParseError("At most 500 readings per message")

    device = body.get("device") or {}
    label = " ".join(str(device[k]) for k in ("type", "model") if device.get(k)) or None
    rec = InboundRecord("DEVICE", f"Readings/{device.get('type') or 'UNKNOWN'}",
                        str(body.get("message_id") or payload_id(raw)), patient_mrn=str(mrn))
    rec.meta["device"] = {k: device.get(k) for k in ("type", "model", "serial") if device.get(k)}
    for i, r in enumerate(readings):
        kind = kind_for(r.get("code"), r.get("type"))
        when = parse_datetime(r.get("measured_at"))
        if not kind:
            rec.errors.append(f"reading {i}: unsupported type {r.get('type') or r.get('code')!r}")
        elif not when:
            rec.errors.append(f"reading {i}: measured_at missing or not ISO 8601")
        else:
            try:
                rec.observations.append(normalize(kind, r.get("value"), r.get("unit"), when, code=r.get("code"),
                                                  device=label))
            except ValueError as exc:
                rec.errors.append(f"reading {i}: {exc}")
    return rec
