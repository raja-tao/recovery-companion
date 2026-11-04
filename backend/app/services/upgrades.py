"""Idempotent data upgrades for databases created by earlier versions (no migrations in this POC)."""
from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import ROLE_PERMISSIONS, Role
from app.models import Alert, Escalation, RoleModel, User, WarningProtocol

logger = logging.getLogger("upgrades")


def retire_pharmacist_role(db: Session) -> int:
    """There is no pharmacist role: treatment decisions belong to the doctor.

    Medication work items move to the doctor (SURGEON team) and the pharmacist role and its
    accounts are removed. Audit history is unchanged (append-only).
    """
    changed = 0
    for model, column in ((Alert, Alert.assigned_team), (WarningProtocol, WarningProtocol.assigned_team)):
        changed += db.execute(update(model).where(column == "PHARMACIST").values({column: "SURGEON"})).rowcount
    changed += db.execute(update(Escalation).where(Escalation.to_role == "PHARMACIST")
                          .values(to_role="SURGEON")).rowcount
    role = db.scalars(select(RoleModel).where(RoleModel.name == "PHARMACIST")).first()
    if role:
        for u in db.scalars(select(User).where(User.role_id == role.id)):
            db.delete(u)
            changed += 1
        db.flush()
        db.delete(role)
        changed += 1
    if changed:
        db.flush()
        logger.info("Retired pharmacist role", extra={"extra_fields": {"rows": changed}})
    return changed


def sync_role_permissions(db: Session) -> int:
    """Keep the descriptive `roles.permissions` column in step with the code's RBAC map."""
    changed = 0
    for rm in db.scalars(select(RoleModel)):
        try:
            perms = sorted(p.value for p in ROLE_PERMISSIONS[Role(rm.name)])
        except ValueError:
            continue
        if rm.permissions != perms:
            rm.permissions = perms
            changed += 1
    return changed


def run(db: Session) -> int:
    return retire_pharmacist_role(db) + sync_role_permissions(db)
