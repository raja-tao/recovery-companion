"""Administration, audit, analytics, notifications, jobs, health and metrics."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require
from app.api.serializers import iso, notification_out
from app.core.config import get_settings
from app.core.database import get_db
from app.core.observability import metrics
from app.core.security import Perm, hash_password
from app.models import AuditEvent, Notification, Program, RoleModel, User
from app.schemas import ProgramCreate, UserCreate
from app.services import audit
from app.services.analytics import program_metrics
from app.services.scheduler import run_all_jobs

router = APIRouter(tags=["Administration"])


@router.get("/health", tags=["System"], summary="Liveness + DB check")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    s = get_settings()
    from ai.router import get_router

    configured = get_router()._configured()
    return {"status": "ok", "env": s.app_env, "llm_provider_configured": s.llm_provider,
            "llm_provider_active": configured.name, "embedding_provider": s.embedding_provider,
            "synthetic_data_only": True}


@router.get("/metrics", tags=["System"], response_class=PlainTextResponse, summary="Prometheus metrics")
def prometheus(user: User = Depends(require(Perm.ANALYTICS_READ, Perm.AUDIT_READ))):
    return metrics.prometheus()


@router.get("/metrics/json", tags=["System"], summary="In-process metrics snapshot")
def metrics_json(user: User = Depends(require(Perm.ANALYTICS_READ, Perm.AUDIT_READ))):
    return metrics.snapshot()


# --------------------------------------------------------------------------- users & programs
@router.get("/admin/users")
def list_users(user: User = Depends(require(Perm.USER_MANAGE)), db: Session = Depends(get_db)):
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role_name, "title": u.title,
             "is_active": u.is_active, "last_login_at": iso(u.last_login_at)}
            for u in db.scalars(select(User).order_by(User.full_name))]


@router.post("/admin/users", status_code=201)
def create_user(body: UserCreate, user: User = Depends(require(Perm.USER_MANAGE)), db: Session = Depends(get_db)):
    if db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first():
        raise HTTPException(409, "Email already exists")
    role = db.scalars(select(RoleModel).where(RoleModel.name == body.role)).one()
    u = User(email=body.email.lower(), full_name=body.full_name, role_id=role.id, title=body.title,
             password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit.record(db, "USER_CREATED", actor=user, resource_type="user", resource_id=u.id,
                 details={"email": u.email, "role": body.role})
    db.commit()
    return {"id": str(u.id), "email": u.email, "role": body.role}


@router.post("/admin/users/{user_id}/active")
def set_active(user_id: uuid.UUID, active: bool, user: User = Depends(require(Perm.USER_MANAGE)),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Not found")
    if u.id == user.id:
        raise HTTPException(409, "You cannot deactivate yourself")
    u.is_active = active
    audit.record(db, "USER_ACTIVATED" if active else "USER_DEACTIVATED", actor=user, resource_type="user",
                 resource_id=u.id)
    db.commit()
    return {"id": str(u.id), "is_active": u.is_active}


@router.get("/admin/programs")
def list_programs(user: User = Depends(require(Perm.PROGRAM_MANAGE, Perm.ANALYTICS_READ)),
                  db: Session = Depends(get_db)):
    return [{"id": str(p.id), "name": p.name, "description": p.description, "procedure_types": p.procedure_types,
             "duration_days": p.duration_days, "targets": p.targets, "is_active": p.is_active}
            for p in db.scalars(select(Program).order_by(Program.name))]


@router.post("/admin/programs", status_code=201)
def create_program(body: ProgramCreate, user: User = Depends(require(Perm.PROGRAM_MANAGE)),
                   db: Session = Depends(get_db)):
    p = Program(**body.model_dump())
    db.add(p)
    db.flush()
    audit.record(db, "PROGRAM_CREATED", actor=user, resource_type="program", resource_id=p.id, details=body.model_dump())
    db.commit()
    return {"id": str(p.id), "name": p.name}


# --------------------------------------------------------------------------- audit (read-only)
@router.get("/audit", summary="Audit trail (read-only; immutable at the DB level)")
def audit_log(user: User = Depends(require(Perm.AUDIT_READ)), db: Session = Depends(get_db),
              action: str | None = None, patient_id: uuid.UUID | None = None, actor_email: str | None = None,
              limit: int = Query(200, le=1000), offset: int = 0):
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action.upper()}%"))
    if patient_id:
        stmt = stmt.where(AuditEvent.patient_id == patient_id)
    if actor_email:
        stmt = stmt.where(AuditEvent.actor_email == actor_email.lower())
    rows = db.scalars(stmt).all()
    # Viewing the audit log is itself audited.
    audit.record(db, "AUDIT_LOG_VIEWED", actor=user, details={"action": action, "patient_id": str(patient_id)
                                                              if patient_id else None})
    db.commit()
    return [{"id": str(e.id), "occurred_at": iso(e.occurred_at), "actor_email": e.actor_email,
             "actor_role": e.actor_role, "patient_id": str(e.patient_id) if e.patient_id else None,
             "action": e.action, "resource_type": e.resource_type, "resource_id": e.resource_id,
             "outcome": e.outcome, "details": e.details, "request_id": e.request_id, "ip_address": e.ip_address}
            for e in rows]


# --------------------------------------------------------------------------- analytics & jobs
@router.get("/analytics", summary="Program metrics vs illustrative BRD targets")
def analytics(user: User = Depends(require(Perm.ANALYTICS_READ)), db: Session = Depends(get_db)):
    return program_metrics(db)


@router.post("/admin/jobs/run", summary="Run scheduled jobs now (missed check-ins, reminders, SLA)")
def run_jobs(user: User = Depends(require(Perm.DEMO_RUN, Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db)):
    result = run_all_jobs(db)
    audit.record(db, "JOBS_RUN", actor=user, details=result)
    db.commit()
    return result


# --------------------------------------------------------------------------- notifications
@router.get("/notifications/me", tags=["Notifications"])
def my_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                     limit: int = Query(30, le=100)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.channel == "IN_APP")
                      .order_by(Notification.created_at.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.channel == "IN_APP", Notification.read_at.is_(None))) or 0
    return {"unread": unread, "items": [notification_out(n) for n in rows]}


@router.post("/notifications/read-all", tags=["Notifications"])
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))):
        n.read_at, n.status = now, "READ"
    db.commit()
    return {"ok": True}
