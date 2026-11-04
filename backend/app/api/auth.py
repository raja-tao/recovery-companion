from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serializers import user_out
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Patient, User
from app.schemas import LoginRequest, LoginResponse, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Constant-time-ish dummy hash so unknown emails take as long as wrong passwords.
_DUMMY_HASH = hash_password("not-a-real-password")


def _patient_id(db: Session, user: User):
    return db.scalar(select(Patient.id).where(Patient.user_id == user.id))


@router.post("/login", response_model=LoginResponse, summary="Authenticate and receive a JWT access token")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit.record(db, "LOGIN_FAILED", outcome="DENIED", details={"email": body.email.lower()},
                     actor_role="ANONYMOUS")
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    user.last_login_at = datetime.now(timezone.utc)
    token, expires = create_access_token(user.id, user.role_name)
    audit.record(db, "LOGIN_SUCCESS", actor=user)
    db.commit()
    return {"access_token": token, "expires_in": expires, "user": user_out(user, _patient_id(db, user))}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(user, _patient_id(db, user))
