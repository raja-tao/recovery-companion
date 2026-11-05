"""HTTP middleware: request IDs, structured access logs + latency metrics, security
headers and a sliding-window rate limiter (in-memory for the POC; use Redis /
API Gateway / WAF rate-based rules in AWS)."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.observability import client_ip_var, log_event, metrics, request_id_var

logger = logging.getLogger("http")


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id_var.set(rid)
        fwd = request.headers.get("x-forwarded-for")
        client_ip_var.set(fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None))
        start = time.perf_counter()
        response: Response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        route = _route_label(request)
        metrics.observe("http_request_duration_ms", ms, method=request.method, route=route)
        metrics.inc("http_requests", method=request.method, route=route, status=str(response.status_code))
        if not request.url.path.endswith(("/health", "/metrics")):
            log_event(logger, "request", method=request.method, path=request.url.path, route=route,
                      status=response.status_code, duration_ms=round(ms, 1))
        response.headers["X-Request-ID"] = rid
        return response


SPA_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
           "font-src 'self' https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if not request.url.path.startswith(get_settings().api_prefix + "/"):
            # The web app itself (single-service deploys): same policy as docker/nginx.conf.
            h.setdefault("Content-Security-Policy", SPA_CSP)
        elif request.url.path.endswith(("/docs", "/redoc")):
            h.setdefault("Content-Security-Policy", "default-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                                    "img-src 'self' data: https://fastapi.tiangolo.com")
        else:
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            h.setdefault("Cache-Control", "no-store")  # PHI must not be cached by intermediaries
        if get_settings().is_production:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def _limit_for(self, path: str) -> tuple[str, int]:
        s = get_settings()
        if path.endswith("/auth/login"):
            return "login", s.rate_limit_login_per_minute
        if "/ai/" in path or path.endswith("/questions"):
            return "ai", s.rate_limit_ai_per_minute
        return "global", s.rate_limit_per_minute

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path.endswith("/health"):
            return await call_next(request)
        bucket, limit = self._limit_for(request.url.path)
        ip = client_ip_var.get() or (request.client.host if request.client else "unknown")
        key = f"{bucket}:{ip}"
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                metrics.inc("rate_limited", bucket=bucket)
                return JSONResponse({"detail": "Too many requests. Please wait a moment."}, status_code=429,
                                    headers={"Retry-After": "60"})
            q.append(now)
        return await call_next(request)

    def reset(self):
        with self.lock:
            self.hits.clear()
