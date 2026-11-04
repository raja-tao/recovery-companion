"""Normalized inbound record, vocabulary mapping (LOINC / UCUM) and plausibility checks."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone


class ParseError(ValueError):
    """The message as a whole cannot be used (malformed, no patient identifier, ...)."""


# LOINC code -> reading kind. Only codes the program monitors are accepted.
LOINC = {
    "8310-5": "TEMPERATURE",
    "8867-4": "HEART_RATE",
    "59408-5": "SPO2", "2708-6": "SPO2",
    "8480-6": "BP_SYSTOLIC", "8462-4": "BP_DIASTOLIC",
    "29463-7": "WEIGHT",
    "41950-7": "STEPS", "55423-8": "STEPS",
    "72514-3": "PAIN_SCORE",
}
BP_PANEL = "85354-9"

# Canonical unit per kind, and accepted spellings (UCUM codes first) -> converter to canonical.
CANONICAL_UNIT = {"TEMPERATURE": "[degF]", "HEART_RATE": "/min", "SPO2": "%", "BP_SYSTOLIC": "mm[Hg]",
                  "BP_DIASTOLIC": "mm[Hg]", "WEIGHT": "[lb_av]", "STEPS": "{steps}", "PAIN_SCORE": "{score}"}
_C_TO_F = lambda v: round(v * 9 / 5 + 32, 1)  # noqa: E731
_KG_TO_LB = lambda v: round(v * 2.20462, 1)  # noqa: E731
_SAME = lambda v: v  # noqa: E731
UNIT_CONVERSIONS = {
    "TEMPERATURE": {"[degf]": _SAME, "degf": _SAME, "f": _SAME, "cel": _C_TO_F, "c": _C_TO_F, "degc": _C_TO_F},
    "HEART_RATE": {"/min": _SAME, "bpm": _SAME, "{beats}/min": _SAME},
    "SPO2": {"%": _SAME},
    "BP_SYSTOLIC": {"mm[hg]": _SAME, "mmhg": _SAME},
    "BP_DIASTOLIC": {"mm[hg]": _SAME, "mmhg": _SAME},
    "WEIGHT": {"[lb_av]": _SAME, "lb": _SAME, "lbs": _SAME, "kg": _KG_TO_LB},
    "STEPS": {"{steps}": _SAME, "steps": _SAME, "/(24.h)": _SAME, "{steps}/d": _SAME, "": _SAME},
    "PAIN_SCORE": {"{score}": _SAME, "score": _SAME, "": _SAME},
}
# Physiologically plausible range (canonical units). Outside it the reading is rejected, not alerted on.
PLAUSIBLE = {"TEMPERATURE": (90, 110), "HEART_RATE": (20, 250), "SPO2": (50, 100), "BP_SYSTOLIC": (50, 260),
             "BP_DIASTOLIC": (30, 160), "WEIGHT": (50, 700), "STEPS": (0, 100_000), "PAIN_SCORE": (0, 10)}
# Rules-engine fact name per kind. temperature_f and pain_score are used by the approved protocols today.
FACT_FOR_KIND = {"TEMPERATURE": "temperature_f", "PAIN_SCORE": "pain_score", "HEART_RATE": "heart_rate",
                 "SPO2": "spo2", "BP_SYSTOLIC": "bp_systolic", "BP_DIASTOLIC": "bp_diastolic",
                 "WEIGHT": "weight_lb", "STEPS": "steps_24h"}


@dataclass
class Observation:
    kind: str
    value: float
    unit: str
    measured_at: datetime
    code: str | None = None
    device: str | None = None


@dataclass
class InboundRecord:
    channel: str  # FHIR | HL7V2 | DEVICE | PHARMACY
    message_type: str
    external_id: str
    patient_mrn: str | None = None
    discharge_date: date | None = None
    procedure: dict | None = None
    medications: list[dict] = field(default_factory=list)
    appointments: list[dict] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)  # pharmacy fill notifications
    errors: list[str] = field(default_factory=list)  # item-level problems; the rest of the message is still used
    meta: dict = field(default_factory=dict)


def payload_id(raw: str | bytes) -> str:
    """Fallback idempotency key when the sender supplies no message id."""
    data = raw.encode() if isinstance(raw, str) else raw
    return "sha256:" + hashlib.sha256(data).hexdigest()


def kind_for(code: str | None, kind: str | None = None) -> str | None:
    if kind and kind.upper() in CANONICAL_UNIT:
        return kind.upper()
    return LOINC.get(code or "")


def normalize(kind: str, value, unit: str | None, measured_at: datetime, *, code: str | None = None,
              device: str | None = None) -> Observation:
    """Convert to the canonical unit and check plausibility. Raises ValueError with a readable reason."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{kind}: value {value!r} is not a number") from None
    convert = UNIT_CONVERSIONS[kind].get((unit or "").strip().lower())
    if convert is None:
        raise ValueError(f"{kind}: unsupported unit {unit!r}")
    v = convert(v)
    lo, hi = PLAUSIBLE[kind]
    if not lo <= v <= hi:
        raise ValueError(f"{kind}: {v} {CANONICAL_UNIT[kind]} is outside the plausible range {lo}–{hi}")
    return Observation(kind, v, CANONICAL_UNIT[kind], measured_at, code, device)


def parse_datetime(value: str | None) -> datetime | None:
    """ISO 8601 (FHIR / JSON). Naive values are treated as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(value), datetime.min.time())
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def appointment_type(text: str | None) -> str:
    t = (text or "").lower()
    if "therap" in t or t.strip() == "pt":
        return "PT"
    if "wound" in t or "incision" in t or "suture" in t or "staple" in t:
        return "WOUND_CHECK"
    if "lab" in t or "blood" in t:
        return "LAB"
    return "POST_OP_VISIT"
