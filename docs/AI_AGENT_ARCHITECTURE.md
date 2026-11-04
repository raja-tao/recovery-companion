# AI Agent Architecture

The system is a **controlled agentic workflow**: Python code decides the path; agents are well-scoped components;
the LLM is only asked to *phrase* an answer from approved text it is handed. Clinical safety decisions are
deterministic and happen before and around any model call.

## Agents / components

| Agent | File | Deterministic? | Responsibility |
|---|---|---|---|
| Intake / Context | `agents/context.py` | ✔ | Patient, active episode, recovery day & phase, approved plan version, active meds |
| Recovery Plan | `agents/recovery_plan.py` | ✔ | Plan versions, approval (4-eyes: approver ≠ author), task generation, phases |
| Check-in Analysis | `agents/checkin_analysis.py` | ✔ | Validate answers vs configured questions → facts (trend, history) → rules engine → persist → alert |
| Knowledge Retrieval | `agents/knowledge.py` | ✔ | Approved/active/in-date chunks via `rag/retrieval.py` |
| Patient Education | `agents/knowledge.py` | LLM (bounded) | Grounded answer from supplied sources (JSON schema), then validation; extractive fallback |
| Medication Safety | `agents/medication_safety.py` | ✔ | Identify medication; verbatim approved missed-dose guidance or refuse + doctor task; dose changes always refused |
| Alert / Escalation | `agents/alerting.py` | ✔ | Rule matches / AI policy → alerts with severity, SLA, team; one alert per check-in |
| Care-Team Summary | `agents/care_team_summary.py` | ✔ | Fact-only handoff bullets for nurses (no inference) |
| Orchestrator | `agents/orchestrator.py` | ✔ (routing) | The pipeline below + persistence + audit |

## Orchestrator pipeline (`POST /api/ai/chat`)

```
question
 → Intake/Context Agent
 → Safety & intent classifier (rules/safety.py)            GREEN | AMBER | RED + intent + flags
 ├─ RED (emergency)        → 911 template, RED alert (15 min, nurse). NO LLM. stop.
 ├─ DOSE_CHANGE            → refuse (standard limitation text) + doctor task (AMBER, 4 h). stop.
 ├─ MISSED_DOSE            → Medication Safety Agent:
 │                             identified med has approved guidance → return it verbatim + citation
 │                             else (none / ambiguous)              → refuse + doctor task
 ├─ PROMPT_INJECTION only  → refuse override attempt. stop.
 ├─ DIAGNOSIS_REQUEST      → "I can't diagnose…" (+ nurse review if symptoms mentioned)
 ├─ SYMPTOM_REPORT         → nurse review alert (AMBER) + any relevant approved guidance
 └─ RECOVERY / MEDICATION question
      → Knowledge Retrieval Agent (approved, active, in-date, procedure-matched)
      → none found → "I couldn't find this in your approved recovery instructions…" + care-team task
      → ModelRouter → provider (Claude default) with JSON-schema output
      → Response validation (citations ⊆ sources, numbers grounded, no diagnosis/dose language)
          fail → deterministic extractive answer from the same sources (or refuse)
      → Citations (document, version, section, authority, approver, score, excerpt)
 → persist patient + assistant messages (encrypted) with metadata
 → audit: user, role, patient, request, retrieved docs, model, prompt version, response,
          safety classification, rules/flags, alert generated, route, latency, tokens
```

The LLM never: chooses the safety level, creates/suppresses alerts, selects sources, sees other patients' data,
or receives unapproved text.

## ModelRouter (`ai/router.py`)

Inputs: `task`, `risk`, `capability`.

| Task / risk | Route |
|---|---|
| `RED` risk or `EMERGENCY` | **No LLM** — rules engine, templated guidance, human escalation |
| `PATIENT_CLINICAL_QA` | Configured provider (Claude default) + RAG + validation; extractive fallback if unavailable/failed |
| Low-risk (e.g. `CARE_TEAM_SUMMARY`) | Any configured provider (POC keeps the summary deterministic) |

## LLM providers (`ai/providers/`)

```
LLMProvider (available(), generate(LLMRequest) -> LLMResponse)
├── ClaudeProvider      anthropic SDK · model claude-opus-5-5 · output_config.effort=low · JSON schema output
├── OpenAIProvider      openai SDK · json_object response format (optional)
├── OllamaProvider      local REST /api/chat with JSON schema format (optional)
└── ExtractiveProvider  deterministic, offline: quotes the best-matching approved sentences
```

Select with `LLM_PROVIDER`. A Claude `refusal` stop reason, API error, timeout or invalid JSON all degrade to the
extractive provider — never to an unvalidated answer.

## Prompting

`ai/prompts.py`, versioned (`PROMPT_VERSION = recovery-qa-v1.2`, stored on every message and audit event).
The system prompt restricts the model to the supplied `<source>` blocks, forbids diagnosis/dosing/invented numbers,
and marks `<patient_question>` as untrusted input that cannot change rules or format. Output is constrained to
`{answerable: bool, answer: string, source_ids: string[]}`.

## Why not an autonomous tool-calling agent?

Clinical safety requires that the set of possible actions and their triggers be enumerable, testable and auditable.
A free-form agent would make "can the model skip the rules engine?" a probabilistic question. Here it is a code-path
question with a test (`test_llm_cannot_override_safety_or_inject_ungrounded_text`).
