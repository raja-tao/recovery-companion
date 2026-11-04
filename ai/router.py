"""ModelRouter — chooses an LLM (or none) per task and risk level.

Policy (see docs/AI_AGENT_ARCHITECTURE.md):
  * HIGH risk (RED safety level, emergency): NO LLM. Rules engine + templated
    emergency guidance + human escalation only.
  * PATIENT_CLINICAL_QA: configured provider (Claude default) + RAG + validation.
    Falls back to the extractive provider if the provider is unavailable.
  * LOW risk (e.g. care-team summary wording): any configured provider.
The router can only pick *how* an answer is phrased; it is never consulted on
*whether* something is safe — that is the rules/safety layer's job.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai.providers.base import LLMProvider
from ai.providers.claude import ClaudeProvider
from ai.providers.extractive import ExtractiveProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.openai_provider import OpenAIProvider


class Task:
    PATIENT_CLINICAL_QA = "PATIENT_CLINICAL_QA"
    CARE_TEAM_SUMMARY = "CARE_TEAM_SUMMARY"
    EMERGENCY = "EMERGENCY"


@dataclass
class RouteDecision:
    task: str
    risk: str
    provider: LLMProvider | None
    reason: str

    def to_dict(self) -> dict:
        return {"task": self.task, "risk": self.risk, "reason": self.reason,
                "provider": self.provider.name if self.provider else None,
                "model": self.provider.model if self.provider else None}


class ModelRouter:
    def __init__(self, settings, providers: dict[str, LLMProvider] | None = None):
        self.settings = settings
        self.providers = providers or {
            "claude": ClaudeProvider(settings.anthropic_api_key, settings.claude_model, settings.claude_effort,
                                     settings.llm_timeout_seconds),
            "openai": OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.llm_timeout_seconds),
            "ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model),
            "extractive": ExtractiveProvider(),
        }
        self.fallback = self.providers["extractive"]

    def _configured(self) -> LLMProvider:
        preferred = self.providers.get(self.settings.llm_provider, self.fallback)
        if preferred.name == "ollama":
            return preferred  # availability probed lazily at call time
        return preferred if preferred.available() else self.fallback

    def route(self, task: str, risk: str, capability: str = "grounded_generation") -> RouteDecision:
        if risk == "RED" or task == Task.EMERGENCY:
            return RouteDecision(task, risk, None, "High risk: rules engine + templated guidance + human escalation; "
                                                   "LLM not used")
        provider = self._configured()
        if task == Task.PATIENT_CLINICAL_QA:
            reason = (f"Clinical Q&A: {provider.name} + approved-content RAG + response validation"
                      if provider is not self.fallback else
                      "Clinical Q&A: configured LLM unavailable -> deterministic extractive provider (quotes approved content)")
            return RouteDecision(task, risk, provider, reason)
        return RouteDecision(task, risk, provider, f"Low-risk task ({capability}): {provider.name}")


_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        from app.core.config import get_settings

        _router = ModelRouter(get_settings())
    return _router


def set_router(router: ModelRouter | None) -> None:
    """Testing hook."""
    global _router
    _router = router
