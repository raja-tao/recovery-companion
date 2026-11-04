from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LLMUnavailable(RuntimeError):
    """Provider not configured or failed; the caller falls back safely."""


@dataclass
class LLMRequest:
    system: str
    user: str
    json_schema: dict | None = None
    max_tokens: int = 1500
    # Extra structured context some providers (extractive) use directly.
    context: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    refused: bool = False
    raw_stop_reason: str | None = None


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def generate(self, req: LLMRequest) -> LLMResponse: ...
