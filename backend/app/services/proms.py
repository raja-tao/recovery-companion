"""Patient-reported outcome measures (PROMs) collected in the app.

HOOS JR (hip replacement) and KOOS JR (knee replacement) are the short-form surveys CMS accepts for
joint-replacement quality reporting. Both are free to use (Hospital for Special Surgery); verify the
item wording against the official instrument before production use.

Scoring here is the raw sum (0 = no problems … 4 per item). The official 0–100 interval score uses
the instrument's published conversion table, which is not bundled in this POC.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PromResponse

SEVERITY = ["None", "Mild", "Moderate", "Severe", "Extreme"]

INSTRUMENTS: dict[str, dict] = {
    "KOOS_JR": {
        "title": "KOOS JR — knee survey", "procedures": ["TKA"], "loinc": "72093-0",
        "intro": "Think about your knee over the last week.",
        "items": [
            ("stiffness_morning", "Stiffness", "How severe is your knee stiffness after first waking in the morning?"),
            ("pain_twisting", "Pain", "Knee pain while twisting or pivoting on your knee"),
            ("pain_straightening", "Pain", "Knee pain while straightening your knee fully"),
            ("pain_stairs", "Pain", "Knee pain going up or down stairs"),
            ("pain_standing", "Pain", "Knee pain standing upright"),
            ("function_rising", "Function", "Difficulty rising from sitting"),
            ("function_bending", "Function", "Difficulty bending to the floor or picking up an object"),
        ],
    },
    "HOOS_JR": {
        "title": "HOOS JR — hip survey", "procedures": ["THA"], "loinc": "72095-5",
        "intro": "Think about your hip over the last week.",
        "items": [
            ("pain_stairs", "Pain", "Hip pain going up or down stairs"),
            ("pain_uneven", "Pain", "Hip pain walking on an uneven surface"),
            ("function_rising", "Function", "Difficulty rising from sitting"),
            ("function_bending", "Function", "Difficulty bending to the floor or picking up an object"),
            ("function_lying", "Function", "Difficulty lying in bed (turning over, keeping your hip position)"),
            ("function_sitting", "Function", "Difficulty sitting"),
        ],
    },
}

# Collection windows inside the 30-day program (recovery days, inclusive).
TIMEPOINTS = {"POSTOP_2W": ("2 weeks after surgery", 14, 20), "POSTOP_30D": ("30 days after surgery", 26, 30)}


def instrument_for(procedure_type: str | None) -> str | None:
    return next((k for k, v in INSTRUMENTS.items() if procedure_type in v["procedures"]), None)


def surveys_for(db: Session, patient_id, procedure_type: str | None, day: int | None) -> list[dict]:
    """Every time point for the patient's instrument with its state: UPCOMING | DUE | COMPLETED | MISSED."""
    key = instrument_for(procedure_type)
    if not key or day is None:
        return []
    done = {r.timepoint: r for r in db.scalars(select(PromResponse).where(
        PromResponse.patient_id == patient_id, PromResponse.instrument == key))}
    out = []
    for tp, (label, start, end) in TIMEPOINTS.items():
        r = done.get(tp)
        state = ("COMPLETED" if r else "DUE" if start <= day <= end else "UPCOMING" if day < start else "MISSED")
        out.append({"instrument": key, "title": INSTRUMENTS[key]["title"], "timepoint": tp, "label": label,
                    "window": [start, end], "state": state,
                    "raw_score": r.raw_score if r else None, "max_score": r.max_score if r else None,
                    "completed_at": r.completed_at.isoformat() if r else None})
    return out


def definition(key: str) -> dict:
    inst = INSTRUMENTS[key]
    return {"instrument": key, "title": inst["title"], "intro": inst["intro"], "options": SEVERITY,
            "items": [{"id": i, "domain": d, "text": t} for i, d, t in inst["items"]]}


def score(key: str, answers: dict) -> tuple[int, int]:
    ids = [i for i, _, _ in INSTRUMENTS[key]["items"]]
    missing = [i for i in ids if i not in answers]
    if missing:
        raise ValueError(f"Missing answers: {', '.join(missing)}")
    if any(not isinstance(answers[i], int) or not 0 <= answers[i] <= 4 for i in ids):
        raise ValueError("Each answer must be 0–4")
    return sum(answers[i] for i in ids), 4 * len(ids)


def window_contains(tp: str, day: int) -> bool:
    _, start, end = TIMEPOINTS[tp]
    return start <= day <= end


def questionnaire_response(r: PromResponse, mrn: str, completed: date | None = None) -> dict:
    inst = INSTRUMENTS[r.instrument]
    texts = {i: t for i, _, t in inst["items"]}
    return {
        "resourceType": "QuestionnaireResponse", "status": "completed",
        "identifier": {"system": "urn:recovery-companion:prom", "value": str(r.id)},
        "questionnaire": f"urn:recovery-companion:questionnaire:{r.instrument}",
        "subject": {"identifier": {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                                       "code": "MR"}]}, "value": mrn}},
        "authored": r.completed_at.isoformat(),
        "item": [{"linkId": i, "text": texts[i], "answer": [{"valueCoding": {"code": str(v), "display": SEVERITY[v]}}]}
                 for i, v in r.answers.items()]
                + [{"linkId": "raw_score", "text": f"{r.instrument} raw score ({r.timepoint})",
                    "answer": [{"valueInteger": r.raw_score}]}],
    }
