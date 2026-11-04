"""FHIR R4 Bundle parser (US Core-shaped resources).

Supported resources: Patient (MRN), Encounter (discharge), Procedure (surgery, informational),
MedicationRequest (discharge medications), Appointment (follow-ups) and Observation (vitals,
including the blood-pressure panel). Anything else is ignored and listed in `meta.ignored`.
One Bundle = one patient.
"""
from __future__ import annotations

import json
from datetime import timedelta

from integrations.records import (
    BP_PANEL, InboundRecord, ParseError, appointment_type, kind_for, normalize, parse_datetime, payload_id,
)

MRN_TYPE_CODES = {"MR", "MRN"}


def _text(concept: dict | None) -> str | None:
    if not concept:
        return None
    if concept.get("text"):
        return concept["text"]
    for c in concept.get("coding") or []:
        if c.get("display"):
            return c["display"]
    return None


def _loinc(concept: dict | None) -> str | None:
    for c in (concept or {}).get("coding") or []:
        if "loinc" in (c.get("system") or "") or not c.get("system"):
            return c.get("code")
    return None


def _mrn(identifiers: list | None) -> str | None:
    identifiers = identifiers or []
    for i in identifiers:
        codes = {c.get("code") for c in ((i.get("type") or {}).get("coding") or [])}
        if codes & MRN_TYPE_CODES and i.get("value"):
            return i["value"]
    return next((i["value"] for i in identifiers if i.get("value")), None)


def _subject_mrn(resource: dict) -> str | None:
    ident = ((resource.get("subject") or resource.get("patient") or {}).get("identifier"))
    return _mrn([ident]) if ident else None


def parse_bundle(raw: str | bytes) -> InboundRecord:
    try:
        bundle = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ParseError(f"Body is not valid JSON: {exc}") from None
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ParseError("Expected a FHIR Bundle (resourceType = Bundle)")

    external_id = (bundle.get("identifier") or {}).get("value") or bundle.get("id") or payload_id(raw)
    rec = InboundRecord("FHIR", f"Bundle/{bundle.get('type', 'collection')}", external_id)
    mrns: set[str] = set()
    ignored: list[str] = []

    for entry in bundle.get("entry") or []:
        r = entry.get("resource") or {}
        rtype = r.get("resourceType")
        try:
            if rtype == "Patient":
                if m := _mrn(r.get("identifier")):
                    mrns.add(m)
            elif rtype == "Encounter":
                end = parse_datetime((r.get("period") or {}).get("end"))
                if end and r.get("status") in ("finished", None):
                    rec.discharge_date = end.date()
                    rec.meta["discharge_disposition"] = _text((r.get("hospitalization") or {}).get("dischargeDisposition"))
            elif rtype == "Procedure":
                rec.procedure = {"name": _text(r.get("code")),
                                 "performed": (r.get("performedDateTime")
                                               or (r.get("performedPeriod") or {}).get("start"))}
            elif rtype == "MedicationRequest":
                _medication(rec, r)
            elif rtype == "Appointment":
                _appointment(rec, r)
            elif rtype == "Observation":
                _observation(rec, r)
            elif rtype:
                ignored.append(rtype)
            if rtype != "Patient" and (m := _subject_mrn(r)):
                mrns.add(m)
        except ValueError as exc:
            rec.errors.append(f"{rtype}/{r.get('id', '?')}: {exc}")

    if not mrns:
        raise ParseError("No patient identifier (MRN) found in the Bundle")
    if len(mrns) > 1:
        raise ParseError("Bundle refers to more than one patient; send one Bundle per patient")
    rec.patient_mrn = mrns.pop()
    if ignored:
        rec.meta["ignored"] = sorted(set(ignored))
    return rec


def _medication(rec: InboundRecord, r: dict) -> None:
    if r.get("status") not in ("active", None):
        return
    name = _text(r.get("medicationCodeableConcept")) or (r.get("medicationReference") or {}).get("display")
    if not name:
        raise ValueError("medication name missing")
    dosage = (r.get("dosageInstruction") or [{}])[0]
    authored = parse_datetime(r.get("authoredOn"))
    rec.medications.append({
        "name": name[:120],
        "dose_text": (dosage.get("text") or "As prescribed")[:120],
        "frequency": (_text((dosage.get("timing") or {}).get("code")) or dosage.get("text") or "As prescribed")[:80],
        "route": (_text(dosage.get("route")) or "oral")[:40],
        "as_needed": bool(dosage.get("asNeededBoolean")),
        "indication": (_text((r.get("reasonCode") or [None])[0]) or "as prescribed")[:120],
        "prescriber": (r.get("requester") or {}).get("display"),
        "start_date": authored.date() if authored else None,
        "external_id": r.get("id"),
    })


def _appointment(rec: InboundRecord, r: dict) -> None:
    start = parse_datetime(r.get("start"))
    if not start:
        raise ValueError("appointment start missing")
    end = parse_datetime(r.get("end"))
    service = _text((r.get("serviceType") or [None])[0]) or _text(r.get("appointmentType")) or r.get("description")
    provider = location = None
    for p in r.get("participant") or []:
        actor = p.get("actor") or {}
        ref = actor.get("reference") or ""
        if ref.startswith("Practitioner") and not provider:
            provider = actor.get("display")
        elif ref.startswith("Location") and not location:
            location = actor.get("display")
    rec.appointments.append({
        "appointment_type": appointment_type(service),
        "description": service,
        "provider_name": (provider or "Care team")[:200],
        "location": (location or "To be confirmed")[:300],
        "scheduled_at": start,
        "duration_minutes": int((end - start) / timedelta(minutes=1)) if end and end > start else 30,
        "status": "CANCELLED" if r.get("status") in ("cancelled", "noshow") else "SCHEDULED",
        "external_id": r.get("id"),
    })


def _observation(rec: InboundRecord, r: dict) -> None:
    if r.get("status") in ("entered-in-error", "cancelled"):
        return
    when = parse_datetime(r.get("effectiveDateTime") or r.get("issued"))
    if not when:
        raise ValueError("observation time missing")
    device = (r.get("device") or {}).get("display")
    code = _loinc(r.get("code"))
    parts = r.get("component") if code == BP_PANEL else [r]
    for part in parts or []:
        part_code = _loinc(part.get("code"))
        kind = kind_for(part_code)
        if not kind:
            raise ValueError(f"unsupported observation code {part_code}")
        q = part.get("valueQuantity") or {}
        value = q.get("value", part.get("valueInteger"))
        rec.observations.append(normalize(kind, value, q.get("code") or q.get("unit"), when, code=part_code,
                                          device=device))
