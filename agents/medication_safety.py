"""Medication Safety Agent.

Hard rules (not configurable by the LLM):
  * Never produce dosing advice or dose/schedule changes.
  * Missed-dose questions: return ONLY the approved `missed_dose_guidance` text
    for the identified medication, verbatim. If there is none, or the medication
    can't be identified unambiguously, refuse and create a task for the doctor.
  * Dose-change requests: always refuse and create a task for the doctor (only the
    doctor decides treatment).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import Medication

_INDICATION_HINTS = {
    "pain": ["pain", "painkiller", "pain killer", "opioid", "oxy", "hydrocodone", "tylenol", "acetaminophen",
             "ibuprofen", "celecoxib"],
    "blood clot prevention": ["blood thinner", "clot", "anticoagulant", "apixaban", "eliquis", "enoxaparin",
                              "lovenox", "aspirin", "shot"],
    "infection prevention": ["antibiotic", "cephalexin", "keflex", "infection"],
    "constipation": ["stool softener", "laxative", "constipation", "docusate", "senna", "colace"],
    "nausea": ["nausea", "ondansetron", "zofran", "sick to my stomach"],
}

NO_GUIDANCE_MESSAGE = (
    "Your recovery instructions don't say what to do after a missed dose of this medication. "
    "Please don't take extra medicine on your own — contact your care team. "
    "I've sent your question to your doctor."
)
DOSE_CHANGE_MESSAGE = (
    "I can't recommend taking more, less, or a different dose of any medication. "
    "I can help you understand your approved recovery instructions, but I can't diagnose your condition or change "
    "your treatment. Please contact your care team. I've sent your question to your doctor so they can follow up."
)


@dataclass
class MedicationMatch:
    medication: Medication | None
    ambiguous: bool


def identify_medication(question: str, medications: list[Medication]) -> MedicationMatch:
    q = question.lower()
    by_name = [m for m in medications if m.name.lower().split()[0] in q]
    if len(by_name) == 1:
        return MedicationMatch(by_name[0], False)
    candidates = []
    for m in medications:
        hints = []
        for indication, words in _INDICATION_HINTS.items():
            if indication.split()[0] in m.indication.lower():
                hints = words
        if any(re.search(r"\b" + re.escape(w), q) for w in hints):
            candidates.append(m)
    if len(candidates) == 1:
        return MedicationMatch(candidates[0], False)
    return MedicationMatch(None, len(candidates) > 1 or len(by_name) > 1)


def medication_sources(medications: list[Medication]) -> list[dict]:
    """Patient's prescribed medication instructions as approved retrieval sources (no dosing changes)."""
    out = []
    for i, m in enumerate(medications):
        content = f"{m.name} ({m.dose_text}) — {m.frequency}. Used for {m.indication}. {m.instructions}".strip()
        out.append({
            "id": f"M{i + 1}", "title": f"Your medication list: {m.name}", "section": "Prescribed instructions",
            "content": content,
            "citation": {"document_id": None, "document_key": f"medication:{m.id}", "title": f"Medication record: {m.name}",
                         "version": 1, "section": "Prescribed instructions", "authority": "SURGEON_APPROVED",
                         "doc_type": "MEDICATION_RECORD", "approved_by": m.prescriber, "score": 1.0,
                         "excerpt": content[:400]},
        })
    return out
