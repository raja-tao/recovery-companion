"""Knowledge Retrieval Agent + Patient Education Agent.

Retrieval returns only approved/active/in-date chunks. Education generates a
grounded answer with the routed LLM, validates it, and falls back to the
extractive provider (verbatim quotes) if the LLM output fails validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ai.prompts import GROUNDED_QA_SCHEMA, GROUNDED_QA_SYSTEM, PROMPT_VERSION, grounded_qa_user
from ai.providers.base import LLMRequest, LLMUnavailable
from ai.providers.extractive import ExtractiveProvider
from ai.router import ModelRouter, Task
from ai.validation import validate_answer
from app.core.observability import metrics
from rag.retrieval import RetrievalResult, retrieve


class KnowledgeRetrievalAgent:
    def search(self, db: Session, question: str, procedure_type: str | None) -> RetrievalResult:
        result = retrieve(db, question, procedure_type)
        metrics.inc("rag_queries", found=str(result.found).lower())
        return result


@dataclass
class GroundedAnswer:
    answerable: bool
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    validation_issues: list[str] = field(default_factory=list)
    route: dict = field(default_factory=dict)
    fallback_used: bool = False


class PatientEducationAgent:
    def __init__(self, router: ModelRouter):
        self.router = router

    def answer(self, question: str, sources: list[dict], patient_ctx: dict, risk: str,
               extra_citations: dict | None = None) -> GroundedAnswer:
        """sources: [{id,title,section,content,citation}] — all already approved."""
        decision = self.router.route(Task.PATIENT_CLINICAL_QA, risk)
        if not sources or decision.provider is None:
            return GroundedAnswer(False, route=decision.to_dict())
        req = LLMRequest(system=GROUNDED_QA_SYSTEM, user=grounded_qa_user(question, sources, patient_ctx),
                         json_schema=GROUNDED_QA_SCHEMA, max_tokens=800,
                         context={"question": question, "sources": sources})
        provider = decision.provider
        fallback_used = False
        try:
            resp = provider.generate(req)
        except LLMUnavailable:
            provider, fallback_used = ExtractiveProvider(), True
            resp = provider.generate(req)
        metrics.observe("ai_latency_ms", resp.latency_ms, provider=resp.provider)
        metrics.inc("ai_tokens", resp.input_tokens, provider=resp.provider, kind="input")
        metrics.inc("ai_tokens", resp.output_tokens, provider=resp.provider, kind="output")

        validation = validate_answer(resp.text, sources) if not resp.refused else None
        issues = validation.issues if validation else ["provider_refusal"]
        if validation is None or not validation.ok:
            # Unsafe/ungrounded LLM output is never shown. Retry deterministically.
            metrics.inc("ai_validation_failures", provider=resp.provider)
            if provider.name != "extractive":
                fallback_used = True
                resp = ExtractiveProvider().generate(req)
                validation = validate_answer(resp.text, sources)
            if validation is None or not validation.ok:
                return GroundedAnswer(False, provider=resp.provider, model=resp.model, validation_issues=issues,
                                      route=decision.to_dict(), fallback_used=fallback_used)
        by_id = {s["id"]: s for s in sources}
        citations = [by_id[sid]["citation"] for sid in validation.source_ids] if validation.answerable else []
        return GroundedAnswer(
            answerable=validation.answerable, answer=validation.answer, citations=citations,
            provider=resp.provider, model=resp.model, latency_ms=resp.latency_ms,
            input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
            validation_issues=issues if fallback_used else [], route=decision.to_dict(), fallback_used=fallback_used,
        )


def sources_from_retrieval(result: RetrievalResult) -> list[dict]:
    return [{"id": f"S{i + 1}", "title": c.title, "section": c.section, "content": c.content,
             "citation": c.citation()} for i, c in enumerate(result.chunks)]
