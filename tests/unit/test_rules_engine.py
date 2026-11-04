"""Deterministic alert-engine tests (no DB, no LLM)."""
import pytest

from app.seed import PROTOCOLS
from rules.engine import (
    ProtocolSpec, RuleDefinitionError, build_checkin_facts, evaluate, evaluate_protocols, max_severity,
    validate_condition,
)

SPECS = [ProtocolSpec(rule_id=r, name=n, severity=s, category=c, condition=cond, response_minutes=m, assigned_team=t)
         for r, n, s, c, cond, m, t, _msg, _d in PROTOCOLS if c != "MISSED_CHECKIN"]
BASE = {"pain_score": 3, "pain_trend": "BETTER", "temperature": 98.4, "wound_appearance": "HEALING_WELL",
        "swelling": "SAME", "mobility": "WITH_AID", "medication_adherence": "ALL", "new_symptoms": ["NONE"]}


def run(answers, prev=None, ctx=None):
    return evaluate_protocols(SPECS, build_checkin_facts(BASE | answers, prev, ctx))


def rules(res):
    return {m.rule_id for m in res.matches}


def test_normal_is_green():
    res = run({})
    assert res.risk_level == "GREEN" and res.matches == []


def test_pain_increasing_amber():
    res = run({"pain_score": 5, "pain_trend": "WORSE"})
    assert res.risk_level == "AMBER" and rules(res) == {"AMBER-PAIN-INCREASING"}


def test_pain_delta_counts_as_worsening_even_if_patient_says_same():
    res = run({"pain_score": 6, "pain_trend": "SAME"}, prev={"pain_score": 3})
    assert "AMBER-PAIN-INCREASING" in rules(res)


def test_severe_worsening_pain_red_not_amber():
    res = run({"pain_score": 8, "pain_trend": "WORSE"})
    assert res.risk_level == "RED"
    assert "RED-PAIN-WORSENING" in rules(res) and "AMBER-PAIN-INCREASING" not in rules(res)


def test_severe_but_improving_pain_not_red():
    assert run({"pain_score": 7, "pain_trend": "BETTER"}).risk_level == "GREEN"


@pytest.mark.parametrize("temp,expected", [(100.3, "GREEN"), (100.4, "AMBER"), (100.9, "AMBER"), (101.0, "RED"),
                                           (101.8, "RED")])
def test_temperature_thresholds(temp, expected):
    assert run({"temperature": temp}).risk_level == expected


def test_celsius_is_converted():
    res = run({"temperature": 38.6, "temperature_unit": "C"})  # 101.5 F
    assert "RED-FEVER" in rules(res)


def test_brd_example_pain_fever_redness_is_red_with_evidence():
    res = run({"pain_score": 7, "pain_trend": "WORSE", "temperature": 101.8, "wound_appearance": "MORE_RED"})
    assert res.risk_level == "RED"
    assert {"RED-FEVER", "RED-PAIN-WORSENING", "RED-INFECTION-COMBO"} <= rules(res)
    fever = next(m for m in res.matches if m.rule_id == "RED-FEVER")
    assert fever.evidence == [{"fact": "temperature_f", "op": ">=", "threshold": 101.0, "actual": 101.8}]
    assert res.matches[0].severity == "RED"  # sorted by severity


def test_combination_rule_needs_both_parts():
    assert "RED-INFECTION-COMBO" not in rules(run({"wound_appearance": "MORE_RED"}))
    assert "RED-INFECTION-COMBO" in rules(run({"wound_appearance": "DRAINAGE", "temperature": 100.5}))


def test_emergency_symptoms():
    res = run({"new_symptoms": ["CHEST_PAIN"]})
    assert res.risk_level == "RED" and "RED-EMERGENCY-SYMPTOMS" in rules(res)


def test_medication_adherence_from_history_context():
    assert "AMBER-MED-ADHERENCE" in rules(run({}, ctx={"missed_doses_48h": 2}))
    assert "AMBER-MED-ADHERENCE" in rules(run({"medication_adherence": "MISSED_SOME"}))


def test_missing_values_never_match():
    facts = build_checkin_facts({})
    assert evaluate_protocols(SPECS, facts).risk_level == "GREEN"


def test_dsl_operators():
    f = {"a": 5, "b": "X", "c": ["P", "Q"], "d": True}
    assert evaluate({"fact": "a", "op": ">", "value": 4}, f)[0]
    assert evaluate({"fact": "b", "op": "in", "value": ["X", "Y"]}, f)[0]
    assert evaluate({"fact": "c", "op": "contains", "value": "Q"}, f)[0]
    assert evaluate({"not": {"fact": "d", "op": "is_false"}}, f)[0]
    assert evaluate({"any": [{"fact": "a", "op": "<", "value": 1}, {"fact": "d", "op": "is_true"}]}, f)[0]
    assert not evaluate({"all": [{"fact": "a", "op": "<", "value": 1}, {"fact": "d", "op": "is_true"}]}, f)[0]


def test_invalid_rule_definitions_rejected():
    for bad in ({"fact": "a", "op": "~=", "value": 1}, {"all": []}, {"foo": 1}):
        with pytest.raises(RuleDefinitionError):
            validate_condition(bad)


def test_procedure_filter():
    spec = ProtocolSpec("X", "x", "RED", {"fact": "a", "op": "==", "value": 1}, 15, procedure_type="THA")
    assert evaluate_protocols([spec], {"a": 1}, "TKA").risk_level == "GREEN"
    assert evaluate_protocols([spec], {"a": 1}, "THA").risk_level == "RED"


def test_max_severity():
    assert max_severity(["AMBER", "RED", "INFO"]) == "RED"
    assert max_severity([]) == "GREEN"
