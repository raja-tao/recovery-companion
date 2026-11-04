# Post-Surgical Recovery Companion (POC)

> ⚠️ **Proof of concept. Synthetic data only. Not for clinical use.**
> This is a *recovery companion and care-navigation assistant*, not an "AI doctor". It never diagnoses,
> prescribes, or changes treatment. Emergency symptoms are always routed to 911 guidance and a human.

A working, locally runnable full-stack application that supports patients for the first 30 days after surgical
discharge and gives nurses, doctors and administrators the tools to act on what patients report.

| | |
|---|---|
| **Patient** | Mood question at every sign-in with a personal reply, 30-day plan (Stabilize → Monitor → Progress → Transition), daily tasks, 2-minute check-in, medications & adherence, appointments with day-before ride check and hospital pickup requests, HOOS JR / KOOS JR outcome surveys, approved education, AI assistant with citations, messages, caregiver access control — on the web or the Android app |
| **Caregiver** | Consent-scoped, read-only view (status / tasks / reminders / progress / appointments) — revocable at any time |
| **Nurse / care manager** | Prioritized worklist with SLA clocks, patient record (timeline, check-ins, wellbeing, meds, alerts, notes, messages), ride booking for appointments, acknowledge → outreach → escalate → resolve → close |
| **Doctor (surgeon)** | The only role that decides treatment: medication questions and reconciliation, missed-dose guidance approval, escalation queue, recovery-plan approval, warning-protocol and content approval |
| **Administrator** | Approved-content management (upload, version, approve, retire, test retrieval), protocols, users/programs, immutable audit trail, analytics vs BRD targets, demo mode |

## Quick start (one command)

Prerequisites: Docker Desktop (Compose v2.24+). Nothing else is required on the host.

```bash
make dev            # = cp .env.example .env (first run) && docker compose up --build
# or simply:
docker compose up --build
```

Open **http://localhost:8080**. API docs (OpenAPI / Swagger): **http://localhost:8080/api/docs**.

The database is created, migrated and seeded with synthetic data automatically on first start (~10 s).

### Demo accounts (local development only)

All demo accounts use the password **`Recovery#2026`** (override with `DEMO_PASSWORD` before first seed).

| Email | Role | Notes |
|---|---|---|
| `patient@example.com` | Patient | Jordan Lee — knee replacement, day 5, normal recovery, has an authorized caregiver |
| `patient2@example.com` | Patient | Carol King — knee replacement, day 14 |
| `mary.smith@example.com` | Patient | Mary Smith — hip replacement, 2 missed check-ins (AMBER) |
| `caregiver@example.com` | Caregiver | Casey Lee — authorized by Jordan (4 scopes); access from Carol was revoked |
| `caregiver2@example.com` | Caregiver | No authorizations yet (use it to demo granting access) |
| `nurse@example.com` | Nurse / care manager | Nina Patel |
| `doctor@example.com` | Surgeon | Dr. Samuel Okafor (orthopedics) |
| `doctor2@example.com` | Surgeon | Dr. Elena Garcia (general surgery) |
| `admin@example.com` | Administrator | Avery Admin |

These are synthetic, local-only credentials. Never reuse them in any shared or deployed environment.

### Enabling Claude (recommended)

The assistant uses **Claude by default** (`claude-opus-5-5`, low effort). Put your key in `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

then `docker compose up -d`. Without a key the system automatically falls back to the deterministic
**extractive** provider, which only quotes approved text — so every feature, test and demo works offline.
OpenAI (`LLM_PROVIDER=openai`, `OPENAI_API_KEY`) and local Ollama (`LLM_PROVIDER=ollama`) are optional.
`GET /api/health` shows which provider is active.

## Common commands

| Command | What it does |
|---|---|
| `make dev` / `make up` | Start the stack (foreground / background) |
| `make test` | Full backend suite: unit, API, RBAC, rules, RAG, audit, demo, **45-question AI safety suite** (separate test DB) |
| `make e2e` | End-to-end HTTP tests against the running stack (nginx → API → Postgres) |
| `make ui-smoke` | Headless Chromium visits every page as every role; fails on console errors (screenshots in `tests/e2e/screenshots/`) |
| `make demo` | Runs the 8 BRD demo scenarios via the API and prints a pass/fail report |
| `make reset` | Drop and reseed all synthetic data |
| `make jobs` | Run scheduled jobs now (missed check-ins, reminders, SLA breach) |
| `make reindex` | Re-chunk/re-embed documents (after changing `EMBEDDING_PROVIDER`) |
| `make openapi` | Export `docs/openapi.json` |
| `make clean` | Remove containers **and** the database volume |

Demo scenarios can also be run from the UI: sign in as `admin@` or `nurse@` → **Demo scenarios** → *Run all 8*.

## Repository layout

```
backend/     FastAPI app: API routers, models, schemas, services (audit, alerts, notifications, scheduler…), seed
ai/          LLMProvider abstraction (Claude, OpenAI, Ollama, extractive), ModelRouter, prompts, response validation
agents/      Controlled agent workflow: intake, recovery plan, check-in analysis, knowledge, medication safety,
             alert/escalation, care-team summary, orchestrator
rag/         Chunking, embeddings (pluggable), ingestion, approved-only retrieval (pgvector)
rules/       Deterministic warning-protocol engine + safety/intent classifier (no LLM)
integrations/ Inbound feed parsers (FHIR R4, HL7 v2, device JSON, NCPDP RxFill), LOINC/UCUM normalization, use-case catalog
mobile/       Android app (Capacitor shell around the web app) — built in Docker with `make android`
database/    Postgres init (pgvector extension, test DB)
knowledge/   Synthetic approved source documents (Markdown + approval metadata)
frontend/    React + TypeScript + Vite + MUI (mobile-first patient app, desktop care-team console)
tests/       unit · api · safety · e2e (HTTP + browser)
docs/        Architecture, API, database, AI, RAG, safety, security, testing, AWS, demo script
docker/      Dockerfiles + nginx config
scripts/     run_demo.py, reindex.py
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Functional requirements extracted from the brief + acceptance-criteria traceability |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, components, key design decisions |
| [docs/API.md](docs/API.md) | REST API contract (full OpenAPI in `docs/openapi.json` and `/api/docs`) |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema, entities, indexes, immutability, migration plan |
| [docs/AI_AGENT_ARCHITECTURE.md](docs/AI_AGENT_ARCHITECTURE.md) | Agents, orchestration pipeline, model routing |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Automated inputs (EHR, devices, pharmacy), outbound to the EHR, surveys, rides, pipeline, API |
| [docs/MOBILE.md](docs/MOBILE.md) | Android app: build the APK in Docker, install, server address, release signing |
| [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md) | Ingestion, chunking, embeddings, retrieval governance, citations |
| [docs/SAFETY_AND_GUARDRAILS.md](docs/SAFETY_AND_GUARDRAILS.md) | Clinical safety model, classifiers, validation, escalation policy |
| [docs/SECURITY.md](docs/SECURITY.md) | AuthN/Z, RBAC matrix, encryption, headers, rate limiting, HIPAA alignment |
| [docs/TESTING.md](docs/TESTING.md) | Test strategy and how to run each suite |
| [docs/AWS_ARCHITECTURE.md](docs/AWS_ARCHITECTURE.md) | Target AWS deployment |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Click-by-click walkthrough of the 8 scenarios |

## Local development without Docker (optional)

```bash
docker compose up -d db                                    # Postgres + pgvector on localhost:5433
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
PYTHONPATH=..:. DATABASE_URL=postgresql+psycopg://recovery:recovery_dev_only@localhost:5433/recovery \
  KNOWLEDGE_DIR=../knowledge uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && VITE_API_PROXY=http://localhost:8000 npm run dev   # http://localhost:5173
```

## Known limitations of the POC

- Single-process scheduler and in-memory rate limiter (one API replica). See AWS doc for the production design.
- Schema is created with `create_all`; Alembic migrations are the first production task (see DATABASE.md).
- Default embeddings are a deterministic hashing embedder (no model download). It is lexical-level and adequate for a
  small curated corpus; switch to OpenAI/Ollama/Bedrock embeddings for production.
- Times are stored and displayed in UTC; per-clinic time zones are a production follow-up.
- Notification providers are mocks (logged + stored); swap in SES/SNS/Pinpoint.
- No real PHI is used or required anywhere.
