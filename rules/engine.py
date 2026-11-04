"""Deterministic warning-protocol rules engine.

The LLM never sees, sets or overrides these thresholds. Protocols are data
(stored in `warning_protocols`, approved by a surgeon) expressed in a small JSON
condition DSL:

    {"all": [cond, ...]}             every sub-condition true
    {"any": [cond, ...]}             at least one true
    {"not": cond}
    {"fact": "pain_score", "op": ">=", "value": 7}

Supported ops: == != > >= < <= in not_in contains contains_any is_true is_false exists

`evaluate()` returns whether the condition matched plus the evidence (facts and
thresholds) that made it match, which is stored on the alert for clinicians.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

SEVERITY_ORDER = {"GREEN": 0, "INFO": 1, "AMBER": 2, "RED": 3}


def max_severity(levels: Iterable[str]) -> str:
    best = "GREEN"
    for lvl in levels:
        if SEVERITY_ORDER.get(lvl, 0) > SEVERITY_ORDER[best]:
            best = lvl
    return best


class RuleDefinitionError(ValueError):
    pass


def _cmp(op: str, actual: Any, expected: Any) -> bool:
    if op == "exists":
        return actual is not None and actual != "" and actual != []
    if actual is None:
        return False
    try:
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == ">":
            return float(actual) > float(expected)
        if op == ">=":
            return float(actual) >= float(expected)
        if op == "<":
            return float(actual) < float(expected)
        if op == "<=":
            return float(actual) <= float(expected)
        if op == "in":
            return actual in expected
        if op == "not_in":
            return actual not in expected
        if op == "contains":
            return expected in (actual or [])
        if op == "contains_any":
            return any(e in (actual or []) for e in expected)
        if op == "is_true":
            return actual is True
        if op == "is_false":
            return actual is False
    except (TypeError, ValueError):
        return False
    raise RuleDefinitionError(f"Unsupported operator: {op}")


def evaluate(condition: dict, facts: dict) -> tuple[bool, list[dict]]:
    """Evaluate a condition against facts. Returns (matched, evidence)."""
    if not isinstance(condition, dict):
        raise RuleDefinitionError("Condition must be an object")
    if "all" in condition:
        evidence: list[dict] = []
        for sub in condition["all"]:
            ok, ev = evaluate(sub, facts)
            if not ok:
                return False, []
            evidence.extend(ev)
        return True, evidence
    if "any" in condition:
        evidence = []
        matched = False
        for sub in condition["any"]:
            ok, ev = evaluate(sub, facts)
            if ok:
                matched = True
                evidence.extend(ev)
        return matched, evidence if matched else []
    if "not" in condition:
        ok, _ = evaluate(condition["not"], facts)
        return (not ok), ([{"fact": "not", "detail": "negated condition satisfied"}] if not ok else [])
    if "fact" in condition:
        fact, op, expected = condition["fact"], condition.get("op", "=="), condition.get("value")
        actual = facts.get(fact)
        ok = _cmp(op, actual, expected)
        return ok, ([{"fact": fact, "op": op, "threshold": expected, "actual": actual}] if ok else [])
    raise RuleDefinitionError(f"Unknown condition shape: {list(condition)}")


def validate_condition(condition: dict) -> None:
    """Raise RuleDefinitionError if the condition is malformed (used on protocol save)."""
    if "all" in condition or "any" in condition:
        subs = condition.get("all", condition.get("any"))
        if not isinstance(subs, list) or not subs:
            raise RuleDefinitionError("all/any requires a non-empty list")
        for s in subs:
            validate_condition(s)
    elif "not" in condition:
        validate_condition(condition["not"])
    elif "fact" in condition:
        _cmp(condition.get("op", "=="), None, condition.get("value"))  # op check
        if condition.get("op", "==") not in {"==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains",
                                             "contains_any", "is_true", "is_false", "exists"}:
            raise RuleDefinitionError(f"Unsupported operator: {condition.get('op')}")
    else:
        raise RuleDefinitionError("Condition must contain all/any/not/fact")


@dataclass
class ProtocolSpec:
    """Engine-side view of a warning protocol (decoupled from the ORM)."""
    rule_id: str
    name: str
    severity: str
    condition: dict
    response_minutes: int
    assigned_team: str = "NURSE"
    category: str = "CLINICAL"
    patient_message: str = ""
    protocol_id: Any = None
    procedure_type: str = "ALL"


@dataclass
class RuleMatch:
    rule_id: str
    name: str
    severity: str
    evidence: list[dict]
    response_minutes: int
    assigned_team: str
    category: str
    patient_message: str
    protocol_id: Any = None


@dataclass
class EvaluationResult:
    risk_level: str
    matches: list[RuleMatch] = field(default_factory=list)

    def as_json(self) -> list[dict]:
        return [
            {"rule_id": m.rule_id, "name": m.name, "severity": m.severity, "evidence": m.evidence,
             "response_minutes": m.response_minutes, "assigned_team": m.assigned_team}
            for m in self.matches
        ]


def evaluate_protocols(protocols: Iterable[ProtocolSpec], facts: dict, procedure_type: str | None = None
                       ) -> EvaluationResult:
    matches: list[RuleMatch] = []
    for p in protocols:
        if procedure_type and p.procedure_type not in ("ALL", procedure_type):
            continue
        ok, evidence = evaluate(p.condition, facts)
        if ok:
            matches.append(RuleMatch(p.rule_id, p.name, p.severity, evidence, p.response_minutes,
                                     p.assigned_team, p.category, p.patient_message, p.protocol_id))
    matches.sort(key=lambda m: -SEVERITY_ORDER.get(m.severity, 0))
    return EvaluationResult(max_severity(m.severity for m in matches), matches)


# --------------------------------------------------------------------------- facts
def build_checkin_facts(answers: dict, previous_answers: dict | None = None, context: dict | None = None) -> dict:
    """Normalize raw check-in answers + history into the fact vocabulary used by protocols."""
    previous_answers = previous_answers or {}
    context = context or {}
    facts: dict[str, Any] = {}

    def num(key):
        v = answers.get(key)
        try:
            return float(v) if v is not None and v != "" else None
        except (TypeError, ValueError):
            return None

    facts["pain_score"] = num("pain_score")
    facts["pain_trend"] = answers.get("pain_trend")
    prev_pain = previous_answers.get("pain_score")
    if facts["pain_score"] is not None and prev_pain is not None:
        try:
            facts["pain_delta"] = facts["pain_score"] - float(prev_pain)
        except (TypeError, ValueError):
            facts["pain_delta"] = None
    else:
        facts["pain_delta"] = None
    # Pain is "worsening" if the patient says so, or it rose ≥2 points since last check-in.
    facts["pain_worsening"] = bool(facts["pain_trend"] == "WORSE" or (facts["pain_delta"] or 0) >= 2)

    temp = num("temperature")
    unit = (answers.get("temperature_unit") or "F").upper()
    if temp is not None and unit == "C":
        temp = round(temp * 9 / 5 + 32, 1)
    facts["temperature_f"] = temp

    facts["wound_appearance"] = answers.get("wound_appearance")
    facts["wound_redness"] = answers.get("wound_appearance") in ("MORE_RED", "RED_AND_WARM")
    facts["wound_drainage"] = answers.get("wound_appearance") in ("DRAINAGE", "PUS")
    facts["swelling"] = answers.get("swelling")
    facts["mobility"] = answers.get("mobility")
    facts["walking_minutes"] = num("walking_minutes")
    facts["medication_adherence"] = answers.get("medication_adherence")
    symptoms = answers.get("new_symptoms") or []
    if isinstance(symptoms, str):
        symptoms = [symptoms]
    facts["new_symptoms"] = [s for s in symptoms if s and s != "NONE"]
    facts["has_concern_text"] = bool((answers.get("concern") or "").strip())

    # Context facts computed by the caller from history.
    facts["consecutive_missed_checkins"] = context.get("consecutive_missed_checkins", 0)
    facts["missed_doses_48h"] = context.get("missed_doses_48h", 0)
    facts["recovery_day"] = context.get("recovery_day")
    return facts
