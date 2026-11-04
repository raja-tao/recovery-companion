# API Contract

- Base URL: `/api` (same origin as the SPA; nginx proxies to FastAPI)
- Interactive docs: **`/api/docs`** (Swagger UI), `/api/redoc`; machine-readable: `/api/openapi.json`
  (exported copy: [`openapi.json`](openapi.json), refresh with `make openapi`)
- Auth: `POST /api/auth/login` → `{access_token, expires_in, user}`; send `Authorization: Bearer <token>`
- Errors: JSON `{"detail": ...}`. 401 unauthenticated, 403 forbidden (RBAC / patient scope), 404, 409 invalid state
  transition, 422 validation (submitted values are never echoed back), 429 rate limited (`Retry-After`)
- Every response carries `X-Request-ID` (also stored on audit events)

## Brief §21 endpoints → implementation

| Brief | Implemented as |
|---|---|
| `POST /auth/login` | `POST /api/auth/login` |
| `GET /patients/me` | `GET /api/patients/me` |
| `GET /patients/{id}/recovery-plan` | same |
| `GET /patients/{id}/timeline` | same |
| `POST/GET /patients/{id}/checkins` | same (+ `GET /patients/{id}/checkin-questions`) |
| `GET /patients/{id}/medications` | same (list + today's schedule + adherence) |
| `POST /patients/{id}/medications/{id}/events` | same |
| `GET /patients/{id}/appointments` | same (+ POST create, POST `/transportation`) |
| `POST /patients/{id}/questions` | same (alias of `/ai/chat`) |
| `POST /ai/chat` | same |
| `GET /care-team/worklist` | same |
| `GET /alerts`, `POST /alerts/{id}/acknowledge|resolve|escalate` | same (+ `/contact`, `/close`, `GET /alerts/{id}`) |
| `POST /documents`, `POST /documents/{id}/approve` | same (+ `/upload`, `/retire`, `/search`) |
| `GET /audit` | same (read-only; no mutating audit endpoint exists) |

## Key payloads

**Check-in submit** `POST /api/patients/{id}/checkins`
```json
{"answers": {"pain_score": 7, "pain_trend": "WORSE", "temperature": 101.8, "wound_appearance": "MORE_RED",
             "swelling": "SAME", "mobility": "WITH_AID", "medication_adherence": "ALL", "new_symptoms": ["NONE"]}}
```
→
```json
{"checkin_id": "…", "recovery_day": 6, "risk_level": "RED",
 "rules_triggered": [{"rule_id": "RED-FEVER", "name": "Fever ≥ 101.0°F", "severity": "RED",
                      "evidence": [{"fact": "temperature_f", "op": ">=", "threshold": 101.0, "actual": 101.8}],
                      "response_minutes": 15, "assigned_team": "NURSE"}, "…"],
 "alerts_created": ["…"], "patient_message": "Your answers match a warning sign…", "emergency": false}
```

**Assistant** `POST /api/ai/chat` `{"message": "When can I drive?"}` →
```json
{"answer": "Do not drive for at least 4 weeks after surgery…", "safety_level": "GREEN", "intent": "RECOVERY_QUESTION",
 "answered_from_content": true, "emergency": false,
 "citations": [{"title": "Total Knee Replacement — Surgeon Discharge Instructions", "section": "Driving", "version": 1,
                "authority": "SURGEON_APPROVED", "approved_by": "Dr. Samuel Okafor", "score": 0.856, "excerpt": "…"}],
 "retrieval": {"query_terms": ["drive"], "candidates_considered": 24, "top_score": 0.856, "embedding_model": "hashing-v1-384"},
 "actions": ["Answered from approved content"], "alert_id": null, "model": "claude-opus-5-5", "provider": "claude",
 "prompt_version": "recovery-qa-v1.2", "latency_ms": 1840, "flags": [], "disclaimer": "…"}
```

## All endpoints (generated from OpenAPI)

### Authentication

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Authenticate and receive a JWT access token |
| GET | `/api/auth/me` | Me |

### Patients

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/patients/me` | Current patient's profile |
| GET | `/api/patients` | Patient list (care team / admin) |
| GET | `/api/patients/{patient_id}` | Patient profile + episode |
| GET | `/api/patients/{patient_id}/dashboard` | Patient home screen data |
| GET | `/api/patients/{patient_id}/recovery-plan` | Approved 30-day recovery plan |
| POST | `/api/patients/{patient_id}/tasks/{task_id}/complete` | Mark today's task done |
| GET | `/api/patients/{patient_id}/checkin-questions` | Configured check-in questions for this patient's procedure |
| POST | `/api/patients/{patient_id}/checkins` | Submit daily check-in |
| GET | `/api/patients/{patient_id}/checkins` | Check-in history |
| GET | `/api/patients/{patient_id}/medications` | Medication list + today's schedule |
| POST | `/api/patients/{patient_id}/medications/{medication_id}/events` | Record dose TAKEN/MISSED/SKIPPED/UNKNOWN |
| GET | `/api/patients/{patient_id}/appointments` | Appointments |
| POST | `/api/patients/{patient_id}/appointments` | Create appointment (care team) |
| POST | `/api/patients/{patient_id}/appointments/{appointment_id}/transportation` | Answer the transportation question; NEEDS_HELP creates a coordinator task |
| GET | `/api/patients/{patient_id}/timeline` | Complete, timestamped patient timeline |
| GET | `/api/patients/{patient_id}/summary` | Care-team summary (Care-Team Summary Agent) |
| GET | `/api/patients/{patient_id}/alerts` | Alerts for a patient |
| GET | `/api/patients/{patient_id}/notes` | Care-team actions and notes (internal) |
| POST | `/api/patients/{patient_id}/notes` | Add internal care-team note |
| GET | `/api/patients/{patient_id}/messages` | Care-team ↔ patient messages |
| POST | `/api/patients/{patient_id}/messages` | Send a message (care team → patient, or patient → care team) |
| GET | `/api/patients/{patient_id}/caregivers` | Caregivers authorized by the patient |
| POST | `/api/patients/{patient_id}/caregivers` | Authorize a caregiver (patient only) |
| DELETE | `/api/patients/{patient_id}/caregivers/{caregiver_id}` | Revoke caregiver access immediately |

### AI Recovery Assistant

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ai/chat` | Ask the Recovery Assistant (approved content only, safety-classified, audited) |
| POST | `/api/patients/{patient_id}/questions` | Ask a question about approved recovery content (alias of /ai/chat) |
| GET | `/api/ai/conversation` | Assistant conversation history for the current patient |

### Caregiver

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/caregiver/patients` | Patients who authorized this caregiver |
| GET | `/api/caregiver/patients/{patient_id}` | Limited, consented view of a patient's recovery |

### Care Team & Alerts

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/care-team/worklist` | Prioritized worklist: patients needing attention |
| GET | `/api/alerts` | List alerts (filterable) |
| GET | `/api/alerts/{alert_id}` | Alert detail with evidence and action history |
| POST | `/api/alerts/{alert_id}/acknowledge` | Acknowledge |
| POST | `/api/alerts/{alert_id}/contact` | Record patient outreach (call/SMS/video) |
| POST | `/api/alerts/{alert_id}/resolve` | Resolve |
| POST | `/api/alerts/{alert_id}/escalate` | Escalate (e.g. nurse → surgeon) |
| POST | `/api/alerts/{alert_id}/close` | Close |
| GET | `/api/escalations` | Escalations (surgeon review queue) |
| POST | `/api/escalations/{escalation_id}/respond` | Doctor response to an escalation |

### Content, Protocols & Plans

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/documents` | List knowledge documents (all versions) |
| POST | `/api/documents` | Create a document version (JSON). Starts PENDING approval |
| POST | `/api/documents/upload` | Upload a .md/.txt/.pdf document (multipart) |
| GET | `/api/documents/{document_id}` | Document detail with content and chunks |
| POST | `/api/documents/{document_id}/approve` | Approve + activate (supersedes other active versions) |
| POST | `/api/documents/{document_id}/retire` | Retire a document (removed from retrieval immediately) |
| POST | `/api/documents/search` | Test retrieval (approved content only) — for content reviewers |
| GET | `/api/education` | Approved education for the current patient (or all, for staff) |
| GET | `/api/protocols` | Warning protocols (rules engine configuration) |
| POST | `/api/protocols` | Propose a protocol version (DRAFT until surgeon approval) |
| POST | `/api/protocols/{protocol_id}/approve` | Surgeon approval — activates this protocol version |
| GET | `/api/plans/pending` | Plan versions awaiting approval |
| POST | `/api/plans/{plan_id}/versions` | Propose a new plan version |
| POST | `/api/plans/versions/{version_id}/approve` | Approve a recovery plan version (surgeon) |

### Administration

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + DB check |
| GET | `/api/metrics` | Prometheus metrics |
| GET | `/api/metrics/json` | In-process metrics snapshot |
| GET | `/api/admin/users` | List Users |
| POST | `/api/admin/users` | Create User |
| POST | `/api/admin/users/{user_id}/active` | Set Active |
| GET | `/api/admin/programs` | List Programs |
| POST | `/api/admin/programs` | Create Program |
| GET | `/api/audit` | Audit trail (read-only; immutable at the DB level) |
| GET | `/api/analytics` | Program metrics vs illustrative BRD targets |
| POST | `/api/admin/jobs/run` | Run scheduled jobs now (missed check-ins, reminders, SLA) |
| GET | `/api/notifications/me` | My Notifications |
| POST | `/api/notifications/read-all` | Read All |

### Demo mode

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/demo/scenarios` | List demo scenarios |
| POST | `/api/demo/scenarios/{n}/run` | Run one demo scenario end-to-end |
| POST | `/api/demo/scenarios/run-all` | Run all demo scenarios |