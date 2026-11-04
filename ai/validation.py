"""Post-generation response validation. An LLM answer is only shown if it passes.

Checks:
  * well-formed JSON matching the schema
  * cites only sources that were actually provided
  * contains no diagnosis / dosing / medication-change language
  * every number in the answer appears in the cited sources (no invented thresholds)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_FORBIDDEN = [
    (r"\byou (likely|probably|may|might|could) have\b|\bsounds like (an? )?(infection|clot|dvt)\b|"
     r"\byou (have|are suffering from) (an? )?(infection|clot|dvt|complication)", "diagnosis"),
    (r"\b(increase|decrease|double|raise|lower|reduce|adjust|change) (your |the )?(dose|dosage)\b|"
     r"\btake (an? )?(extra|additional|double|second) (dose|pill|tablet)", "dose change"),
    (r"\bstop taking\b|\bstart taking\b", "medication start/stop"),
    (r"\bi (am|'m) (a|your) (doctor|physician|nurse|pharmacist)\b", "impersonation"),
    (r"\bignore (your|the) (care team|doctor|surgeon)", "undermining care team"),
]


@dataclass
class ValidationResult:
    ok: bool
    answerable: bool
    answer: str
    source_ids: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def validate_answer(raw_text: str, sources: list[dict]) -> ValidationResult:
    try:
        data = json.loads(raw_text)
        answerable = bool(data["answerable"])
        answer = str(data.get("answer") or "").strip()
        source_ids = [str(s) for s in data.get("source_ids") or []]
    except (json.JSONDecodeError, KeyError, TypeError):
        return ValidationResult(False, False, "", [], ["malformed_output"])

    if not answerable:
        return ValidationResult(True, False, "", [], [])
    issues: list[str] = []
    by_id = {s["id"]: s for s in sources}
    if not answer:
        issues.append("empty_answer")
    if not source_ids:
        issues.append("no_citation")
    unknown = [sid for sid in source_ids if sid not in by_id]
    if unknown:
        issues.append(f"unknown_sources:{','.join(unknown)}")
    for pattern, label in _FORBIDDEN:
        if re.search(pattern, answer, re.I):
            issues.append(f"forbidden_content:{label}")
    cited_text = " ".join(by_id[s]["content"] + " " + by_id[s]["section"] for s in source_ids if s in by_id)
    invented = _numbers(answer) - _numbers(cited_text)
    if invented:
        issues.append(f"ungrounded_numbers:{','.join(sorted(invented))}")
    return ValidationResult(not issues, True, answer, [s for s in source_ids if s in by_id], issues)
