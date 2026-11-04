"""Auth + RBAC dependencies. Every patient-scoped endpoint goes through `patient_access`."""
from __future__ import annotations

import uuid
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Perm, Role, decode_access_token, has_perm
from app.models import Caregiver, Patient, User
from app.services import audit

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


def require(*perms: Perm) -> Callable[..., User]:
    """Dependency: user must hold at least one of the permissions."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if not any(has_perm(user.role_name, p) for p in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user
    return checker


def patient_access(db: Session, user: User, patient_id: uuid.UUID, *, self_perm: Perm | None,
                   staff_perm: Perm | None, audit_action: str | None = None) -> Patient:
    """Resolve a patient the caller may access for this purpose, or raise 403/404.

    * PATIENT: only their own record, and only if self_perm allows the action.
    * CAREGIVER: never through these endpoints — caregivers use /caregiver views.
    * Staff: must hold staff_perm (minimum necessary per role). Access is audited.
    """
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    role = user.role_name
    if role == Role.PATIENT.value:
        if patient.user_id != user.id or not self_perm or not has_perm(role, self_perm):
            raise HTTPException(403, "You can only access your own record")
        return patient
    if role == Role.CAREGIVER.value:
        raise HTTPException(403, "Caregivers can only use the caregiver view")
    if not staff_perm or not has_perm(role, staff_perm):
        audit.record(db, "ACCESS_DENIED", actor=user, patient_id=patient.id, outcome="DENIED",
                     details={"required": staff_perm.value if staff_perm else None})
        db.commit()
        raise HTTPException(403, "Insufficient permissions for this patient data")
    if audit_action:
        audit.record(db, audit_action, actor=user, patient_id=patient.id, resource_type="patient",
                     resource_id=patient.id)
    return patient


def my_patient(db: Session, user: User) -> Patient:
    patient = db.scalars(select(Patient).where(Patient.user_id == user.id)).first()
    if not patient:
        raise HTTPException(404, "No patient record linked to this user")
    return patient


def caregiver_link(db: Session, user: User, patient_id: uuid.UUID) -> Caregiver:
    link = db.scalars(select(Caregiver).where(Caregiver.user_id == user.id, Caregiver.patient_id == patient_id,
                                              Caregiver.status == "ACTIVE")).first()
    if not link:
        raise HTTPException(403, "Caregiver access not authorized or has been revoked")
    return link


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
