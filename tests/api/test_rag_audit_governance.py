"""RAG retrieval governance, document lifecycle, protocols, audit immutability, analytics, jobs, demo."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from rag.retrieval import retrieve


def test_retrieval_only_approved_active_in_date(db):
    r = retrieve(db, "When can I drive?", "TKA")
    assert r.found
    titles = {c.title for c in r.chunks}
    assert not any("EXPIRED" in t or "DRAFT" in t for t in titles)
    assert all(c.authority in ("SURGEON_APPROVED", "HOSPITAL_APPROVED", "PROGRAM_APPROVED") for c in r.chunks)
    assert "1 week" not in r.chunks[0].content  # expired 2023 guidance never returned


def test_retrieval_filters_by_procedure(db):
    r = retrieve(db, "hip precautions", "TKA")
    assert not any("Hip Replacement" in c.title for c in r.chunks)
    r = retrieve(db, "hip precautions", "THA")
    assert r.chunks[0].section == "Hip precautions"


def test_draft_content_not_retrievable(db):
    r = retrieve(db, "return to skiing and tennis", "TKA")
    assert not any("skiing" in c.content.lower() for c in r.chunks)


def test_unrelated_query_returns_nothing(db):
    assert not retrieve(db, "scuba diving certification", "TKA").found


@pytest.mark.parametrize("question,section", [
    ("When can I drive?", "Driving"), ("Can I shower?", "Showering and bathing"),
    ("When does physical therapy start?", "Physical therapy (PT)"), ("how should I sleep", "Sleeping position"),
    ("ice for swelling", "Swelling and ice"), ("going up stairs", "Stairs"),
])
def test_retrieval_top_section(db, question, section):
    assert retrieve(db, question, "TKA").chunks[0].section == section


def test_document_upload_approve_retire_lifecycle(client, tokens):
    body = {"document_key": "tka-gardening-faq", "title": "Gardening after Knee Replacement", "doc_type": "FAQ",
            "authority": "SURGEON_APPROVED", "author": "Ortho (synthetic)", "procedure_type": "TKA",
            "content": "# Gardening\n\n## Gardening\nYou may do light gardening while standing after 6 weeks. "
                       "Avoid kneeling on the operated knee until your surgeon says it is okay."}
    r = client.post("/api/documents", headers=tokens["admin"], json=body)
    assert r.status_code == 201 and r.json()["approval_status"] == "PENDING"
    doc_id = r.json()["id"]
    ask = lambda: client.post("/api/documents/search", headers=tokens["admin"],  # noqa: E731
                              json={"query": "Can I do gardening?", "procedure_type": "TKA"}).json()
    assert not any(x["document_key"] == "tka-gardening-faq" for x in ask()["results"])
    # admin (uploader) cannot approve; surgeon-approved content needs a surgeon
    assert client.post(f"/api/documents/{doc_id}/approve", headers=tokens["admin"]).status_code == 409
    assert client.post(f"/api/documents/{doc_id}/approve", headers=tokens["nurse"]).status_code == 403
    r = client.post(f"/api/documents/{doc_id}/approve", headers=tokens["doctor"])
    assert r.status_code == 200 and r.json()["is_active"]
    assert any(x["document_key"] == "tka-gardening-faq" for x in ask()["results"])
    # new version supersedes old
    r2 = client.post("/api/documents", headers=tokens["admin"], json=body | {"content": body["content"] + " v2"}).json()
    assert r2["version"] == 2
    client.post(f"/api/documents/{r2['id']}/approve", headers=tokens["doctor"])
    docs = {d["id"]: d for d in client.get("/api/documents", headers=tokens["admin"]).json()}
    assert docs[doc_id]["approval_status"] == "RETIRED" and docs[r2["id"]]["is_active"]
    client.post(f"/api/documents/{r2['id']}/retire", headers=tokens["admin"])
    assert not any(x["document_key"] == "tka-gardening-faq" for x in ask()["results"])
    detail = client.get(f"/api/documents/{r2['id']}", headers=tokens["admin"]).json()
    assert detail["chunks"] and detail["checksum"]


def test_document_file_upload(client, tokens):
    files = {"file": ("faq.md", b"# FAQ\n\n## Pets\nKeep pets off the bed for the first 2 weeks.", "text/markdown")}
    data = {"document_key": "pets-faq", "title": "Pets FAQ", "doc_type": "FAQ", "authority": "PROGRAM_APPROVED",
            "author": "Program team"}
    r = client.post("/api/documents/upload", headers=tokens["admin"], files=files, data=data)
    assert r.status_code == 201, r.text
    bad = client.post("/api/documents/upload", headers=tokens["admin"],
                      files={"file": ("x.exe", b"MZ", "application/octet-stream")}, data=data)
    assert bad.status_code == 415


def test_protocol_governance(client, tokens):
    body = {"rule_id": "AMBER-TEST-RULE", "name": "Test", "severity": "AMBER",
            "condition": {"fact": "pain_score", "op": ">=", "value": 9}, "response_minutes": 60}
    r = client.post("/api/protocols", headers=tokens["admin"], json=body)
    assert r.status_code == 201 and r.json()["status"] == "DRAFT"
    assert client.post(f"/api/protocols/{r.json()['id']}/approve", headers=tokens["admin"]).status_code == 403
    assert client.post(f"/api/protocols/{r.json()['id']}/approve", headers=tokens["doctor"]).json()["status"] == "APPROVED"
    bad = client.post("/api/protocols", headers=tokens["admin"], json=body | {"condition": {"fact": "x", "op": "~"}})
    assert bad.status_code == 422


def test_draft_protocol_not_used(db):
    from agents.checkin_analysis import approved_protocols

    fever = [p for p in approved_protocols(db) if p.rule_id == "RED-FEVER"]
    assert len(fever) == 1 and fever[0].condition["value"] == 101.0  # v2 (100.9) is DRAFT


def test_audit_is_immutable(db):
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_events SET action = 'TAMPERED'"))
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_events"))
    db.rollback()


def test_audit_log_contents_and_api_is_read_only(client, tokens):
    events = client.get("/api/audit?action=AI_ASSISTANT", headers=tokens["admin"]).json()
    assert events
    d = events[0]["details"]
    for key in ("request", "response", "safety_classification", "model", "prompt_version", "retrieved_documents",
                "alert_generated", "rule_triggered"):
        assert key in d
    actions = {e["action"] for e in client.get("/api/audit?limit=1000", headers=tokens["admin"]).json()}
    assert {"LOGIN_SUCCESS", "CHECKIN_SUBMITTED", "ALERT_CREATED", "CARE_TEAM_ACKNOWLEDGE"} <= actions
    spec = client.get("/api/openapi.json").json()["paths"]
    audit_methods = {m for p, ops in spec.items() if p.startswith("/api/audit") for m in ops}
    assert audit_methods == {"get"}


def test_analytics_targets(client, tokens):
    a = client.get("/api/analytics", headers=tokens["admin"]).json()
    names = [k["name"] for k in a["kpis"]]
    assert names == ["Check-in completion", "Medication adherence", "Follow-up attendance",
                     "RED alert → nurse contact (median)"]
    targets = {k["name"]: k["target"] for k in a["kpis"]}
    assert targets["Check-in completion"] == 0.7 and targets["RED alert → nurse contact (median)"] == 15
    assert a["ai"]["responses"] > 0 and "synthetic" in a["disclaimer"].lower()


def test_scheduler_jobs_idempotent(client, tokens):
    r1 = client.post("/api/admin/jobs/run", headers=tokens["admin"]).json()
    r2 = client.post("/api/admin/jobs/run", headers=tokens["admin"]).json()
    assert r2["missed_checkins_recorded"] == 0 and r2["reminders_sent"] == 0
    assert set(r1) == {"missed_checkins_recorded", "reminders_sent", "sla_breaches", "programs_completed",
                       "transport_asked", "ride_reminders", "transport_tasks", "outbound_delivered"}
    assert r2["transport_asked"] == 0 and r2["outbound_delivered"] == 0


def test_missed_checkins_create_amber(client, tokens):
    wl = client.get("/api/care-team/worklist", headers=tokens["nurse"]).json()
    mary = [i for i in wl["items"] if i["patient_name"] == "Mary Smith"]
    assert mary and mary[0]["category"] == "MISSED_CHECKIN" and mary[0]["severity"] == "AMBER"


def test_metrics_endpoint(client, tokens):
    r = client.get("/api/metrics", headers=tokens["admin"])
    assert r.status_code == 200 and "http_requests_total" in r.text


def test_all_demo_scenarios_pass(client, tokens):
    r = client.post("/api/demo/scenarios/run-all", headers=tokens["admin"]).json()
    failed = [(x["scenario"], [s for s in x["steps"] if not s["passed"]]) for x in r["results"] if not x["passed"]]
    assert r["passed"], failed
    assert len(r["results"]) == 8
