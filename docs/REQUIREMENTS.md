# Requirements & Traceability

**Source note.** The BRD and "HLS Agent POC Roadmap" referenced in the brief were not attached to the build request.
Requirements below were extracted from the detailed build brief (sections 1–37), which restates the BRD's goals,
roles, modules, journeys and target metrics. When the original BRD is available, reconcile it against this list.

## Functional requirements

| ID | Requirement | Implementation |
|---|---|---|
| FR-01 | JWT authentication, 6 roles, RBAC with minimum necessary access | `backend/app/core/security.py`, `app/api/deps.py` |
| FR-02 | Patient enrollment into a 30-day program linked to a surgical episode | `patients`, `programs`, `surgical_episodes`; seed + timeline |
| FR-03 | 30-day journey: Stabilize 0–3, Monitor 4–7, Progress 8–14, Transition 15–30 | `services/patients.py::PHASES` |
| FR-04 | Versioned recovery plan (procedure, surgery date, instructions, meds, activity/walking goals, wound, hydration, PT, appointments, check-in schedule, warning signs) with created-by/approved-by/date/version/status; only APPROVED plans shown | `recovery_plans`, `recovery_plan_versions`, `agents/recovery_plan.py` |
| FR-05 | Daily check-in, configurable per procedure | `checkin_questions` (ALL + procedure overrides), `agents/checkin_analysis.py` |
| FR-06 | Deterministic alert engine (RED/AMBER/GREEN) from approved protocols; LLM never sets thresholds | `rules/engine.py`, `warning_protocols` |
| FR-07 | Alert record: patient, severity, trigger, rule ID, evidence, timestamp, response time, team, status; NEW→ACKNOWLEDGED→CONTACT_IN_PROGRESS→RESOLVED/ESCALATED→CLOSED | `alerts`, `services/alerts.py` state machine |
| FR-08 | Medications with schedule, guidance; TAKEN/MISSED/SKIPPED/UNKNOWN; AI never modifies dose | `medications`, `medication_events`, `agents/medication_safety.py` |
| FR-09 | Appointments with reminders and transportation question → coordinator task | `appointments`, `/transportation` endpoint, `APPT-TRANSPORT` policy |
| FR-10 | Approved education | `education_content` linked to documents |
| FR-11 | AI assistant: approved-content Q&A with citations; refuses otherwise and creates a task | `agents/orchestrator.py` |
| FR-12 | Safety classification GREEN/AMBER/RED before generation; RED → emergency guidance + escalation | `rules/safety.py` |
| FR-13 | RAG over approved documents with versioning, metadata, citations; ACTIVE+APPROVED only | `rag/*`, `documents`, `document_chunks` (pgvector) |
| FR-14 | Nurse worklist (Patient / Risk / Reason / Last check-in / Action / SLA) and patient record actions | `/care-team/worklist`, `PatientDetail` UI |
| FR-15 | Complete timestamped patient timeline | `services/timeline.py` |
| FR-16 | Caregiver authorization with scopes; revocable | `caregivers`, `caregiver_permissions`, `/caregiver/*` |
| FR-17 | Notification abstraction: email/SMS/in-app (mocks) | `services/notifications.py` |
| FR-18 | Immutable audit trail of users, data access, AI requests/responses, rules, alerts, human actions | `audit_events` + DB trigger |
| FR-19 | Document management: upload, version, approve, retire, metadata | `/documents*` |
| FR-20 | Admin: users, programs, content, protocols, audit, metrics | `/admin/*`, `/protocols`, `/audit`, `/analytics` |
| FR-21 | Analytics vs BRD targets (check-in ≥70%, adherence ≥90%, follow-up ≥90%, RED→contact ≤15 min), configurable | `services/analytics.py`, settings |
| FR-22 | Automated demo mode with 8 scenarios | `/demo/*`, `scripts/run_demo.py`, Demo UI |
| FR-23 | Synthetic data only: 20–30 patients, multiple procedures, normal/amber/red cases | `backend/app/seed.py` (26 patients, 4 procedures) |

## Non-functional requirements

| ID | Requirement | Implementation |
|---|---|---|
| NFR-01 | One-command local start | `docker compose up` / `make dev` |
| NFR-02 | LLM-provider independence (Claude default, OpenAI, Ollama) | `ai/providers/*`, `ai/router.py` |
| NFR-03 | Security: hashing, JWT, input validation, rate limiting, secure headers, env secrets, encryption-ready | see SECURITY.md |
| NFR-04 | Observability: structured logs, API/AI latency, tokens, model usage, RAG, alerts | `core/observability.py`, `/api/metrics`, analytics |
| NFR-05 | Accessible, responsive UX; severity never color-only | MUI, icon+text severity chips, skip link, ARIA |
| NFR-06 | AWS-ready architecture | AWS_ARCHITECTURE.md |

## Acceptance criteria (brief §36) → evidence

| # | Criterion | Verified by |
|---|---|---|
| 1 | Synthetic patient can log in | `test_auth_rbac::test_login_success_and_me`, e2e |
| 2 | Patient sees 30-day plan | `test_patient_sees_30_day_plan_and_dashboard` |
| 3–5 | Check-in → rules → GREEN/AMBER/RED | `test_checkin_green_amber_red_and_nurse_workflow`, `tests/unit/test_rules_engine.py` |
| 6 | RED alert reaches worklist | same + demo scenario 3 |
| 7–9 | Nurse acknowledges, records outreach, resolves/escalates | same + demo scenario 8 |
| 10–11 | Medication schedule + adherence | `test_medications_and_adherence` |
| 12 | Appointments | `test_appointments_and_transportation` |
| 13–15 | Assistant answers only from approved content with citations | `tests/safety` (13 cited answers), RAG tests |
| 16 | Unsupported questions refused | safety suite (5 cases), scenario 6 |
| 17 | Dosing questions escalated | safety suite (9 medication cases), scenario 4 |
| 18 | Caregiver authorization | `test_caregiver_authorize_limited_view_and_revoke`, scenario 7 |
| 19 | Complete audit trail | `test_audit_log_contents_and_api_is_read_only`, `test_audit_is_immutable`, e2e |
| 20 | Demo scenarios end-to-end | `test_all_demo_scenarios_pass`, `make demo` |
| 21 | Automated tests pass | `make test`, `make e2e`, `make ui-smoke` |
| 22 | One documented command | README |
| 23 | Complete setup instructions | README |
| 24 | AWS-ready | AWS_ARCHITECTURE.md |
| 25 | No real PHI | seed is fully synthetic; `is_synthetic` flag; banner |
