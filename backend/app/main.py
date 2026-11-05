"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import (
    admin, ai, ai_agents, alerts, auth, caregiver, content, demo, integrations, patients, transport, wellbeing,
)
from app.core.config import get_settings
from app.core.database import SessionLocal, init_schema
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.observability import configure_logging

logger = logging.getLogger("app")

DESCRIPTION = """
**Post-Surgical Recovery Companion — POC API**

⚠️ **Synthetic data only. Not for clinical use.** This system is a recovery companion and care-navigation
assistant. It does not diagnose, prescribe, or change treatment.

Authenticate with `POST /api/auth/login`, then click **Authorize** and paste the access token.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    settings.validate_for_runtime()
    init_schema()
    if settings.seed_on_startup:
        from app.seed import is_empty, seed

        db = SessionLocal()
        try:
            if is_empty(db):
                logger.info("Seeding synthetic data…")
                result = seed(db)
                db.commit()
                logger.info("Seed complete", extra={"extra_fields": result})
            from app.services.integrations import ensure_sources

            from app.services import upgrades

            # Both also upgrade databases created by earlier versions.
            if ensure_sources(db) + upgrades.run(db):
                db.commit()
        finally:
            db.close()
    task = None
    if settings.enable_scheduler:
        from app.services.scheduler import scheduler_loop

        task = asyncio.create_task(scheduler_loop(settings.scheduler_interval_seconds))
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Post-Surgical Recovery Companion API", version="0.1.0", description=DESCRIPTION,
        lifespan=lifespan, docs_url=f"{s.api_prefix}/docs", redoc_url=f"{s.api_prefix}/redoc",
        openapi_url=f"{s.api_prefix}/openapi.json",
    )
    # Middleware order: outermost first in execution = last added.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_credentials=False, allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
    app.add_middleware(RequestContextMiddleware)

    for r in (auth.router, patients.router, ai.router, caregiver.router, alerts.router, content.router,
              admin.router, ai_agents.router, integrations.router, transport.router, wellbeing.router, demo.router):
        app.include_router(r, prefix=s.api_prefix)

    if s.static_dir:
        _serve_web_app(app, Path(s.static_dir).resolve())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Don't echo submitted values back (may contain PHI).
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


def _serve_web_app(app: FastAPI, root: Path) -> None:
    """Serve the built SPA: real files as-is, every other non-API path → index.html (client-side routing)."""
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str):
        if path.startswith((get_settings().api_prefix.strip("/") + "/", "assets/")) and not (root / path).is_file():
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
