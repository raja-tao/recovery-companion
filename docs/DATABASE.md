# Database

PostgreSQL 16 with the `pgvector` extension. All primary keys are UUIDs. Mutable tables carry `created_at` /
`updated_at` (timestamptz, UTC). Models: `backend/app/models/__init__.py`.

## Entities

| Area | Table | Purpose / notable columns |
|---|---|---|
| Identity | `roles` | PATIENT, CAREGIVER, NURSE, SURGEON, ADMIN (no pharmacist role; medication decisions are the doctor's) + permission list (documentation copy of the code matrix) |
| | `users` | email (unique), bcrypt `password_hash`, `role_id`, `is_active`, `last_login_at` |
| | `programs` | 30-day programs, procedure types, configurable KPI `targets` |
| | `patients` | synthetic MRN, demographics, `assigned_nurse_id`, `current_risk` (denormalized max open alert severity), `is_synthetic` |
| | `caregivers` | patient ↔ caregiver-user authorization, `status` ACTIVE/REVOKED, timestamps |
| | `caregiver_permissions` | granted scopes (RECOVERY_STATUS, TASKS, REMINDERS, PROGRESS, APPOINTMENTS), `revoked_at` |
| Episode & plan | `surgical_episodes` | procedure type/name, surgeon, surgery & discharge dates |
| | `recovery_plans` | per episode; `current_version_id` |
| | `recovery_plan_versions` | `version`, `status` DRAFT/PENDING_APPROVAL/APPROVED/SUPERSEDED, JSON `content`, `created_by_id`, `approved_by_id`, `approved_at` |
| | `recovery_tasks` | generated from an approved version: day range, category, caregiver visibility |
| | `task_completions` | per task per day |
| Check-in | `checkin_questions` | configurable per procedure (`ALL` + overrides), type, options, ranges |
| | `checkins` | date, recovery day, COMPLETED/MISSED, `risk_level`, `rule_results` JSON, encrypted free text |
| | `checkin_responses` | one row per answered question (`value` JSON) |
| Medications | `medications` | name, `dose_text` (display only), indication, schedule times, PRN, approved `missed_dose_guidance` |
| | `medication_events` | TAKEN/MISSED/SKIPPED/UNKNOWN per scheduled dose |
| Appointments | `appointments` | type, provider, location, time, status, `transportation_status`, reminder sent |
| Content | `documents` | `document_key` + `version` (unique), type, authority, approval status, approver, effective/expiry, procedure, population, `is_active`, checksum, `storage_uri` (S3 in AWS) |
| | `document_chunks` | section path, content, token count, `embedding vector(384)`, embedding model, metadata |
| | `education_content` | patient-facing articles linked to source documents |
| Rules | `warning_protocols` | `rule_id` + `version`, severity, JSON condition DSL, response minutes, team, status, approver |
| Work | `alerts` | patient, severity RED/AMBER/INFO, category, source, rule id, trigger, evidence JSON, status, SLA (`required_response_minutes`, `due_at`, `sla_breached`), ack/contact/resolve/close timestamps, encrypted resolution |
| | `escalations` | alert → role/user, reason, response, status |
| | `care_team_actions` | ACKNOWLEDGE/CONTACT_*/NOTE/ESCALATE/RESOLVE/CLOSE/MESSAGE, method, outcome, encrypted note, `internal` flag |
| Comms | `notifications` | channel EMAIL/SMS/IN_APP, category, provider, status, `dedupe_key` (unique → idempotent jobs) |
| | `conversations` | ASSISTANT or CARE_TEAM thread per patient |
| | `messages` | encrypted content, intent, safety level, citations, retrieval metadata, model, prompt version, latency, tokens, linked alert |
| Audit | `audit_events` | append-only: actor, role, patient, action, resource, outcome, details JSON, request id, IP |

## Indexes

Foreign keys and frequent filters are indexed, plus:
`ix_checkins_patient_date`, `ix_med_events_patient_sched`, `ix_alerts_open (status, severity, due_at)`,
`ix_documents_retrievable (approval_status, is_active)`, `ix_notifications_user_status`,
`ix_audit_patient_time (patient_id, occurred_at)`, and an **HNSW** index on
`document_chunks.embedding vector_cosine_ops`.

## Immutability

`audit_events` has a `BEFORE UPDATE OR DELETE` row trigger that raises an exception (`backend/app/core/database.py`).
No API route can modify audit rows; tests assert both the trigger and the absence of mutating routes.
For production, additionally grant the application role only `INSERT, SELECT` on `audit_events` and stream to
write-once storage (CloudWatch Logs / S3 Object Lock).

## Encryption

Sensitive free text (check-in concerns, notes, resolutions, messages, escalation reasons, transportation notes) is
stored with an `EncryptedText` column type (Fernet). Storage-level encryption (RDS/KMS) covers everything else.

## Migrations

POC: `init_schema()` runs `CREATE EXTENSION`, `create_all`, the HNSW index and the audit trigger idempotently at
startup. Production plan: introduce Alembic with this schema as revision 0001, run migrations as a one-off ECS task
in the deploy pipeline, never at app start.

## Seed data

`python -m app.seed` (auto on first start). 26 synthetic patients across TKA, THA, ACL and laparoscopic
cholecystectomy, at different recovery days, covering: normal recovery, missed check-ins, medication question,
increasing pain, fever + wound warning (RED), transportation problem, caregiver access (granted and revoked),
a resolved emergency with escalation history, medication non-adherence, and a plan pending surgeon approval.
Also: 13 approved warning protocols (+1 DRAFT revision), 8 documents (incl. one DRAFT and one EXPIRED that must never be retrieved),
9 education items.
