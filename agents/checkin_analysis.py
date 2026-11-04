"""Check-in Analysis Agent — validates answers, builds facts, runs the deterministic
rules engine against APPROVED warning protocols, persists results and raises alerts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from agents.alerting import AlertEscalationAgent
from agents.context import IntakeContextAgent
from app.core.observability import metrics
from app.models import (
    Alert, Checkin, CheckinQuestion, CheckinResponse, MedicationEvent, Patient, User, WarningProtocol,
)
from app.services import audit
from app.services.alerts import refresh_patient_risk
from rules.engine import EvaluationResult, ProtocolSpec, build_checkin_facts, evaluate_protocols


def questions_for(db: Session, procedure_type: str | None) -> list[CheckinQuestion]:
    rows = db.scalars(select(CheckinQuestion).where(
        CheckinQuestion.is_active.is_(True),
        or_(CheckinQuestion.procedure_type == "ALL", CheckinQuestion.procedure_type == (procedure_type or "ALL")),
    ).order_by(CheckinQuestion.sort_order)).all()
    # Procedure-specific question overrides the generic one with the same key.
    by_key: dict[str, CheckinQuestion] = {}
    for q in rows:
        if q.key not in by_key or q.procedure_type != "ALL":
            by_key[q.key] = q
    return sorted(by_key.values(), key=lambda q: q.sort_order)


def approved_protocols(db: Session, exclude_categories: tuple[str, ...] = ()) -> list[ProtocolSpec]:
    latest = (select(WarningProtocol.rule_id, func.max(WarningProtocol.version).label("v"))
              .where(WarningProtocol.status == "APPROVED").group_by(WarningProtocol.rule_id).subquery())
    rows = db.scalars(select(WarningProtocol).join(
        latest, (WarningProtocol.rule_id == latest.c.rule_id) & (WarningProtocol.version == latest.c.v))).all()
    return [ProtocolSpec(rule_id=p.rule_id, name=p.name, severity=p.severity, condition=p.condition,
                         response_minutes=p.response_minutes, assigned_team=p.assigned_team, category=p.category,
                         patient_message=p.patient_message, protocol_id=p.id, procedure_type=p.procedure_type)
            for p in rows if p.category not in exclude_categories]


# Missed check-ins are evaluated by the scheduler, not on submission.
SCHEDULER_ONLY = ("MISSED_CHECKIN",)


def validate_answers(questions: list[CheckinQuestion], answers: dict) -> dict:
    clean: dict = {}
    errors: list[str] = []
    for q in questions:
        v = answers.get(q.key)
        if v in (None, "", []):
            if q.required:
                errors.append(f"{q.key} is required")
            continue
        if q.answer_type in ("SCALE", "NUMBER"):
            try:
                v = float(v)
            except (TypeError, ValueError):
                errors.append(f"{q.key} must be a number")
                continue
            if q.key == "temperature" and answers.get("temperature_unit") == "C":
                v = round(v * 9 / 5 + 32, 1)  # store and evaluate in °F
            if (q.min_value is not None and v < q.min_value) or (q.max_value is not None and v > q.max_value):
                errors.append(f"{q.key} must be between {q.min_value} and {q.max_value}")
                continue
        elif q.answer_type == "CHOICE":
            allowed = {o["value"] for o in q.options}
            if v not in allowed:
                errors.append(f"{q.key} must be one of {sorted(allowed)}")
                continue
        elif q.answer_type == "MULTI":
            allowed = {o["value"] for o in q.options}
            v = [x for x in (v if isinstance(v, list) else [v])]
            if any(x not in allowed for x in v):
                errors.append(f"{q.key} contains invalid options")
                continue
        elif q.answer_type == "BOOLEAN":
            v = bool(v)
        elif q.answer_type == "TEXT":
            v = str(v)[:2000]
        clean[q.key] = v
    if "temperature" in clean:
        clean["temperature_unit"] = "F"
    if errors:
        raise HTTPException(422, {"message": "Invalid check-in", "errors": errors})
    return clean


@dataclass
class CheckinOutcome:
    checkin: Checkin
    evaluation: EvaluationResult
    alerts: list[Alert] = field(default_factory=list)
    patient_message: str = ""


class CheckinAnalysisAgent:
    def __init__(self):
        self.context = IntakeContextAgent()
        self.alerting = AlertEscalationAgent()

    def history_context(self, db: Session, patient: Patient, today: date) -> tuple[dict, dict]:
        prev = db.scalars(select(Checkin).where(
            Checkin.patient_id == patient.id, Checkin.status == "COMPLETED", Checkin.checkin_date <= today)
            .order_by(Checkin.checkin_date.desc(), Checkin.submitted_at.desc())).first()
        prev_answers = {r.question_key: r.value.get("v") for r in prev.responses} if prev else {}
        recent = db.scalars(select(Checkin).where(Checkin.patient_id == patient.id, Checkin.checkin_date < today)
                            .order_by(Checkin.checkin_date.desc()).limit(7)).all()
        missed = 0
        for c in recent:
            if c.status != "MISSED":
                break
            missed += 1
        since = datetime.now(timezone.utc) - timedelta(hours=48)
        missed_doses = db.scalar(select(func.count()).select_from(MedicationEvent).where(
            MedicationEvent.patient_id == patient.id, MedicationEvent.status == "MISSED",
            MedicationEvent.scheduled_for >= since)) or 0
        return prev_answers, {"consecutive_missed_checkins": missed, "missed_doses_48h": missed_doses}

    def submit(self, db: Session, patient: Patient, actor: User, raw_answers: dict,
               on: date | None = None) -> CheckinOutcome:
        ctx = self.context.load(db, patient)
        if not ctx.episode:
            raise HTTPException(409, "Patient has no active surgical episode")
        today = on or date.today()
        questions = questions_for(db, ctx.procedure_type)
        answers = validate_answers(questions, raw_answers)

        prev_answers, hist = self.history_context(db, patient, today)
        hist["recovery_day"] = (today - ctx.episode.surgery_date).days
        facts = build_checkin_facts(answers, prev_answers, hist)
        evaluation = evaluate_protocols(approved_protocols(db, SCHEDULER_ONLY), facts, ctx.procedure_type)

        checkin = Checkin(
            patient_id=patient.id, episode_id=ctx.episode.id, checkin_date=today, recovery_day=hist["recovery_day"],
            status="COMPLETED", submitted_at=datetime.now(timezone.utc), submitted_by_id=actor.id,
            risk_level=evaluation.risk_level, rule_results=evaluation.as_json(),
            free_text_concern=answers.get("concern") or None,
        )
        checkin.responses = [CheckinResponse(question_key=k, value={"v": v}) for k, v in answers.items()
                             if k != "concern"]
        db.add(checkin)
        db.flush()

        alerts = []
        if evaluation.matches:
            alerts.append(self.alerting.from_checkin(db, patient, evaluation.matches, episode_id=ctx.episode.id,
                                                     checkin_id=checkin.id, actor=actor))
        refresh_patient_risk(db, patient)
        metrics.inc("checkins_completed", risk=evaluation.risk_level)
        audit.record(db, "CHECKIN_SUBMITTED", actor=actor, patient_id=patient.id, resource_type="checkin",
                     resource_id=checkin.id, details={
                         "recovery_day": checkin.recovery_day, "risk_level": evaluation.risk_level,
                         "facts": facts, "rules_triggered": [m.rule_id for m in evaluation.matches],
                         "alerts": [str(a.id) for a in alerts]})

        if evaluation.risk_level == "RED":
            msg = next((m.patient_message for m in evaluation.matches if m.severity == "RED" and m.patient_message),
                       "Your answers match a warning sign in your recovery plan. Your care team has been alerted "
                       "and will contact you shortly.")
        elif evaluation.risk_level == "AMBER":
            msg = next((m.patient_message for m in evaluation.matches if m.patient_message),
                       "Thanks. Some answers need a closer look, so your care team will follow up with you.")
        else:
            msg = "Thanks for checking in. Your answers don't match any warning signs in your recovery plan. Keep going!"
        return CheckinOutcome(checkin, evaluation, alerts, msg)
