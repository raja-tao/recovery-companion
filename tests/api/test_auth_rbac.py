"""Authentication, RBAC and minimum-necessary access."""
from sqlalchemy import select

from tests.conftest import login


def test_login_success_and_me(client, tokens):
    r = client.get("/api/auth/me", headers=tokens["patient"])
    assert r.status_code == 200 and r.json()["role"] == "PATIENT" and r.json()["patient_id"]


def test_login_failure_generic_message(client):
    r = client.post("/api/auth/login", json={"email": "patient@example.com", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password"
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password"


def test_requires_token(client):
    assert client.get("/api/patients/me").status_code == 401
    assert client.get("/api/care-team/worklist", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_passwords_are_hashed(db):
    from app.models import User

    u = db.scalars(select(User).where(User.email == "patient@example.com")).one()
    assert u.password_hash.startswith("$2") and "Recovery" not in u.password_hash


def test_patient_cannot_access_other_patient(client, tokens):
    nurse_list = client.get("/api/patients", headers=tokens["nurse"]).json()
    me = client.get("/api/auth/me", headers=tokens["patient"]).json()["patient_id"]
    other = next(p["id"] for p in nurse_list if p["id"] != me)
    for path in ("", "/dashboard", "/checkins", "/medications", "/timeline", "/recovery-plan"):
        assert client.get(f"/api/patients/{other}{path}", headers=tokens["patient"]).status_code == 403


def test_patient_cannot_use_care_team_endpoints(client, tokens):
    for path in ("/api/care-team/worklist", "/api/alerts", "/api/audit", "/api/patients", "/api/documents",
                 "/api/analytics", "/api/admin/users"):
        assert client.get(path, headers=tokens["patient"]).status_code == 403, path


def test_caregiver_cannot_use_patient_endpoints(client, tokens):
    pid = client.get("/api/caregiver/patients", headers=tokens["caregiver"]).json()[0]["patient_id"]
    assert client.get(f"/api/patients/{pid}", headers=tokens["caregiver"]).status_code == 403
    assert client.get(f"/api/patients/{pid}/checkins", headers=tokens["caregiver"]).status_code == 403
    assert client.post("/api/ai/chat", headers=tokens["caregiver"], json={"message": "hi"}).status_code == 403


def test_nurse_can_view_patient_data(client, tokens):
    pid = client.get("/api/patients", headers=tokens["nurse"]).json()[0]["id"]
    for path in ("", "/timeline", "/checkins", "/medications", "/summary", "/alerts", "/notes"):
        assert client.get(f"/api/patients/{pid}{path}", headers=tokens["nurse"]).status_code == 200, path


def test_no_pharmacist_role_medication_work_goes_to_the_doctor(client, tokens):
    from app.core.security import ROLE_PERMISSIONS, Perm, Role

    assert "PHARMACIST" not in {r.value for r in Role}
    assert client.post("/api/auth/login", json={"email": "pharmacist@example.com",
                                                "password": "Recovery#2026"}).status_code == 401
    assert Perm.MEDICATION_GUIDANCE in ROLE_PERMISSIONS[Role.SURGEON]
    assert Perm.MEDICATION_GUIDANCE not in ROLE_PERMISSIONS[Role.NURSE]
    items = client.get("/api/care-team/worklist", headers=tokens["doctor"]).json()["items"]
    med = [i for i in items if i["category"] == "MEDICATION_QUESTION"]
    assert med and all(i["assigned_team"] == "SURGEON" for i in med)


def test_admin_cannot_read_clinical_detail(client, tokens):
    pid = client.get("/api/patients", headers=tokens["admin"]).json()[0]["id"]
    assert client.get(f"/api/patients/{pid}/checkins", headers=tokens["admin"]).status_code == 403
    assert client.get("/api/audit", headers=tokens["admin"]).status_code == 200


def test_denied_access_is_audited(client, tokens, db):
    from app.models import AuditEvent

    pid = client.get("/api/patients", headers=tokens["admin"]).json()[0]["id"]
    client.get(f"/api/patients/{pid}/checkins", headers=tokens["admin"])
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "ACCESS_DENIED")
                    .order_by(AuditEvent.occurred_at.desc())).first()
    assert ev and ev.actor_role == "ADMIN"


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Request-ID"]


def test_rate_limiting_login(client):
    from app.core.config import get_settings

    s = get_settings()
    old = s.rate_limit_login_per_minute
    s.rate_limit_login_per_minute = 3
    try:
        hdr = {"X-Forwarded-For": "203.0.113.77"}
        codes = [client.post("/api/auth/login", json={"email": "x@example.com", "password": "x"}, headers=hdr).status_code
                 for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[-1] == 429
    finally:
        s.rate_limit_login_per_minute = old


def test_input_validation_does_not_echo_values(client, tokens):
    r = client.post("/api/ai/chat", headers=tokens["patient"], json={"message": "x" * 5000})
    assert r.status_code == 422 and "xxxx" not in r.text


def test_openapi_available(client):
    spec = client.get("/api/openapi.json").json()
    for path in ("/api/auth/login", "/api/patients/{patient_id}/checkins", "/api/ai/chat", "/api/care-team/worklist",
                 "/api/alerts/{alert_id}/acknowledge", "/api/documents/{document_id}/approve", "/api/audit"):
        assert path in spec["paths"], path


def test_inactive_user_rejected(client, db, tokens):
    from app.models import User

    hdr = login(client, "nurse2@example.com")
    u = db.scalars(select(User).where(User.email == "nurse2@example.com")).one()
    r = client.post(f"/api/admin/users/{u.id}/active?active=false", headers=tokens["admin"])
    assert r.status_code == 200
    assert client.get("/api/care-team/worklist", headers=hdr).status_code == 401
    client.post(f"/api/admin/users/{u.id}/active?active=true", headers=tokens["admin"])
