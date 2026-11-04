"""Application settings. All secrets come from environment variables (12-factor).

Development defaults exist so `docker compose up` works out of the box; the app
refuses to start in production while any of them are still in use.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"
DEV_INTEGRATION_KEY = "dev-integration-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_name: str = "Post-Surgical Recovery Companion"
    app_env: str = "development"
    api_prefix: str = "/api"

    database_url: str = "postgresql+psycopg://recovery:recovery_dev_only@localhost:5433/recovery"
    test_database_url: str | None = None

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    field_encryption_key: str = ""

    # AI
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.1"
    llm_timeout_seconds: float = 60.0
    prompt_version: str = "recovery-qa-v1.2"

    embedding_provider: str = "hashing"
    embedding_dim: int = 384
    rag_top_k: int = 4
    rag_min_score: float = 0.18

    # Notifications / jobs
    notification_email_provider: str = "mock"
    notification_sms_provider: str = "mock"
    enable_scheduler: bool = True
    scheduler_interval_seconds: int = 300

    # Rate limiting
    rate_limit_per_minute: int = 300
    rate_limit_login_per_minute: int = 10
    rate_limit_ai_per_minute: int = 30

    # Inbound integrations. Seeded sources get the key "<INTEGRATION_DEMO_KEY>-<source slug>";
    # rotate them from Admin › Integrations. Max accepted message size in bytes.
    integration_demo_key: str = DEV_INTEGRATION_KEY
    integration_max_bytes: int = 1_000_000
    # Outbound FHIR (alerts → Communication, surveys → QuestionnaireResponse). Empty = simulated delivery.
    outbound_fhir_url: str = ""
    outbound_fhir_token: str = ""

    seed_on_startup: bool = True
    # Includes the Android app's WebView origins (Capacitor serves the bundled app from https://localhost).
    cors_origins: str = "http://localhost:5173,http://localhost:8080,https://localhost,capacitor://localhost"

    # Illustrative program targets from the BRD (configurable, not guarantees)
    target_checkin_completion: float = 0.70
    target_medication_adherence: float = 0.90
    target_followup_attendance: float = 0.90
    target_red_alert_contact_minutes: int = 15

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def fernet_key(self) -> bytes:
        if self.field_encryption_key:
            return self.field_encryption_key.encode()
        # Dev/test only: derive a stable key from the JWT secret.
        return base64.urlsafe_b64encode(hashlib.sha256(("fernet:" + self.jwt_secret).encode()).digest())

    def validate_for_runtime(self) -> None:
        if self.is_production:
            problems = []
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be a strong secret in production")
            if not self.field_encryption_key:
                problems.append("FIELD_ENCRYPTION_KEY is required in production")
            if self.integration_demo_key == DEV_INTEGRATION_KEY:
                problems.append("INTEGRATION_DEMO_KEY uses the development default")
            if "dev_only" in self.database_url:
                problems.append("DATABASE_URL uses development credentials")
            if problems:
                raise RuntimeError("Insecure production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
