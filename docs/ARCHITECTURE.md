# Architecture

## Overview

```
┌─────────────────────────── Browser ───────────────────────────┐
│ React + TS + MUI SPA                                           │
│  • Patient app (mobile-first)  • Caregiver view                │
│  • Care-team console           • Admin / governance / demo     │
└───────────────┬────────────────────────────────────────────────┘
                │ HTTPS  /api/*  (JWT bearer)
┌───────────────▼──────────────┐
│ nginx (static SPA + reverse  │  security headers, CSP
│ proxy)                       │
└───────────────┬──────────────┘
┌───────────────▼──────────────────────────────────────────────────────────┐
│ FastAPI (backend/app)                                                     │
│  middleware: request-id · JSON logs · metrics · security headers · rate   │
│  limit · CORS                                                             │
│  routers: auth · patients · ai · caregiver · alerts/worklist · content ·  │
│           admin/audit/analytics · demo                                    │
│  deps: JWT → User → RBAC permission → patient_access (scope + audit)     │
│                                                                           │
│  ┌──────────────── agents/ (controlled workflow) ────────────────┐       │
│  │ Intake/Context · Recovery Plan · Check-in Analysis ·           │       │
│  │ Knowledge Retrieval · Patient Education · Medication Safety ·  │       │
│  │ Alert/Escalation · Care-Team Summary · Orchestrator            │       │
│  └───────┬───────────────┬──────────────────┬────────────────────┘       │
│   rules/ (deterministic) │ rag/ (approved-only)  ai/ (router, providers,  │
│   engine + safety        │ chunk/embed/retrieve   prompts, validation)    │
│                          │                                                │
│  services/: audit · alerts (state machine, SLA) · notifications ·         │
│             timeline · analytics · scheduler (reminders, missed, SLA)     │
└───────────────┬────────────────────────────────────┬──────────────────────┘
                │ SQLAlchemy / psycopg               │ HTTPS (optional)
┌───────────────▼──────────────┐       ┌─────────────▼─────────────────────┐
│ PostgreSQL 16 + pgvector     │       │ Claude API (default) · OpenAI ·   │
│ app data, chunks+embeddings, │       │ Ollama (local)                    │
│ append-only audit (trigger)  │       └───────────────────────────────────┘
└──────────────────────────────┘
```

## Request flow examples

**Daily check-in** → `POST /api/patients/{id}/checkins` → `patient_access` (own record) → Check-in Analysis
Agent: validate against configured questions → build facts (incl. trend vs. previous check-in, missed-dose
history) → evaluate latest APPROVED protocols → persist check-in + responses + rule results → one alert per
check-in carrying all matched rules (highest severity, strictest SLA) → notify assigned team → update patient risk →
audit. No LLM is involved.

**Assistant question** → `POST /api/ai/chat` → Orchestrator (see AI_AGENT_ARCHITECTURE.md): safety classifier →
(RED: template + RED alert, stop) → medication safety → approved-only retrieval → routed LLM with JSON schema →
response validation → citations → persist messages → audit.

## Key design decisions

| Decision | Choice | Why |
|---|---|---|
| Monorepo layout | `ai/ agents/ rag/ rules/` as top-level Python packages next to `backend/` | Matches requested structure; keeps safety-critical deterministic code (`rules/`) independent of the web framework and trivially unit-testable |
| Clinical decisions | Deterministic rules engine over JSON-DSL protocols stored in DB | Auditable, versioned, surgeon-approved; LLM can't invent thresholds |
| Agents | Code-orchestrated pipeline, not autonomous tool-calling | Predictable paths, testable, LLM only phrases answers from supplied approved text |
| Alerts vs tasks | One `alerts` table with `severity` RED/AMBER/INFO and `category` | One worklist, one SLA clock, one audit pattern for clinical alerts and care-team tasks |
| One alert per check-in | Combine matched rules; append to an open alert of ≥ severity | Avoids 4 alerts for one bad check-in; nurses see one row with all evidence |
| Vector store | pgvector in the same Postgres | Simplest production-viable option; no extra service; HNSW index |
| Default embeddings | Deterministic hashing embedder + lexical re-rank | Offline, reproducible tests, no model download; pluggable |
| LLM fallback | Extractive provider (quotes approved sentences) | System is fully functional and safe without any API key |
| Schema management | `create_all` + idempotent DDL at startup | POC speed; Alembic is the first production task |
| Audit immutability | Postgres trigger rejects UPDATE/DELETE on `audit_events` | Enforced below the application |
| Field encryption | Fernet `EncryptedText` type for notes/free text/messages | Defense in depth beyond storage encryption; key from env/KMS |
| Scheduler | asyncio loop in API process + `/admin/jobs/run` | Simple; production → EventBridge Scheduler + worker task |
| Frontend serving | Static build in nginx, same origin as API | No CORS in prod path; CSP `connect-src 'self'` |
| Time zone | UTC everywhere | POC simplification; per-clinic TZ later |

## Module map (brief §4)

| Module | Where |
|---|---|
| Authentication & RBAC | `core/security.py`, `api/auth.py`, `api/deps.py` |
| Patient Enrollment / Surgical Episode | `models` (`patients`, `programs`, `surgical_episodes`), seed |
| Recovery Plan | `agents/recovery_plan.py`, `/patients/{id}/recovery-plan`, `/plans/*` |
| Daily Check-in | `agents/checkin_analysis.py` |
| Medication / Appointment Management | `api/patients.py` |
| Patient Education | `/education` |
| AI Recovery Assistant | `agents/orchestrator.py`, `api/ai.py` |
| Warning/Alert Engine | `rules/engine.py` |
| Escalation Management / Worklist | `services/alerts.py`, `api/alerts.py` |
| Caregiver Authorization | `api/patients.py` (caregivers), `api/caregiver.py` |
| Notifications | `services/notifications.py` |
| Audit Trail | `services/audit.py`, DB trigger, `/audit` |
| Admin Dashboard / Analytics | `api/admin.py`, `services/analytics.py` |
