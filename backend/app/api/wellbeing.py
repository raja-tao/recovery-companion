"""Wellbeing (mood asked at each sign-in) and patient-reported outcome surveys."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.wellbeing import FEELINGS, MOODS, WellbeingAgent
from app.api.deps import get_current_user, patient_access
from app.api.serializers import iso
from app.core.database import get_db
from app.core.security import Perm
from app.models import MoodEntry, PromResponse, User
from app.schemas import MoodCreate, SurveySubmit
from app.services import audit, outbound, proms
from app.services.patients import active_episode, recovery_day

router = APIRouter(tags=["Wellbeing & surveys"])


def mood_out(m: MoodEntry) -> dict:
    return {"id": str(m.id), "recorded_at": iso(m.recorded_at), "mood": m.mood, "score": m.score,
            "label": MOODS[m.mood][1], "emoji": MOODS[m.mood][2], "feelings": m.feelings, "note": m.note,
            "alert_id": str(m.alert_id) if m.alert_id else None}


@router.get("/wellbeing/options", summary="Mood and feeling choices for the sign-in question")
def options(user: User = Depends(get_current_user)):
    return {"moods": [{"key": k, "score": s, "label": label, "emoji": e} for k, (s, label, e) in MOODS.items()],
            "feelings": [{"key": k, "label": v} for k, v in FEELINGS.items()]}


@router.get("/patients/{patient_id}/mood", summary="Mood history (patient, nurses and doctors)")
def mood_history(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 days: int = Query(30, ge=1, le=90)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=Perm.CHECKIN_READ,
                       audit_action="PHI_VIEW_MOOD")
    db.commit()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(select(MoodEntry).where(MoodEntry.patient_id == p.id, MoodEntry.recorded_at >= since)
                      .order_by(MoodEntry.recorded_at.desc())).all()
    scores = [r.score for r in rows]
    return {"entries": [mood_out(r) for r in rows],
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "low_days": WellbeingAgent()._low_days(db, p, datetime.now(timezone.utc))}


@router.post("/patients/{patient_id}/mood", summary="Record how the patient feels (asked at sign-in)")
def record_mood(patient_id: uuid.UUID, body: MoodCreate, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=None)
    unknown = [f for f in body.feelings if f not in FEELINGS]
    if unknown:
        raise HTTPException(422, f"Unknown feelings: {', '.join(unknown)}")
    entry, reply = WellbeingAgent().record(db, user, p, body.mood, body.feelings, body.note, body.contact_me)
    audit.record(db, "MOOD_RECORDED", actor=user, patient_id=p.id, resource_type="mood_entry", resource_id=entry.id,
                 details={"mood": body.mood, "feelings": entry.feelings, "has_note": bool(body.note),
                          "level": reply.level, "alert": reply.alert_id, "contact_me": body.contact_me})
    db.commit()
    return {"entry": mood_out(entry), "reply": {"message": reply.message, "level": reply.level,
                                                "actions": reply.actions, "nudges": reply.nudges,
                                                "alert_id": reply.alert_id}}


# --------------------------------------------------------------------------- PROMs
@router.get("/patients/{patient_id}/surveys", summary="Outcome surveys due / completed for this patient")
def surveys(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=Perm.CHECKIN_READ)
    ep = active_episode(db, p.id)
    return proms.surveys_for(db, p.id, ep.procedure_type if ep else None, recovery_day(ep) if ep else None)


@router.get("/surveys/{instrument}", summary="Survey questions")
def survey_definition(instrument: str, user: User = Depends(get_current_user)):
    if instrument not in proms.INSTRUMENTS:
        raise HTTPException(404, "Unknown survey")
    return proms.definition(instrument)


@router.post("/patients/{patient_id}/surveys/{instrument}/{timepoint}", summary="Submit an outcome survey")
def submit_survey(patient_id: uuid.UUID, instrument: str, timepoint: str, body: SurveySubmit,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_CHECKIN, staff_perm=None)
    ep = active_episode(db, p.id)
    if not ep or proms.instrument_for(ep.procedure_type) != instrument or timepoint not in proms.TIMEPOINTS:
        raise HTTPException(404, "This survey is not part of your program")
    day = recovery_day(ep)
    if not proms.window_contains(timepoint, day):
        raise HTTPException(409, "This survey isn't open today")
    try:
        raw, max_score = proms.score(instrument, body.answers)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    ids = {i for i, _, _ in proms.INSTRUMENTS[instrument]["items"]}
    r = PromResponse(patient_id=p.id, episode_id=ep.id, instrument=instrument, timepoint=timepoint, recovery_day=day,
                     answers={k: v for k, v in body.answers.items() if k in ids}, raw_score=raw, max_score=max_score,
                     submitted_by_id=user.id)
    try:
        with db.begin_nested():
            db.add(r)
            db.flush()
    except IntegrityError:
        raise HTTPException(409, "You've already completed this survey") from None
    queued = outbound.queue_prom(db, r, p)
    audit.record(db, "PROM_SUBMITTED", actor=user, patient_id=p.id, resource_type="prom_response", resource_id=r.id,
                 details={"instrument": instrument, "timepoint": timepoint, "raw_score": raw,
                          "outbound": str(queued.id) if queued else None})
    db.commit()
    return {"id": str(r.id), "raw_score": raw, "max_score": max_score,
            "message": "Thank you — your answers help your surgeon track your recovery."}
