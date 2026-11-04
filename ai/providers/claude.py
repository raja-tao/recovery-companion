"""Claude provider (default) using the official Anthropic Python SDK."""
from __future__ import annotations

import time

from ai.providers.base import LLMProvider, LLMRequest, LLMResponse, LLMUnavailable


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str = "claude-opus-5-5", effort: str = "low", timeout: float = 60.0):
        self.api_key, self.model, self.effort, self.timeout = api_key, model, effort, timeout
        self._client = None

    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout, max_retries=2)
        return self._client

    def generate(self, req: LLMRequest) -> LLMResponse:
        if not self.available():
            raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
        import anthropic

        output_config: dict = {"effort": self.effort}
        if req.json_schema:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        kwargs = dict(
            model=self.model,
            max_tokens=max(req.max_tokens, 4000),  # headroom for adaptive thinking
            system=req.system,
            messages=[{"role": "user", "content": req.user}],
            output_config=output_config,
        )
        start = time.perf_counter()
        try:
            response = self._get_client().messages.create(**kwargs)
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as exc:
            raise LLMUnavailable(f"Claude request failed: {exc.__class__.__name__}") from exc
        latency = int((time.perf_counter() - start) * 1000)

        refused = response.stop_reason == "refusal"
        text = "" if refused else "".join(b.text for b in response.content if b.type == "text")
        return LLMResponse(
            text=text, provider=self.name, model=response.model, latency_ms=latency,
            input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
            refused=refused, raw_stop_reason=response.stop_reason,
        )
