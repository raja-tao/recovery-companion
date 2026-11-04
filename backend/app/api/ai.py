from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.orchestrator import RecoveryAssistantOrchestrator
from app.api.deps import my_patient, patient_access, require
from app.api.serializers import message_out
from app.core.database import get_db
from app.core.security import Perm
from app.models import Conversation, Message, User
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["AI Recovery Assistant"])


def _ask(db: Session, user: User, patient_id: uuid.UUID, text: str) -> dict:
    patient = patient_access(db, user, patient_id, self_perm=Perm.SELF_ASSISTANT, staff_perm=None)
    reply = RecoveryAssistantOrchestrator().ask(db, user, patient, text)
    db.commit()
    return reply.to_dict()


@router.post("/ai/chat", response_model=ChatResponse,
             summary="Ask the Recovery Assistant (approved content only, safety-classified, audited)")
def chat(body: ChatRequest, user: User = Depends(require(Perm.SELF_ASSISTANT)), db: Session = Depends(get_db)):
    patient = my_patient(db, user)
    return _ask(db, user, patient.id, body.message)


@router.post("/patients/{patient_id}/questions", response_model=ChatResponse, tags=["Patients"],
             summary="Ask a question about approved recovery content (alias of /ai/chat)")
def question(patient_id: uuid.UUID, body: ChatRequest, user: User = Depends(require(Perm.SELF_ASSISTANT)),
             db: Session = Depends(get_db)):
    return _ask(db, user, patient_id, body.message)


@router.get("/ai/conversation", summary="Assistant conversation history for the current patient")
def history(user: User = Depends(require(Perm.SELF_ASSISTANT)), db: Session = Depends(get_db)):
    patient = my_patient(db, user)
    conv = db.scalars(select(Conversation).where(Conversation.patient_id == patient.id,
                                                 Conversation.channel == "ASSISTANT")).first()
    if not conv:
        return []
    msgs = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
                      .limit(200)).all()
    return [message_out(m) for m in msgs]
