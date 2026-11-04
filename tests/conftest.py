"""Shared fixtures. DB tests run against the separate `recovery_test` database,
which is dropped, recreated and seeded once per session."""
from __future__ import annotations

import os
import uuid

import pytest

# Must be set before the app/settings are imported.
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.update({
    "APP_ENV": "test", "SEED_ON_STARTUP": "false", "ENABLE_SCHEDULER": "false", "LLM_PROVIDER": "extractive",
    "RATE_LIMIT_PER_MINUTE": "100000", "RATE_LIMIT_AI_PER_MINUTE": "100000", "RATE_LIMIT_LOGIN_PER_MINUTE": "100000",
})

PASSWORD = "Recovery#2026"


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.core.database import get_engine

        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def seeded_db():
    if not _db_available():
        pytest.skip("PostgreSQL not available (run tests with `make test`)")
    from app.core.database import SessionLocal
    from app.seed import reset_schema, seed

    reset_schema()
    db = SessionLocal()
    try:
        seed(db)
        db.commit()
    finally:
        db.close()
    return True


@pytest.fixture()
def db(seeded_db):
    from app.core.database import SessionLocal

    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def client(seeded_db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)  # no lifespan: schema/seed handled by fixtures


def login(client, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def tokens(client):
    return {role: login(client, f"{role}@example.com")
            for role in ("patient", "nurse", "doctor", "admin", "caregiver")}


@pytest.fixture()
def fresh_patient(seeded_db):
    """A brand-new synthetic patient with a known password: returns (patient_id, headers_factory)."""
    from app.api.demo import make_demo_patient
    from app.core.database import SessionLocal
    from app.core.security import hash_password

    db = SessionLocal()
    try:
        p, u = make_demo_patient(db, f"T{uuid.uuid4().hex[:4]}")
        u.password_hash = hash_password(PASSWORD)
        db.commit()
        return {"id": str(p.id), "email": u.email}
    finally:
        db.close()


NORMAL = {"pain_score": 3, "pain_trend": "BETTER", "temperature": 98.4, "wound_appearance": "HEALING_WELL",
          "swelling": "SAME", "mobility": "WITH_AID", "walking_minutes": 40, "medication_adherence": "ALL",
          "new_symptoms": ["NONE"]}
