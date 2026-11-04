"""NCPDP SCRIPT RxFill (fill status) parser and Status / Error responses.

Pharmacies send RxFill when a prescription is dispensed, partially dispensed, not dispensed
(e.g. not picked up) or transferred. Only the subset this program uses is read; element names
follow SCRIPT 2017071 and namespaces are ignored.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from integrations.records import InboundRecord, ParseError, payload_id

FILL_STATUSES = {"Dispensed": "DISPENSED", "PartiallyDispensed": "PARTIAL", "NotDispensed": "NOT_DISPENSED",
                 "Transferred": "TRANSFERRED"}
MAX_FILLS = 50


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el: ET.Element | None, *path: str) -> ET.Element | None:
    """Namespace-agnostic child lookup by local names."""
    for name in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == name), None)
    return el


def _text(el: ET.Element | None, *path: str) -> str | None:
    found = _find(el, *path)
    return (found.text or "").strip() or None if found is not None else None


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def parse(raw: str) -> InboundRecord:
    # No DTDs: rules out entity-expansion and external-entity attacks before parsing.
    if re.search(r"<!(DOCTYPE|ENTITY)", raw, re.I):
        raise ParseError("DOCTYPE / ENTITY declarations are not allowed")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError(f"Not well-formed XML: {exc}") from None
    if _local(root.tag) != "Message":
        raise ParseError("Root element must be an NCPDP SCRIPT <Message>")
    message_id = _text(root, "Header", "MessageID")
    body = _find(root, "Body")
    fills = [c for c in (body if body is not None else []) if _local(c.tag) == "RxFill"]
    if not fills:
        raise ParseError("Only RxFill messages are supported")
    if len(fills) > MAX_FILLS:
        raise ParseError(f"Too many RxFill elements (max {MAX_FILLS})")

    rec = InboundRecord("PHARMACY", "NCPDP RxFill", message_id or payload_id(raw))
    mrns = set()
    for fx in fills:
        mrn = _text(fx, "Patient", "HumanPatient", "Identification", "MedicalRecordIdentificationNumberEHR")
        if mrn:
            mrns.add(mrn)
        status_el = _find(fx, "FillStatus")
        status_name = next((_local(c.tag) for c in (status_el if status_el is not None else [])), None)
        status = FILL_STATUSES.get(status_name or "")
        drug = _text(fx, "MedicationDispensed", "DrugDescription") or _text(fx, "MedicationPrescribed", "DrugDescription")
        if not status or not drug:
            rec.errors.append("RxFill without a recognised FillStatus or DrugDescription was skipped")
            continue
        reason = None
        if status_el is not None:
            reason = _text(_find(status_el, status_name), "Note") or _text(_find(status_el, status_name), "ReasonCode")
        med = _find(fx, "MedicationDispensed")
        if med is None:  # Elements without children are falsy, so no `or` here.
            med = _find(fx, "MedicationPrescribed")
        days = _text(med, "DaysSupply")
        rec.fills.append({
            "drug_description": drug[:200], "status": status, "reason": (reason or "")[:300] or None,
            "quantity": " ".join(x for x in (_text(med, "Quantity", "Value"),
                                             _text(med, "Quantity", "QuantityUnitOfMeasure", "Code")) if x) or None,
            "days_supply": int(days) if days and days.isdigit() else None,
            "fill_date": _date(_text(med, "LastFillDate", "Date")),
            "pharmacy_name": (_text(fx, "Pharmacy", "BusinessName") or "")[:200] or None,
            "ndc": _text(med, "DrugCoded", "ProductCode", "Code"),
        })
    if len(mrns) != 1:
        raise ParseError("Message must identify exactly one patient MRN "
                         "(Patient/HumanPatient/Identification/MedicalRecordIdentificationNumberEHR)")
    rec.patient_mrn = mrns.pop()
    return rec


def status_response(message_id: str | None, accepted: bool, text: str) -> str:
    """NCPDP Status 010 (accepted) or Error 900 (rejected) reply, echoing the sender's MessageID."""
    safe = (text or "").replace("&", "and").replace("<", "(").replace(">", ")")[:250]
    body = (f"<Status><Code>010</Code><Description>{safe}</Description></Status>" if accepted else
            f"<Error><Code>900</Code><Description>{safe}</Description></Error>")
    relates = f"<RelatesToMessageID>{message_id}</RelatesToMessageID>" if message_id else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><Message><Header>{relates}</Header><Body>{body}</Body></Message>')


def message_id_of(raw: str) -> str | None:
    m = re.search(r"<(?:\w+:)?MessageID>\s*([^<]{1,120}?)\s*</", raw or "")
    return m.group(1) if m else None
