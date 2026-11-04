"""Lightweight text normalization shared by the hashing embedder and the lexical re-ranker."""
from __future__ import annotations

import re

STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
few for from further had hadn't has hasn't have haven't having he her here hers herself him himself his how
i i'm i've if in into is isn't it it's its itself just let's me more most my myself no nor not now of off
on once only or other ought our ours ourselves out over own same she should shouldn't so some such than that
the their theirs them themselves then there these they this those through to too under until up very was we
were what when where which while who whom why will with won't would you your yours yourself yourselves
ok okay please tell know want need say says said plan recovery instructions instruction today also get
still may might much many really thing things like ll ve re d s t go going allowed day days week weeks time long
soon start starting begin begins usually normally normal take taking
""".split())

# Canonical forms so patient wording matches clinical wording.
SYNONYMS = {
    "driving": "drive", "drove": "drive", "car": "drive", "steering": "drive",
    "bath": "shower", "bathe": "shower", "bathing": "shower", "showering": "shower", "wash": "shower",
    "tub": "soak", "hottub": "soak", "swim": "soak", "swimming": "soak", "pool": "soak", "soaking": "soak",
    "walking": "walk", "walks": "walk", "stroll": "walk", "steps": "walk",
    "pt": "physiotherapy", "physio": "physiotherapy", "therapy": "physiotherapy", "therapist": "physiotherapy",
    "physical": "physiotherapy",
    "sleeping": "sleep", "lie": "sleep", "lying": "sleep", "bed": "sleep", "pillow": "sleep",
    "position": "position", "positions": "position",
    "swollen": "swell", "swelling": "swell", "puffy": "swell",
    "incision": "wound", "dressing": "wound", "bandage": "wound", "stitches": "wound", "staples": "wound",
    "scar": "wound", "cut": "wound",
    "medicine": "medication", "meds": "medication", "pills": "medication", "pill": "medication",
    "tablet": "medication", "drugs": "medication",
    "fluids": "hydration", "water": "hydration", "drink": "hydration", "drinking": "hydration",
    "hydrate": "hydration",
    "eat": "diet", "eating": "diet", "food": "diet", "meal": "diet", "meals": "diet", "nutrition": "diet",
    "exercises": "exercise", "workout": "exercise", "stretches": "exercise",
    "work": "work", "job": "work", "office": "work",
    "sex": "intimacy", "sexual": "intimacy",
    "stairs": "stair", "staircase": "stair",
    "fever": "temperature", "temp": "temperature",
    "constipated": "constipation", "bowel": "constipation", "poop": "constipation",
    "lift": "lift", "lifting": "lift", "carry": "lift", "heavy": "lift",
    "flying": "travel", "fly": "travel", "plane": "travel", "trip": "travel", "flight": "travel",
    "alcohol": "alcohol", "beer": "alcohol", "wine": "alcohol",
    "crutches": "walker", "cane": "walker",
    "ice": "ice", "icing": "ice", "cold": "ice",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def stem(word: str) -> str:
    w = word
    if len(w) <= 3:
        return w
    for suf, rep in (("ies", "y"), ("ing", ""), ("edly", ""), ("ed", ""), ("ly", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "s" and w.endswith("ss"):
                continue
            if suf == "es" and not re.search(r"(sh|ch|x|z|ss)es$", w):
                continue
            w = w[: -len(suf)] + rep
            if suf in ("ing", "ed") and len(w) >= 4 and w[-1] == w[-2] and w[-1] not in "lsz":
                w = w[:-1]  # swimming -> swim
            break
    return w


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


_PHRASES = [
    (re.compile(r"\b(go|get|going|getting|come|coming) back to\b"), "return to"),
    (re.compile(r"\bphysical therapy\b"), "physiotherapy"),
    (re.compile(r"\bhot tub\b"), "soak"),
]


def content_terms(text: str) -> list[str]:
    """Stopword-free, synonym-canonicalized, stemmed terms."""
    text = (text or "").lower()
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    out = []
    for tok in tokenize(text):
        tok = tok.replace("'", "")
        if tok in STOPWORDS or len(tok) < 2:
            continue
        canon = SYNONYMS.get(tok)
        if canon is None:
            s = stem(tok)
            canon = SYNONYMS.get(s, s)
        out.append(canon)
    return out


def approx_tokens(text: str) -> int:
    return int(len(tokenize(text)) * 1.3) + 1
