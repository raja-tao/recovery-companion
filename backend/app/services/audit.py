"""Audit trail writer. Append-only; the DB trigger rejects UPDATE/DELETE."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.observability import client_ip_var, request_id_var
from app.models import AuditEvent, User


def record(db: Session, action: str, *, actor: User | None = None, patient_id: uuid.UUID | None = None,
           resource_type: str | None = None, resource_id: Any = None, details: dict | None = None,
           outcome: str = "SUCCESS", actor_role: str | None = None) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor.id if actor else None,
        actor_role=actor_role or (actor.role_name if actor else "SYSTEM"),
        actor_email=actor.email if actor else None,
        patient_id=patient_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        details=details or {},
        request_id=request_id_var.get(),
        ip_address=client_ip_var.get(),
    )
    db.add(event)
    db.flush()
    return event
