"""Structured JSON logging, request context and in-process metrics.

Metrics are exposed in Prometheus text format at /api/metrics. In AWS these map
to CloudWatch (EMF or the CloudWatch agent scraping Prometheus).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, msg: str, **fields) -> None:
    logger.info(msg, extra={"extra_fields": fields})


class Metrics:
    """Tiny thread-safe counter/histogram registry (no external dependency)."""

    _buckets = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000)

    def __init__(self):
        self._lock = threading.Lock()
        self.counters: dict[tuple, float] = defaultdict(float)
        self.hist: dict[tuple, dict] = {}

    @staticmethod
    def _key(name: str, labels: dict) -> tuple:
        return (name, tuple(sorted(labels.items())))

    def inc(self, name: str, value: float = 1, **labels) -> None:
        with self._lock:
            self.counters[self._key(name, labels)] += value

    def observe(self, name: str, value_ms: float, **labels) -> None:
        with self._lock:
            k = self._key(name, labels)
            h = self.hist.setdefault(k, {"count": 0, "sum": 0.0, "buckets": [0] * len(self._buckets)})
            h["count"] += 1
            h["sum"] += value_ms
            for i, b in enumerate(self._buckets):
                if value_ms <= b:
                    h["buckets"][i] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": [{"name": n, "labels": dict(l), "value": v} for (n, l), v in self.counters.items()],
                "histograms": [{"name": n, "labels": dict(l), "count": h["count"],
                                "avg_ms": round(h["sum"] / h["count"], 1) if h["count"] else 0}
                               for (n, l), h in self.hist.items()],
            }

    def prometheus(self) -> str:
        def fmt(labels):
            return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""

        lines = []
        with self._lock:
            for (n, l), v in sorted(self.counters.items()):
                lines.append(f"{n}_total{fmt(l)} {v}")
            for (n, l), h in sorted(self.hist.items()):
                cumulative = 0
                for b, c in zip(self._buckets, h["buckets"]):
                    cumulative = c
                    lines.append(f'{n}_bucket{fmt(l + (("le", str(b)),))} {cumulative}')
                lines.append(f'{n}_bucket{fmt(l + (("le", "+Inf"),))} {h["count"]}')
                lines.append(f"{n}_sum{fmt(l)} {h['sum']}")
                lines.append(f"{n}_count{fmt(l)} {h['count']}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
