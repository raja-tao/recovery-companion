"""Deterministic safety & intent classifier for patient free text.

Runs BEFORE any retrieval or LLM call. The LLM cannot lower the level assigned
here (see agents/orchestrator.py). Patterns are intentionally conservative:
false positives route to a human, false negatives are the failure we avoid.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- RED: emergency
_RED_PATTERNS: list[tuple[str, str]] = [
    (r"chest (pain|pressure|tightness)|pain in (my )?chest|crushing (pain|pressure)", "chest pain"),
    (r"(difficulty|trouble|hard|struggling|can'?t|cannot|unable to) (to )?breath|short(ness)? of breath|"
     r"breathless|gasping|not breathing", "difficulty breathing"),
    (r"cough(ing)? (up )?blood|vomit(ing)? blood|blood in (my )?vomit", "coughing/vomiting blood"),
    (r"(heavy|severe|uncontroll\w*|won'?t stop|soaking|gushing|a lot of) (bleeding|blood)|"
     r"bleeding (heavily|a lot|won'?t stop|through)", "severe bleeding"),
    (r"pass(ed)? out|faint(ed|ing)|unconscious|unresponsive|collapsed", "fainting / loss of consciousness"),
    (r"(face|arm|leg|smile) (is )?(drooping|numb|weak)|slurred speech|stroke", "stroke symptoms"),
    (r"seizure|convuls", "seizure"),
    (r"suicid|kill myself|end my life|want to die|self[- ]harm|hurt myself", "self-harm risk"),
    (r"(severe|sudden|worst).{0,20}(head ?ache)", "sudden severe headache"),
    (r"(calf|leg).{0,30}(swollen|swelling|hot|red).{0,40}(short of breath|breath)", "possible clot symptoms"),
    (r"confus(ed|ion)|can'?t wake|very drowsy|hard to wake", "confusion / altered alertness"),
    (r"allergic reaction|throat (is )?(closing|swelling)|swollen (tongue|lips|throat)|anaphyla", "severe allergic reaction"),
    (r"\b(emergency|911|ambulance)\b", "emergency mentioned"),
]

# --------------------------------------------------------------------------- AMBER: concerning symptoms
_AMBER_PATTERNS: list[tuple[str, str]] = [
    (r"pain.{0,25}(worse|worsening|increas|getting bad|more)|(worse|increasing|more) pain", "worsening pain"),
    (r"\bfever\b|temperature|chills|feel(ing)? hot|sweat", "fever / chills"),
    (r"\bred(ness|der)?\b|warm to (the )?touch|hot to (the )?touch", "redness / warmth"),
    (r"swell|swollen", "swelling"),
    (r"drain|ooz|pus|discharge|leaking|smell", "wound drainage"),
    (r"incision.{0,20}(open|split|gap)|stitches.{0,20}(came|out|open)|staples.{0,20}(out|open)", "wound opening"),
    (r"nause|vomit|throw(ing)? up|can'?t keep (food|anything) down", "nausea / vomiting"),
    (r"constipat|haven'?t (had a )?bowel|no bowel", "constipation"),
    (r"dizz|lighthead", "dizziness"),
    (r"numb|tingl", "numbness / tingling"),
    (r"can'?t (walk|stand|bear weight)|unable to (walk|stand)", "unable to walk"),
    (r"\bbleed", "bleeding"),
    (r"can'?t (sleep|eat)|not eating|not drinking", "poor intake / sleep"),
]

# --------------------------------------------------------------------------- intents
_INJECTION = re.compile(
    r"ignore (all |any |your |the )?(previous|prior|above|earlier)? ?(instructions|rules|prompts?)|"
    r"disregard (your|the|all) (instructions|rules|guidelines)|forget (your|all|the) (rules|instructions)|"
    r"system prompt|you are now|act as (a |an )?(doctor|physician|pharmacist|nurse)|pretend (you are|to be)|"
    r"developer mode|jailbreak|\bDAN\b|override (your|the) (rules|safety)|new instructions:|"
    r"reveal (your|the) (prompt|instructions)|without (any )?(restrictions|safety)", re.I)

_DOSE_CHANGE = re.compile(
    r"(take|have|use) (two|2|three|3|double|extra|another|more|an extra|a double)\b|double (up|the|my|dose)|"
    r"(increase|decrease|raise|lower|reduce|change|adjust|up) (my |the )?(dose|dosage|medication|meds|pills?)|"
    r"(how much|how many|what dose|what dosage|which dose|how many mg|how many milligrams)|"
    r"(what|which|how much|right|correct)\b.{0,30}\b(dose|dosage)\b|\b(dose|dosage)\b.{0,20}\bshould i\b|"
    r"(stop|quit) taking|\bmg\b|milligram|overdose|can i take .{0,40}(with|and|instead)|"
    r"(dose|dosage) (should|do) i", re.I)

_MISSED_DOSE = re.compile(
    r"(forgot|forget|missed|skipped|didn'?t take|did not take|haven'?t taken|late).{0,40}"
    r"(dose|pill|tablet|med|medicine|medication|blood thinner|antibiotic|\w+ ?(ine|in|ol|en|ox|ide|one|am))|"
    r"missed (a |my )?dose", re.I)

_MEDICATION = re.compile(
    r"\b(med|meds|medicine|medication|pill|pills|tablet|dose|dosage|prescription|pharmac|refill|"
    r"oxycodone|hydrocodone|acetaminophen|tylenol|ibuprofen|advil|aspirin|apixaban|eliquis|enoxaparin|"
    r"lovenox|cephalexin|keflex|docusate|senna|ondansetron|zofran|celecoxib|antibiotic|blood thinner|"
    r"painkiller|pain killer|opioid)\b", re.I)

_DIAGNOSIS = re.compile(
    r"\bdo i have\b|\bis (this|it) (an? )?(infection|infected|clot|dvt|normal|serious|dangerous)|"
    r"what('?s| is) wrong with me|diagnos|am i (sick|infected|ok|okay|dying)|is my (wound|incision) infected|"
    r"what (illness|disease|condition) do i", re.I)

# A change verb shortly before any medication term ("stop my blood thinner",
# "increase my pain medication") is a request to change treatment.
_CHANGE_VERB = re.compile(r"\b(stop|quit|discontinue|increase|decrease|raise|lower|reduce|double|halve|change|adjust|"
                          r"switch|cut back|come off|get off|skip)\b", re.I)


def _change_near_medication(t: str) -> bool:
    for m in _CHANGE_VERB.finditer(t):
        if _MEDICATION.search(t[m.end():m.end() + 40]):
            return True
    return False


_GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|thanks|thank you)[\s!.]*$", re.I)


@dataclass
class SafetyAssessment:
    level: str  # GREEN | AMBER | RED
    intent: str  # EMERGENCY | DOSE_CHANGE | MISSED_DOSE | MEDICATION_QUESTION | DIAGNOSIS_REQUEST
    #              | SYMPTOM_REPORT | RECOVERY_QUESTION | GREETING
    flags: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    @property
    def is_emergency(self) -> bool:
        return self.level == "RED"

    def to_dict(self) -> dict:
        return {"level": self.level, "intent": self.intent, "flags": self.flags, "matched_terms": self.matched_terms}


def _negated(text: str, start: int) -> bool:
    """Very small negation check: 'no chest pain', 'not short of breath', 'denies fever'."""
    window = text[max(0, start - 18):start]
    return bool(re.search(r"\b(no|not|without|denies|never|n't)\b[\w\s]{0,10}$", window))


def classify(text: str) -> SafetyAssessment:
    t = " ".join((text or "").lower().split())
    flags: list[str] = []
    red_terms = []
    for pattern, label in _RED_PATTERNS:
        for m in re.finditer(pattern, t):
            if not _negated(t, m.start()):
                red_terms.append(label)
                break
    amber_terms = []
    for pattern, label in _AMBER_PATTERNS:
        for m in re.finditer(pattern, t):
            if not _negated(t, m.start()):
                amber_terms.append(label)
                break

    if _INJECTION.search(t):
        flags.append("PROMPT_INJECTION")

    if red_terms:
        return SafetyAssessment("RED", "EMERGENCY", flags + ["EMERGENCY_SYMPTOMS"], red_terms)

    is_med = bool(_MEDICATION.search(t))
    if (_DOSE_CHANGE.search(t) and (is_med or "PROMPT_INJECTION" in flags or "dose" in t)) or \
            (_change_near_medication(t) and not _MISSED_DOSE.search(t)):
        if _MISSED_DOSE.search(t):
            flags.append("DOSE_CHANGE_REQUESTED")
            return SafetyAssessment("AMBER", "MISSED_DOSE", flags, amber_terms)
        return SafetyAssessment("AMBER", "DOSE_CHANGE", flags + ["DOSE_CHANGE_REQUESTED"], amber_terms)
    if _MISSED_DOSE.search(t):
        return SafetyAssessment("AMBER", "MISSED_DOSE", flags, amber_terms)
    if _DIAGNOSIS.search(t):
        return SafetyAssessment("AMBER", "DIAGNOSIS_REQUEST", flags, amber_terms)
    if is_med:
        return SafetyAssessment("AMBER" if amber_terms else "GREEN", "MEDICATION_QUESTION", flags, amber_terms)
    is_question = bool(re.search(r"^(what|when|how|can|could|should|is it|may|do i|does|will|where|why)\b", t)
                       or t.rstrip().endswith("?"))
    first_person = bool(re.search(r"\b(i have|i've got|i feel|i am|i'm|i noticed|i think|my \w+ (is|are|has|feels|"
                                  r"looks|got|seems|keeps))", t))
    if amber_terms and (not is_question or first_person):
        return SafetyAssessment("AMBER", "SYMPTOM_REPORT", flags, amber_terms)
    if _GREETING.match(t):
        return SafetyAssessment("GREEN", "GREETING", flags)
    return SafetyAssessment("GREEN", "RECOVERY_QUESTION", flags, amber_terms)


EMERGENCY_MESSAGE = (
    "⚠️ Your message describes symptoms that may need emergency care. "
    "Call 911 (or your local emergency number) now, or go to the nearest emergency department. "
    "Do not wait for a reply in this app. Your care team has also been alerted."
)

STANDARD_LIMITATION = (
    "I can help you understand your approved recovery instructions, but I can't diagnose your condition "
    "or change your treatment. Please contact your care team."
)
