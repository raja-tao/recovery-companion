"""Optional local Ollama provider (REST API — Ollama has no official Python SDK requirement here)."""
from __future__ import annotations

import time

import httpx

from ai.providers.base import LLMProvider, LLMRequest, LLMResponse, LLMUnavailable


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str = "llama3.1", timeout: float = 120.0):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    def available(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def generate(self, req: LLMRequest) -> LLMResponse:
        body = {
            "model": self.model, "stream": False, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.user}],
        }
        if req.json_schema:
            body["format"] = req.json_schema
        start = time.perf_counter()
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc
        data = resp.json()
        return LLMResponse(
            text=data.get("message", {}).get("content", ""), provider=self.name, model=self.model,
            input_tokens=data.get("prompt_eval_count", 0), output_tokens=data.get("eval_count", 0),
            latency_ms=int((time.perf_counter() - start) * 1000), raw_stop_reason=data.get("done_reason"),
        )
