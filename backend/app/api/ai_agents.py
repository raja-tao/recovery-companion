"""Admin view of the AI agents: catalog, live configuration and activity from the audit trail."""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from agents.catalog import AGENTS, COMPONENTS, WORKFLOWS, agents_for
from app.api.deps import require
from app.api.serializers import iso
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import Perm
from app.models import AuditEvent, User
from app.services import audit

router = APIRouter(tags=["Administration"])

NON_LLM_PROVIDERS = {None, "extractive", "rules-engine"}
RECENT_PER_AGENT = 10


def _activity_filter(entry: dict):
    cond = AuditEvent.action == entry["action"]
    if "field" in entry:
        cond = and_(cond, AuditEvent.details[entry["field"]].as_string().in_(entry["values"]))
    return cond


def _config() -> dict:
    from ai.router import get_router

    s = get_settings()
    active = get_router()._configured()
    return {
        "llm": {
            "provider_configured": s.llm_provider, "provider_active": active.name, "model_active": active.model,
            "fallback_active": active.name != s.llm_provider,
            "claude_model": s.claude_model, "claude_effort": s.claude_effort,
            "anthropic_api_key_set": bool(s.anthropic_api_key),
            "openai_model": s.openai_model, "openai_api_key_set": bool(s.openai_api_key),
            "ollama_base_url": s.ollama_base_url, "ollama_model": s.ollama_model,
            "timeout_seconds": s.llm_timeout_seconds, "prompt_version": s.prompt_version,
        },
        "rag": {"embedding_provider": s.embedding_provider, "embedding_dim": s.embedding_dim,
                "top_k": s.rag_top_k, "min_score": s.rag_min_score},
    }


def _summary(e: AuditEvent) -> str:
    d = e.details or {}
    if e.action == "AI_ASSISTANT_RESPONSE":
        return f"{d.get('intent')} · {d.get('final_safety_level')} · {d.get('provider') or 'no model'}"
    if e.action == "ALERT_REPEAT_TRIGGER":
        rules = d.get("rules") or [d.get("rule_id")]
        return f"Merged into open alert · {', '.join(r for r in rules if r)}"
    if e.action == "ALERT_CREATED":
        return f"{d.get('severity', '')} {d.get('category', '')} → {d.get('assigned_team', '')}".strip()
    if e.action == "CHECKIN_SUBMITTED":
        rules = d.get("rules_triggered") or []
        return f"Day {d.get('recovery_day')} · {d.get('risk_level')} · {len(rules)} rule(s) triggered"
    if e.action.startswith("PLAN_VERSION"):
        return f"Version {d.get('version')}"
    return e.resource_type or ""


@router.get("/admin/ai-agents", summary="AI agents: catalog, configuration and activity (admin)")
def ai_agents(user: User = Depends(require(Perm.AUDIT_READ)), db: Session = Depends(get_db),
              days: int = Query(30, ge=1, le=365)):
    now = datetime.now(timezone.utc)
    since, day_ago = now - timedelta(days=days), now - timedelta(days=1)

    # Counted in SQL: scheduled jobs can write thousands of alert events, so rows are never loaded for counting.
    # Recent events are taken per agent so one busy agent can't push the others off the list.
    agents, recent_rows = [], {}
    for a in AGENTS:
        total, last_24h, last_at = 0, 0, None
        for entry in a["activity"]:
            n, n24, last = db.execute(select(
                func.count(), func.count().filter(AuditEvent.occurred_at >= day_ago), func.max(AuditEvent.occurred_at))
                .where(_activity_filter(entry), AuditEvent.occurred_at >= since)).one()
            total, last_24h = total + n, last_24h + n24
            last_at = max(filter(None, (last_at, last)), default=None)
        agents.append(a | {"activity_counts": {"total": total, "last_24h": last_24h, "last_at": iso(last_at)}})
        for e in db.scalars(select(AuditEvent).where(or_(*map(_activity_filter, a["activity"])),
                                                     AuditEvent.occurred_at >= since)
                            .order_by(AuditEvent.occurred_at.desc()).limit(RECENT_PER_AGENT)):
            recent_rows[e.id] = e

    ai = [d or {} for d in db.scalars(select(AuditEvent.details).where(
        AuditEvent.action == "AI_ASSISTANT_RESPONSE", AuditEvent.occurred_at >= since)
        .order_by(AuditEvent.occurred_at.desc()).limit(5000))]
    latencies = [d["latency_ms"] for d in ai if d.get("latency_ms") is not None]
    assistant = {
        "responses": len(ai),
        "llm_calls": sum(1 for d in ai if d.get("provider") not in NON_LLM_PROVIDERS),
        "answered_from_content": sum(1 for d in ai if d.get("answered_from_content")),
        "validation_failures": sum(1 for d in ai if d.get("validation_issues")),
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "tokens": {k: sum((d.get("tokens") or {}).get(k) or 0 for d in ai) for k in ("input", "output")},
        "by_provider": dict(Counter(d.get("provider") or "none" for d in ai)),
        "by_safety_level": dict(Counter(d.get("final_safety_level") or "UNKNOWN" for d in ai)),
        "by_intent": dict(Counter(d.get("intent") or "UNKNOWN" for d in ai)),
    }

    recent = [{"id": str(e.id), "occurred_at": iso(e.occurred_at), "action": e.action, "outcome": e.outcome,
               "actor_email": e.actor_email, "actor_role": e.actor_role,
               "patient_id": str(e.patient_id) if e.patient_id else None,
               "agents": agents_for(e.action, e.details), "summary": _summary(e)}
              for e in sorted(recent_rows.values(), key=lambda e: e.occurred_at, reverse=True)]

    # This view is derived from the audit log, so viewing it is audited like the audit log itself.
    audit.record(db, "AUDIT_LOG_VIEWED", actor=user, details={"view": "ai_agents", "days": days})
    db.commit()
    return {"window_days": days, "config": _config(), "agents": agents, "components": COMPONENTS,
            "workflows": WORKFLOWS, "assistant": assistant, "recent": recent}
