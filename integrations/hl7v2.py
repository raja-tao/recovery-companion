"""HL7 v2.x parser (ER7 pipe-delimited) for ADT^A03, ORU^R01 and SIU^S12, plus ACK builder.

Interface engines expect a synchronous ACK: AA (accepted), AE (application error) or
AR (rejected). Timestamps without an offset are treated as UTC in this POC; production
uses the sending facility's time zone.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from integrations.records import (
    InboundRecord, ParseError, appointment_type, kind_for, normalize, payload_id,
)

SUPPORTED = {"ADT^A03", "ORU^R01", "SIU^S12"}
FINAL_STATUSES = {"F", "C", "R", ""}  # final, corrected, unverified-but-sent; skip P/W/X/D


class Message:
    def __init__(self, raw: str):
        text = raw.replace("\r\n", "\r").replace("\n", "\r").strip("\r ")
        if not text.startswith("MSH"):
            raise ParseError("HL7 v2 message must start with an MSH segment")
        self.field_sep = text[3]
        self.comp_sep, self.rep_sep = text[4], text[5]
        self.segments: list[list[str]] = []
        for line in filter(None, (s.strip() for s in text.split("\r"))):
            fields = line.split(self.field_sep)
            if fields[0] == "MSH":  # MSH-1 is the separator itself, so shift to keep HL7 numbering
                fields = ["MSH", self.field_sep] + fields[1:]
            self.segments.append(fields)

    def all(self, seg: str) -> list[list[str]]:
        return [s for s in self.segments if s[0] == seg]

    def first(self, seg: str) -> list[str] | None:
        return next(iter(self.all(seg)), None)

    def get(self, segment: list[str] | None, field: int, comp: int = 1, rep: int = 0) -> str:
        if not segment or field >= len(segment):
            return ""
        reps = segment[field].split(self.rep_sep) if field != 2 or segment[0] != "MSH" else [segment[field]]
        if rep >= len(reps):
            return ""
        comps = reps[rep].split(self.comp_sep)
        return comps[comp - 1] if comp - 1 < len(comps) else ""

    def reps(self, segment: list[str] | None, field: int) -> int:
        return len(segment[field].split(self.rep_sep)) if segment and field < len(segment) else 0


def ts(value: str) -> datetime | None:
    """HL7 DTM: YYYY[MM[DD[HH[MM[SS]]]]][+/-ZZZZ]."""
    if not value:
        return None
    offset = None
    for sign in "+-":
        if sign in value[8:]:
            idx = value.rindex(sign)
            value, off = value[:idx], value[idx + 1:]
            minutes = int(off[:2]) * 60 + int(off[2:4] or 0)
            offset = timezone(timedelta(minutes=minutes if sign == "+" else -minutes))
            break
    value = value.split(".")[0]
    fmt = "%Y%m%d%H%M%S"[: {4: 2, 6: 4, 8: 6, 10: 8, 12: 10, 14: 12}.get(len(value), 0)]
    if not fmt:
        return None
    try:
        dt = datetime.strptime(value, fmt)
    except ValueError:
        return None
    return dt.replace(tzinfo=offset or timezone.utc)


def parse(raw: str) -> tuple[InboundRecord, Message]:
    msg = Message(raw)
    msh = msg.first("MSH")
    mtype = f"{msg.get(msh, 9, 1)}^{msg.get(msh, 9, 2)}"
    control_id = msg.get(msh, 10) or payload_id(raw)
    rec = InboundRecord("HL7V2", mtype, control_id)
    rec.meta.update(sending_application=msg.get(msh, 3), sending_facility=msg.get(msh, 4),
                    version=msg.get(msh, 12))
    if mtype not in SUPPORTED:
        raise ParseError(f"Unsupported message type {mtype} (supported: {', '.join(sorted(SUPPORTED))})")

    pid = msg.first("PID")
    rec.patient_mrn = _mrn(msg, pid)
    if not rec.patient_mrn:
        raise ParseError("PID-3 has no patient identifier (MRN)")

    if mtype == "ADT^A03":
        pv1 = msg.first("PV1")
        discharged = ts(msg.get(pv1, 45)) or ts(msg.get(msg.first("EVN"), 2))
        if not discharged:
            raise ParseError("ADT^A03 without a discharge time (PV1-45 / EVN-2)")
        rec.discharge_date = discharged.date()
        rec.meta["discharge_disposition"] = msg.get(pv1, 36) or None
    elif mtype == "ORU^R01":
        for obx in msg.all("OBX"):
            _obx(msg, obx, rec)
        if not rec.observations and not rec.errors:
            rec.errors.append("ORU^R01 contained no usable OBX results")
    elif mtype == "SIU^S12":
        _appointment(msg, rec)
    return rec, msg


def _mrn(msg: Message, pid: list[str] | None) -> str | None:
    first = None
    for i in range(msg.reps(pid, 3)):
        value = msg.get(pid, 3, 1, i)
        if value and msg.get(pid, 3, 5, i) in ("MR", "MRN"):
            return value
        first = first or value
    return first


def _obx(msg: Message, obx: list[str], rec: InboundRecord) -> None:
    code, label = msg.get(obx, 3, 1), msg.get(obx, 3, 2)
    status = msg.get(obx, 11)
    if status not in FINAL_STATUSES:
        rec.errors.append(f"OBX {code}: skipped (result status {status})")
        return
    kind = kind_for(code)
    if not kind:
        rec.errors.append(f"OBX {code} {label}: unsupported observation code")
        return
    when = ts(msg.get(obx, 14)) or ts(msg.get(msg.first("OBR"), 7)) or datetime.now(timezone.utc)
    try:
        rec.observations.append(normalize(kind, msg.get(obx, 5), msg.get(obx, 6, 1), when, code=code,
                                          device=msg.get(obx, 18) or None))
    except ValueError as exc:
        rec.errors.append(f"OBX {code}: {exc}")


def _appointment(msg: Message, rec: InboundRecord) -> None:
    sch, ais, aip, ail = (msg.first(s) for s in ("SCH", "AIS", "AIP", "AIL"))
    start = ts(msg.get(sch, 11, 4)) or ts(msg.get(ais, 4))
    if not start:
        raise ParseError("SIU^S12 without a start time (SCH-11.4 / AIS-4)")
    duration = msg.get(sch, 9) or msg.get(ais, 7)
    service = msg.get(ais, 3, 2) or msg.get(sch, 7, 2) or msg.get(sch, 7, 1)
    given, family = msg.get(aip, 3, 3), msg.get(aip, 3, 2)
    location = ", ".join(p for p in (msg.get(ail, 3, 1), msg.get(ail, 3, 4)) if p)
    rec.appointments.append({
        "appointment_type": appointment_type(service),
        "description": service or None,
        "provider_name": (" ".join(p for p in (given, family) if p) or "Care team")[:200],
        "location": (location or "To be confirmed")[:300],
        "scheduled_at": start,
        "duration_minutes": int(duration) if duration.isdigit() else 30,
        "status": "SCHEDULED",
        "external_id": msg.get(sch, 1) or msg.get(sch, 2) or None,
    })


def ack(raw_or_msg: str | Message | None, code: str, text: str = "") -> str:
    """Build an ACK. `code` is AA, AE or AR. Works even when the inbound message could not be parsed."""
    msg = raw_or_msg if isinstance(raw_or_msg, Message) else None
    if msg is None and isinstance(raw_or_msg, str):
        try:
            msg = Message(raw_or_msg)
        except ParseError:
            msg = None
    msh = msg.first("MSH") if msg else None
    get = (lambda f, c=1: msg.get(msh, f, c)) if msg else (lambda f, c=1: "")
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    clean = text.replace("|", "/").replace("^", " ").replace("\r", " ").replace("\n", " ")[:200]
    return "\r".join([
        f"MSH|^~\\&|RECOVERY_COMPANION|POC|{get(3)}|{get(4)}|{now}||ACK^{get(9, 2)}^ACK|{uuid.uuid4().hex[:20]}|P|"
        f"{get(12) or '2.5.1'}",
        f"MSA|{code}|{get(10)}|{clean}",
    ]) + "\r"
