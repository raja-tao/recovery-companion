# Safety & Guardrails

**Positioning:** Recovery Companion and Care Navigation Assistant — *not* an AI doctor.
It never diagnoses, prescribes, changes medication or creates unsupported medical guidance. When appropriate it says:

> "I can help you understand your approved recovery instructions, but I can't diagnose your condition or change
> your treatment. Please contact your care team."

## Layers

| # | Layer | Where | Deterministic |
|---|---|---|---|
| 1 | Warning protocols (surgeon-approved, versioned) evaluate every check-in | `rules/engine.py` | ✔ |
| 2 | Safety & intent classifier on every assistant message, before retrieval/LLM | `rules/safety.py` | ✔ |
| 3 | Emergency path: template + RED alert, LLM never called | `agents/orchestrator.py::_emergency` | ✔ |
| 4 | Medication safety: verbatim approved guidance or refuse + doctor task | `agents/medication_safety.py` | ✔ |
| 5 | Retrieval restricted to approved, active, in-date content | `rag/retrieval.py` | ✔ |
| 6 | Constrained generation (system prompt + JSON schema + untrusted-input tagging) | `ai/prompts.py` | LLM |
| 7 | Response validation (citations, grounded numbers, forbidden language) + safe fallback | `ai/validation.py` | ✔ |
| 8 | Human in the loop: alerts with SLA, escalation to the doctor (surgeon) | `services/alerts.py` | ✔ |
| 9 | Full audit of request, sources, model, prompt version, response, classification, alert | `services/audit.py` | ✔ |

## Safety classification (assistant)

| Level | Examples | Handling |
|---|---|---|
| **RED** | chest pain, trouble breathing, heavy bleeding, fainting, stroke signs, coughing blood, severe allergic reaction, self-harm | 911 guidance shown immediately; RED `AI-RED-EMERGENCY` alert to nurses (15 min, SMS + in-app); no LLM |
| **AMBER** | worsening pain, fever, redness, drainage, swelling; any dosing / missed-dose question; diagnosis requests | Nurse review (`AI-AMBER-SYMPTOM`, 4 h) or doctor task (`AI-MED-DOSE-QUESTION`, 4 h); approved guidance may still be shown |
| **GREEN** | "What exercises are in my plan?", "Can I shower?" | RAG + validated, cited answer |

Negation is handled ("no chest pain, just wondering…" is not RED). Classifier patterns are conservative by design:
a false positive costs a nurse review; a false negative is the failure to avoid.

## Intents & routing

| Intent | Response |
|---|---|
| `EMERGENCY` | emergency template + RED alert |
| `DOSE_CHANGE` (more/less/double/stop/switch, "what dose", "how many mg", "can I take X with Y") | refuse + doctor task — even if wrapped in role-play or instruction override |
| `MISSED_DOSE` | approved `missed_dose_guidance` for the unambiguously identified medication, verbatim, with approver; otherwise refuse + doctor task |
| `DIAGNOSIS_REQUEST` | standard limitation statement (+ nurse review if symptoms) |
| `SYMPTOM_REPORT` | nurse review alert + relevant approved guidance |
| `PROMPT_INJECTION` (ignore instructions, system prompt, "you are now a doctor"…) | refuse to change behavior; flagged in audit |
| `RECOVERY_QUESTION` / `MEDICATION_QUESTION` | approved-content RAG; refuse + task if not found |

## Alert protocols (seeded, illustrative, synthetic)

| Rule | Severity | Condition | Response |
|---|---|---|---|
| RED-EMERGENCY-SYMPTOMS | RED | new symptom ∈ {chest pain, SOB, confusion, heavy bleeding} | 15 min, 911 message |
| RED-FEVER | RED | temperature ≥ 101.0 °F | 15 min |
| RED-PAIN-WORSENING | RED | pain ≥ 7 AND worsening (patient says worse OR +2 vs last check-in) | 15 min |
| RED-INFECTION-COMBO | RED | (wound redness OR drainage) AND temperature ≥ 100.4 °F | 15 min |
| RED-CALF-PAIN | RED | calf pain/swelling | 15 min |
| AMBER-PAIN-INCREASING | AMBER | 4 ≤ pain < 7 AND worsening | 4 h |
| AMBER-LOW-GRADE-TEMP | AMBER | 100.4 ≤ temp < 101.0 °F | 4 h |
| AMBER-WOUND-CHANGE | AMBER | any incision change | 4 h |
| AMBER-SWELLING-WORSE / AMBER-MOBILITY / AMBER-GI-SYMPTOMS | AMBER | swelling worse / unable to get up / GI or numbness | 4 h–24 h |
| AMBER-MED-ADHERENCE | AMBER | missed doses reported OR ≥ 2 missed in 48 h | 24 h |
| AMBER-MISSED-CHECKINS | AMBER | ≥ 2 consecutive missed check-ins (scheduler) | 24 h |

These thresholds are **placeholders for a POC on synthetic data**. Real thresholds must come from the clinical
owners and be approved in the protocol workflow (a DRAFT v2 of RED-FEVER demonstrates that unapproved changes have
no effect).

## Fixed system policy for AI-originated work items

| Policy id | Severity | Team | Response |
|---|---|---|---|
| AI-RED-EMERGENCY | RED | Nurse | 15 min |
| AI-AMBER-SYMPTOM | AMBER | Nurse | 4 h |
| AI-MED-DOSE-QUESTION | AMBER | Doctor | 4 h |
| AI-MED-QUESTION | INFO | Doctor | 24 h |
| AI-UNANSWERED | INFO | Nurse | 24 h |
| APPT-TRANSPORT | AMBER | Coordinator (nurse role) | 24 h |
| MED-ADHERENCE-MISSED | AMBER | Nurse | 24 h |
| INT-MED-RECONCILE | INFO | Doctor | 24 h |
| INT-RX-NOT-FILLED | AMBER | Nurse (outreach) | 8 h |
| MOOD-SAFETY (crisis / self-harm language in a mood note) | RED | Nurse | 15 min |
| MOOD-LOW-TREND (low/bad mood on 3 days within 5) | AMBER | Nurse | 24 h |
| MOOD-CONTACT-REQUEST | INFO | Nurse | 24 h |
| APPT-TRANSPORT-UNCONFIRMED (no ride answer 12 h before) | INFO | Coordinator (nurse role) | 4 h |

## Containment test

`tests/safety/test_assistant_safety.py::test_llm_cannot_override_safety_or_inject_ungrounded_text` plugs in a
malicious LLM that returns invented timelines, a diagnosis and a dose change with a valid-looking citation. The
validator rejects it, the deterministic extractive answer is returned instead, the issue is logged, and an
emergency message still never reaches the LLM.

## Residual risks / next steps

- Regex classification can miss unusual phrasing → add an LLM *second opinion* that may only **raise** severity,
  plus clinician review of AMBER/RED transcripts.
- Non-English input is not supported in the POC.
- Clinical owners must validate all content, thresholds and response times before any pilot.
