"""Password hashing, JWT, field-level encryption and RBAC permission model."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# --------------------------------------------------------------------------- JWT
def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, int]:
    s = get_settings()
    expires_in = s.access_token_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": uuid.uuid4().hex,
        "iss": "recovery-companion",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), expires_in


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], issuer="recovery-companion")


# --------------------------------------------------------------------------- encryption
class _Cipher:
    _fernet: Fernet | None = None

    @classmethod
    def get(cls) -> Fernet:
        if cls._fernet is None:
            cls._fernet = Fernet(get_settings().fernet_key())
        return cls._fernet


class EncryptedText(TypeDecorator):
    """Transparently encrypts sensitive free text at rest (Fernet / AES-128-CBC + HMAC).

    Used for clinical notes and patient free-text concerns. In AWS this key would
    live in Secrets Manager / KMS; RDS storage encryption covers everything else.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _Cipher.get().encrypt(str(value).encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return _Cipher.get().decrypt(value.encode()).decode()
        except InvalidToken:
            return "[unreadable: encryption key mismatch]"


# --------------------------------------------------------------------------- RBAC
class Role(str, Enum):
    PATIENT = "PATIENT"
    CAREGIVER = "CAREGIVER"
    NURSE = "NURSE"  # nurse / care manager
    SURGEON = "SURGEON"  # surgeon / physician — the only role that decides treatment
    ADMIN = "ADMIN"


CARE_TEAM_ROLES = {Role.NURSE, Role.SURGEON}


class Perm(str, Enum):
    # patient self-service
    SELF_PLAN_READ = "self:plan:read"
    SELF_CHECKIN = "self:checkin"
    SELF_MEDS = "self:medications"
    SELF_APPOINTMENTS = "self:appointments"
    SELF_ASSISTANT = "self:assistant"
    SELF_CAREGIVERS = "self:caregivers"
    # caregiver
    CAREGIVER_VIEW = "caregiver:view"
    # care team (patient-level clinical data)
    PATIENT_LIST = "patient:list"
    PATIENT_SUMMARY = "patient:summary"
    PATIENT_TIMELINE = "patient:timeline"
    CHECKIN_READ = "checkin:read"
    MEDICATION_READ = "medication:read"
    APPOINTMENT_READ = "appointment:read"
    APPOINTMENT_WRITE = "appointment:write"
    ALERT_READ = "alert:read"
    ALERT_WORK = "alert:work"
    ESCALATION_REVIEW = "escalation:review"
    MEDICATION_TASKS = "medication:tasks"
    MEDICATION_GUIDANCE = "medication:guidance"  # approve missed-dose guidance (treatment decision)
    TRANSPORT_MANAGE = "transport:manage"
    NOTE_WRITE = "note:write"
    NOTE_READ = "note:read"
    MESSAGE_PATIENT = "message:patient"
    PLAN_APPROVE = "plan:approve"
    CONTENT_APPROVE = "content:approve"
    PROTOCOL_APPROVE = "protocol:approve"
    # admin
    USER_MANAGE = "user:manage"
    PROGRAM_MANAGE = "program:manage"
    CONTENT_MANAGE = "content:manage"
    PROTOCOL_MANAGE = "protocol:manage"
    AUDIT_READ = "audit:read"
    ANALYTICS_READ = "analytics:read"
    DEMO_RUN = "demo:run"


_PATIENT = {Perm.SELF_PLAN_READ, Perm.SELF_CHECKIN, Perm.SELF_MEDS, Perm.SELF_APPOINTMENTS,
            Perm.SELF_ASSISTANT, Perm.SELF_CAREGIVERS}
_NURSE = {Perm.PATIENT_LIST, Perm.PATIENT_SUMMARY, Perm.PATIENT_TIMELINE, Perm.CHECKIN_READ,
          Perm.MEDICATION_READ, Perm.APPOINTMENT_READ, Perm.APPOINTMENT_WRITE, Perm.ALERT_READ,
          Perm.ALERT_WORK, Perm.NOTE_WRITE, Perm.NOTE_READ, Perm.MESSAGE_PATIENT, Perm.ANALYTICS_READ,
          Perm.TRANSPORT_MANAGE}
# Treatment decisions belong to the doctor: medication questions, reconciliation and
# missed-dose guidance are doctor work items (there is no pharmacist role).
_SURGEON = {Perm.PATIENT_LIST, Perm.PATIENT_SUMMARY, Perm.PATIENT_TIMELINE, Perm.CHECKIN_READ,
            Perm.MEDICATION_READ, Perm.APPOINTMENT_READ, Perm.ALERT_READ, Perm.ALERT_WORK,
            Perm.ESCALATION_REVIEW, Perm.NOTE_READ, Perm.NOTE_WRITE, Perm.MESSAGE_PATIENT,
            Perm.PLAN_APPROVE, Perm.CONTENT_APPROVE, Perm.PROTOCOL_APPROVE, Perm.MEDICATION_TASKS,
            Perm.MEDICATION_GUIDANCE}
_ADMIN = {Perm.USER_MANAGE, Perm.PROGRAM_MANAGE, Perm.CONTENT_MANAGE, Perm.PROTOCOL_MANAGE,
          Perm.AUDIT_READ, Perm.ANALYTICS_READ, Perm.DEMO_RUN, Perm.PATIENT_LIST, Perm.CONTENT_APPROVE}

ROLE_PERMISSIONS: dict[Role, set[Perm]] = {
    Role.PATIENT: _PATIENT,
    Role.CAREGIVER: {Perm.CAREGIVER_VIEW},
    Role.NURSE: _NURSE | {Perm.DEMO_RUN},
    Role.SURGEON: _SURGEON,
    Role.ADMIN: _ADMIN,
}


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


# Caregiver scopes a patient may grant (minimum necessary — no clinical notes, no
# check-in free text, no medication details beyond reminders).
CAREGIVER_SCOPES = {
    "RECOVERY_STATUS": "Overall recovery status and phase",
    "TASKS": "Today's recovery tasks",
    "REMINDERS": "Approved reminders (medication times, check-in, appointments)",
    "PROGRESS": "Basic recovery progress",
    "APPOINTMENTS": "Upcoming appointment dates and locations",
}
