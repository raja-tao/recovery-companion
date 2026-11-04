# Security

Designed toward HIPAA Security Rule safeguards. **The POC holds only synthetic data**; a pilot with PHI would
additionally require a BAA with every vendor in the data path (AWS, the LLM provider), a risk analysis, and the
production items listed at the end.

## Authentication

- Email + password → JWT (HS256, `iss`, `exp`, `jti`), default 60 min (`ACCESS_TOKEN_MINUTES`).
- Passwords: bcrypt (cost 12). Unknown-email logins verify against a dummy hash (uniform timing) and return a
  generic message. Failed and successful logins are audited.
- Inactive users are rejected on every request.
- Token stored in `sessionStorage` (cleared with the tab). Production: Cognito / enterprise IdP (OIDC + MFA for
  staff), short-lived access tokens, refresh via httpOnly secure cookie.

## Authorization (RBAC + minimum necessary)

Permissions are defined in code (`backend/app/core/security.py`); every route declares the permission it needs, and
every patient-scoped route goes through `patient_access()`:

There is no pharmacist role: treatment decisions (medication questions, reconciliation, missed-dose guidance) belong
to the doctor (`SURGEON` role).

| Capability | Patient | Caregiver | Nurse | Doctor (surgeon) | Admin |
|---|---|---|---|---|---|
| Own plan, check-in, mood, surveys, meds, appts + rides, assistant, caregivers | ✔ (own) | | | | |
| Consented caregiver view | | ✔ (scopes) | | | |
| Patient list / summary | | | ✔ | ✔ | list only |
| Timeline, check-ins, mood, notes | | | ✔ | ✔ | ✗ |
| Medications | | | ✔ | ✔ | ✗ |
| Approve missed-dose guidance (treatment) | | | ✗ | ✔ | ✗ |
| Worklist / alerts (incl. medication tasks) | | | ✔ | ✔ | ✗ |
| Work alerts (ack/contact/resolve) | | | ✔ | ✔ | ✗ |
| Book rides to appointments | | | ✔ | | ✗ |
| Escalation review, plan/protocol/content approval | | | | ✔ | content (non-surgeon) |
| Users, programs, content upload, protocols, integrations, audit, demo | | | analytics, demo | | ✔ |

Denied access to patient data is itself audited (`ACCESS_DENIED`). Staff reads of PHI (profile, timeline,
check-ins, medications, summary, alert detail) are audited (`PHI_VIEW_*`). Caregivers receive a separately shaped
response that physically omits clinical fields.

## Data protection

- TLS terminates at nginx/ALB (production: CloudFront + ALB with ACM certificates, HSTS enabled in production mode).
- Field-level encryption (Fernet) for free text, notes, messages, resolutions (`EncryptedText`); key from
  `FIELD_ENCRYPTION_KEY` (production: Secrets Manager, KMS-wrapped, rotation via re-encryption job).
- Storage encryption: RDS/KMS, S3 SSE-KMS (production).
- External notifications (email/SMS) carry no PHI: *"You have a new update in your Recovery Companion app."*
- Validation errors never echo submitted values; unhandled errors return a generic 500.
- `Cache-Control: no-store` on API responses.

## Application hardening

| Control | Implementation |
|---|---|
| Input validation | Pydantic schemas with lengths/enums/ranges; check-in answers validated against configured questions; upload type/size limits |
| Rate limiting | Sliding window per IP: global 300/min, login 10/min, AI 30/min (`RATE_LIMIT_*`). Production: WAF rate rules + Redis |
| Security headers | API: CSP `default-src 'none'`, `X-Frame-Options DENY`, `nosniff`, `Referrer-Policy no-referrer`, `Permissions-Policy`, COOP, HSTS (prod). SPA (nginx): CSP `default-src 'self'` |
| CORS | Allow-list (`CORS_ORIGINS`); production path is same-origin |
| Secrets | Environment only; `.env` git-ignored; app refuses to start in `APP_ENV=production` with dev JWT secret, missing encryption key or dev DB credentials |
| Containers | Non-root user (uid 10001); backend not published to the host by default |
| Audit | Append-only (DB trigger), request id + IP on every event |
| Prompt injection | Deterministic pre-classification, untrusted-input tagging, schema-constrained output, post-validation |
| Supply chain | Pinned Python deps; npm lockfile; official base images |

## HIPAA safeguard mapping (summary)

| Safeguard | POC coverage |
|---|---|
| Access control §164.312(a) | Unique user IDs, RBAC, automatic token expiry, encryption-ready |
| Audit controls §164.312(b) | Immutable audit of access and actions |
| Integrity §164.312(c) | Append-only audit; document checksums; versioned content/protocols/plans |
| Authentication §164.312(d) | Password + JWT (MFA via IdP in production) |
| Transmission security §164.312(e) | TLS at edge; no PHI in SMS/email |
| Minimum necessary §164.502(b) | Role-scoped fields/endpoints; caregiver scopes |

## Production backlog

MFA/SSO via Cognito; refresh-token rotation and revocation list; Redis-backed rate limiter; WAF; KMS envelope
encryption with key rotation; DB role with INSERT/SELECT-only on audit; centralized SIEM; dependency & container
scanning in CI; penetration test; BAA with LLM vendor (or Claude via Amazon Bedrock inside the AWS BAA boundary).
