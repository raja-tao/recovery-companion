"""Admin AI agents page: catalog, configuration (no secrets) and activity from the audit trail."""
from agents.catalog import AGENTS, WORKFLOWS


def test_ai_agents_admin_only(client, tokens):
    assert client.get("/api/admin/ai-agents").status_code == 401
    for role in ("patient", "caregiver", "nurse", "doctor"):
        assert client.get("/api/admin/ai-agents", headers=tokens[role]).status_code == 403


def test_ai_agents_catalog_config_and_activity(client, tokens):
    client.post("/api/ai/chat", headers=tokens["patient"], json={"message": "When can I shower?"})
    r = client.get("/api/admin/ai-agents?days=7", headers=tokens["admin"])
    assert r.status_code == 200
    body = r.json()

    assert [a["id"] for a in body["agents"]] == [a["id"] for a in AGENTS]
    assert [a["id"] for a in body["agents"] if a["kind"] == "LLM"] == ["patient_education"]
    assert {w["id"] for w in body["workflows"]} == {w["id"] for w in WORKFLOWS}

    llm = body["config"]["llm"]
    assert isinstance(llm["anthropic_api_key_set"], bool)
    assert "anthropic_api_key" not in llm and "openai_api_key" not in llm

    by_id = {a["id"]: a for a in body["agents"]}
    assert by_id["orchestrator"]["activity_counts"]["total"] >= 1
    assert by_id["patient_education"]["activity_counts"]["total"] >= 1
    assert body["assistant"]["responses"] >= 1
    assert any(e["action"] == "AI_ASSISTANT_RESPONSE" and "orchestrator" in e["agents"] for e in body["recent"])


def test_ai_agents_view_is_audited(client, tokens):
    client.get("/api/admin/ai-agents", headers=tokens["admin"])
    events = client.get("/api/audit?action=AUDIT_LOG_VIEWED&limit=5", headers=tokens["admin"]).json()
    assert any(e["details"].get("view") == "ai_agents" for e in events)
