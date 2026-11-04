"""Optional OpenAI provider (official `openai` SDK)."""
from __future__ import annotations

import json
import time

from ai.providers.base import LLMProvider, LLMRequest, LLMResponse, LLMUnavailable


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: float = 60.0):
        self.api_key, self.model, self.timeout = api_key, model, timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, req: LLMRequest) -> LLMResponse:
        if not self.available():
            raise LLMUnavailable("OPENAI_API_KEY not configured")
        from openai import OpenAI, OpenAIError

        client = OpenAI(api_key=self.api_key, timeout=self.timeout)
        system = req.system
        if req.json_schema:
            system += "\n\nRespond ONLY with JSON matching this schema:\n" + json.dumps(req.json_schema)
        start = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=self.model, max_tokens=req.max_tokens, temperature=0,
                response_format={"type": "json_object"} if req.json_schema else None,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": req.user}],
            )
        except OpenAIError as exc:
            raise LLMUnavailable(f"OpenAI request failed: {exc.__class__.__name__}") from exc
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content or "", provider=self.name, model=resp.model,
            input_tokens=usage.prompt_tokens if usage else 0, output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=int((time.perf_counter() - start) * 1000), raw_stop_reason=resp.choices[0].finish_reason,
        )
