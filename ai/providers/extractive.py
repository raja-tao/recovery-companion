"""Deterministic offline provider.

Used when no LLM is configured (and in tests). It never generates new prose: it
quotes the most relevant sentences from the approved chunks supplied in
`req.context["sources"]`, so it is grounded by construction.
"""
from __future__ import annotations

import json
import re
import time

from ai.providers.base import LLMProvider, LLMRequest, LLMResponse
from rag.text import content_terms

MIN_COVERAGE = 0.6


def _sentences(text: str) -> list[str]:
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


class ExtractiveProvider(LLMProvider):
    name = "extractive"
    model = "extractive-grounded-v1"

    def available(self) -> bool:
        return True

    def generate(self, req: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        question = req.context.get("question", "")
        sources: list[dict] = req.context.get("sources", [])
        q_terms = set(content_terms(question))
        answer, used, answerable = "", [], False

        if sources and q_terms:
            best = sources[0]
            coverage = len(q_terms & set(content_terms(best["section"] + " " + best["content"]))) / len(q_terms)
            if coverage >= MIN_COVERAGE:
                ranked = []
                for i, sent in enumerate(_sentences(best["content"])):
                    overlap = len(q_terms & set(content_terms(sent)))
                    ranked.append((overlap, -i, sent))
                ranked.sort(reverse=True)
                chosen = [s for o, _, s in ranked[:3] if o > 0] or [ranked[0][2]]
                # Keep original document order for readability.
                order = {s: i for i, s in enumerate(_sentences(best["content"]))}
                chosen.sort(key=lambda s: order.get(s, 0))
                answer = " ".join(chosen)
                used = [best["id"]]
                answerable = True

        text = json.dumps({"answerable": answerable, "answer": answer, "source_ids": used})
        return LLMResponse(text=text, provider=self.name, model=self.model,
                           latency_ms=int((time.perf_counter() - start) * 1000))
