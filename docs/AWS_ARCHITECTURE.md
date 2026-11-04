# Target AWS Architecture

Nothing is provisioned by this repository. This describes how the POC maps onto AWS for a pilot.

```
 Patients / staff
      │ HTTPS
 ┌────▼─────────────┐        ┌──────────────────────────┐
 │ CloudFront + WAF │──────▶ │ S3 (SPA static build)    │
 │ (TLS, rate rules)│        └──────────────────────────┘
 └────┬─────────────┘
      │ /api/*
 ┌────▼──────────────────┐
 │ ALB (or API Gateway)  │  ACM certs, HTTPS only
 └────┬──────────────────┘
      │ private subnets
 ┌────▼──────────────────────────────┐     ┌───────────────────────────────┐
 │ ECS Fargate: api service (N tasks)│────▶│ Amazon Bedrock (Claude) or    │
 │ FastAPI container (this image)    │     │ Claude API via NAT/egress     │
 ├───────────────────────────────────┤     └───────────────────────────────┘
 │ ECS Fargate: worker service       │  ◀── EventBridge Scheduler (reminders,
 │ (scheduler jobs, ingestion)       │       missed check-ins, SLA monitor)
 └────┬───────────┬──────────┬───────┘
      │           │          │
 ┌────▼─────┐ ┌───▼──────┐ ┌─▼───────────────────┐  ┌──────────────────────┐
 │ RDS      │ │ S3       │ │ ElastiCache Redis   │  │ SES (email) ·        │
 │ Postgres │ │ documents│ │ rate limit, cache   │  │ SNS / Pinpoint (SMS) │
 │+pgvector │ │ (SSE-KMS,│ └─────────────────────┘  └──────────────────────┘
 │ Multi-AZ │ │ versioned)│
 └──────────┘ └──────────┘
 Secrets Manager (JWT, DB, field-encryption, LLM keys) · KMS · CloudWatch (logs, metrics, alarms) ·
 CloudTrail · GuardDuty · Security Hub · Cognito (identity, MFA)
```

## Component mapping

| POC component | AWS service | Notes |
|---|---|---|
| nginx serving SPA | S3 + CloudFront | Same-origin `/api/*` behavior to ALB keeps CSP `connect-src 'self'` |
| FastAPI container | ECS Fargate service behind ALB | Same Dockerfile; ≥ 2 tasks across AZs; health check `/api/health` |
| asyncio scheduler | EventBridge Scheduler → ECS worker task | Jobs already idempotent (dedupe keys) — safe with retries/overlap |
| Postgres + pgvector | RDS for PostgreSQL 16 (pgvector supported), Multi-AZ, KMS | Alternative: Aurora PostgreSQL; or OpenSearch Serverless for vectors at larger scale |
| Document text | S3 (`storage_uri` already modeled), SSE-KMS, versioning, Object Lock optional | Ingestion worker reads S3 → chunks → pgvector |
| `.env` secrets | Secrets Manager (+ rotation), injected as ECS secrets | App refuses dev secrets in production mode |
| Field encryption key | KMS data key in Secrets Manager | Envelope encryption; rotation job re-encrypts |
| JSON logs / Prometheus metrics | CloudWatch Logs + EMF / CloudWatch agent; alarms on RED SLA breach, 5xx, AI latency | |
| Audit trail | RDS table (append-only) + subscription to CloudWatch Logs/S3 Object Lock | Long-term WORM retention |
| Mock notifications | SES (email), SNS/Pinpoint (SMS), in-app unchanged | Implement `NotificationProvider` subclasses |
| Claude API | Amazon Bedrock (`anthropic.claude-*`) inside the AWS BAA boundary, or Claude API under a BAA | Add a `BedrockProvider` (Anthropic SDK `AnthropicBedrockMantle` client) — router unchanged |
| Embeddings | Bedrock Titan/Cohere embeddings | New `EmbeddingProvider`; reindex |
| Rate limiting | WAF rate-based rules + Redis | Replace in-memory limiter |
| Auth | Cognito user pools (patients) + federated IdP/SAML (staff), MFA | API validates Cognito JWTs |

## Networking & security

VPC with public (ALB, NAT) and private (ECS, RDS, Redis) subnets; security groups least-privilege; VPC endpoints
for S3, Secrets Manager, Bedrock, CloudWatch; no public DB. IAM task roles scoped per service. CloudTrail,
GuardDuty, Security Hub, AWS Config (HIPAA conformance pack). Backups: RDS automated backups + PITR, S3 versioning.

## Delivery

CI: lint, `pytest` (unit/API/safety against an ephemeral Postgres), frontend build, container scan, push to ECR.
CD: Alembic migration task → blue/green ECS deploy (CodeDeploy) → smoke (`make e2e` against staging) → promote.
IaC: CDK or Terraform (not included).
