"""Patient timeline: a merged, timestamped view of every event in the episode."""
from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Alert, Appointment, CareTeamAction, Checkin, Escalation, Medication, MedicationEvent, Message, MoodEntry, Patient,
    PharmacyFill, PromResponse, RecoveryPlan, RecoveryPlanVersion, SurgicalEpisode, TransportRequest,
)


def _dt(d) -> datetime:
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(d, time(8, 0), tzinfo=timezone.utc)


def build_timeline(db: Session, patient: Patient, *, include_internal: bool = True, limit: int = 300) -> list[dict]:
    ev: list[dict] = []

    def add(ts, kind, title, detail="", severity=None, ref=None, actor=None):
        ev.append({"timestamp": _dt(ts).isoformat(), "type": kind, "title": title, "detail": detail,
                   "severity": severity, "ref_id": str(ref) if ref else None, "actor": actor})

    for ep in db.scalars(select(SurgicalEpisode).where(SurgicalEpisode.patient_id == patient.id)):
        add(ep.surgery_date, "SURGERY", f"Surgery: {ep.procedure_name}",
            f"{ep.hospital}; surgeon {ep.surgeon.full_name if ep.surgeon else 'n/a'}", ref=ep.id)
        add(ep.discharge_date, "DISCHARGE", "Discharged home", ref=ep.id)
    add(patient.enrolled_at, "ENROLLMENT", "Enrolled in 30-day Recovery Companion program", ref=patient.id)

    plan_ids = [p.id for p in db.scalars(select(RecoveryPlan).where(RecoveryPlan.patient_id == patient.id))]
    for v in db.scalars(select(RecoveryPlanVersion).where(RecoveryPlanVersion.plan_id.in_(plan_ids))):
        add(v.created_at, "RECOVERY_PLAN", f"Recovery plan v{v.version} created", v.change_summary, ref=v.id,
            actor=v.created_by.full_name if v.created_by else None)
        if v.approved_at:
            add(v.approved_at, "RECOVERY_PLAN", f"Recovery plan v{v.version} approved", ref=v.id,
                actor=v.approved_by.full_name if v.approved_by else None)

    for c in db.scalars(select(Checkin).where(Checkin.patient_id == patient.id)):
        if c.status == "MISSED":
            add(c.checkin_date, "CHECKIN", f"Day {c.recovery_day} check-in missed", severity="AMBER", ref=c.id)
        else:
            rules = ", ".join(r["rule_id"] for r in c.rule_results) or "no warning rules triggered"
            add(c.submitted_at or c.checkin_date, "CHECKIN", f"Day {c.recovery_day} check-in: {c.risk_level}", rules,
                severity=c.risk_level, ref=c.id)

    meds = {m.id: m.name for m in db.scalars(select(Medication).where(Medication.patient_id == patient.id))}
    for e in db.scalars(select(MedicationEvent).where(MedicationEvent.patient_id == patient.id)
                        .order_by(MedicationEvent.recorded_at.desc()).limit(60)):
        add(e.recorded_at, "MEDICATION", f"{meds.get(e.medication_id, 'Medication')}: {e.status}",
            f"scheduled {e.scheduled_for:%b %d %H:%M}", severity="AMBER" if e.status == "MISSED" else None, ref=e.id)

    for a in db.scalars(select(Appointment).where(Appointment.patient_id == patient.id)):
        add(a.scheduled_at, "APPOINTMENT", f"{a.appointment_type.replace('_', ' ').title()} — {a.status}",
            f"{a.provider_name}, {a.location}; transport {a.transportation_status}", ref=a.id)

    for r in db.scalars(select(TransportRequest).where(TransportRequest.patient_id == patient.id)):
        add(r.created_at, "TRANSPORT", f"Ride {r.kind.replace('_', ' ').lower()}: {r.status.lower()}",
            f"{r.mode or ''} pickup {r.pickup_at:%b %d %H:%M}" if r.pickup_at else "", ref=r.id)

    for m in db.scalars(select(MoodEntry).where(MoodEntry.patient_id == patient.id)
                        .order_by(MoodEntry.recorded_at.desc()).limit(60)):
        add(m.recorded_at, "MOOD", f"Feeling {m.mood.lower()}",
            ", ".join(f.replace("_", " ").lower() for f in m.feelings),
            severity="AMBER" if m.score <= 2 else None, ref=m.id)

    for r in db.scalars(select(PromResponse).where(PromResponse.patient_id == patient.id)):
        add(r.completed_at, "SURVEY", f"{r.instrument.replace('_', ' ')} survey completed",
            f"{r.timepoint}; raw score {r.raw_score}/{r.max_score}", ref=r.id)

    for f in db.scalars(select(PharmacyFill).where(PharmacyFill.patient_id == patient.id)):
        add(f.reported_at, "PHARMACY", f"{f.drug_description}: {f.status.replace('_', ' ').lower()}",
            f.pharmacy_name or "", severity="AMBER" if f.status == "NOT_DISPENSED" else None, ref=f.id)

    for al in db.scalars(select(Alert).where(Alert.patient_id == patient.id)):
        add(al.created_at, "ALERT", f"{al.severity} alert: {al.trigger_summary}", f"rule {al.rule_id}; status {al.status}",
            severity=al.severity, ref=al.id)
        if al.resolved_at:
            add(al.resolved_at, "RESOLUTION", f"Alert resolved: {al.trigger_summary}",
                al.resolution if include_internal else "", ref=al.id)

    q = select(CareTeamAction).where(CareTeamAction.patient_id == patient.id)
    if not include_internal:
        q = q.where(CareTeamAction.internal.is_(False))
    for act in db.scalars(q):
        detail = " · ".join(x for x in [act.contact_method, act.outcome, act.note if include_internal else None] if x)
        add(act.created_at, "CARE_TEAM_ACTION", act.action_type.replace("_", " ").title(), detail, ref=act.id,
            actor=act.actor.full_name if act.actor else None)

    if include_internal:
        for esc in db.scalars(select(Escalation).where(Escalation.patient_id == patient.id)):
            add(esc.created_at, "ESCALATION", f"Escalated to {esc.to_role}", esc.reason, ref=esc.id,
                actor=esc.from_user.full_name if esc.from_user else None)
            if esc.responded_at:
                add(esc.responded_at, "ESCALATION", f"{esc.to_role} responded", esc.response_note or "", ref=esc.id)

    for m in db.scalars(select(Message).where(Message.patient_id == patient.id)
                        .order_by(Message.created_at.desc()).limit(60)):
        label = {"PATIENT": "Patient message", "ASSISTANT": "Assistant reply", "CARE_TEAM": "Care team message"}
        add(m.created_at, "MESSAGE", label.get(m.sender_type, m.sender_type), m.content[:240],
            severity=m.safety_level if m.safety_level in ("AMBER", "RED") else None, ref=m.id,
            actor=m.sender.full_name if m.sender else None)

    ev.sort(key=lambda e: e["timestamp"], reverse=True)
    return ev[:limit]
