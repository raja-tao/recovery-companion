"""Integration Intake: authenticates senders, logs every message and applies parsed records.

Flow per message: authenticate source → parse → idempotency → match patient by MRN →
apply (discharge, medications, appointments, readings) → evaluate approved warning
protocols on fresh readings → alert → log + audit. Clinical thresholds come only from
approved protocols; the intake never invents or changes treatment.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.alerting import AlertEscalationAgent
from agents.checkin_analysis import SCHEDULER_ONLY, approved_protocols
from agents.context import IntakeContextAgent
from app.core.config import get_settings
from app.core.observability import metrics
from app.models import (
    Appointment, DeviceReading, InboundMessage, IntegrationSource, Medication, Patient, PharmacyFill, User,
)
from app.services import audit
from app.services.notifications import notify
from integrations import devices, fhir, hl7v2, ncpdp
from integrations.records import FACT_FOR_KIND, InboundRecord, ParseError, payload_id
from rules.engine import evaluate_protocols

# slug, name, channel, description
SOURCES = [
    ("ehr-fhir", "Hospital EHR (FHIR R4)", "FHIR",
     "Discharge encounters, discharge medications, appointments and vitals from the EHR's FHIR API."),
    ("ehr-hl7", "Interface engine (HL7 v2)", "HL7V2",
     "ADT^A03 discharges, ORU^R01 results and SIU^S12 scheduling forwarded by the hospital interface engine."),
    ("rpm-devices", "Remote monitoring hub", "DEVICE",
     "Thermometer, pulse oximeter, BP cuff and scale readings from the RPM device vendor's cloud."),
    ("patient-wearables", "Patient app wearables", "DEVICE",
     "Steps and heart rate synced by the patient app from Apple HealthKit / Google Health Connect, with consent."),
    ("pharmacy-network", "Pharmacy network (NCPDP SCRIPT)", "PHARMACY",
     "RxFill notifications: whether discharge prescriptions were dispensed or picked up."),
]
# Readings older than this are stored for the record but never page the care team.
ALERT_WINDOW = timedelta(hours=24)
# A discharge this long after surgery that would overwrite a recorded date is held for human review.
MAX_AUTO_DISCHARGE_DAYS = 30
# Protocols whose facts device feeds cannot supply.
DEVICE_EXCLUDED_CATEGORIES = SCHEDULER_ONLY + ("MEDICATION_ADHERENCE",)
PARSERS = {"FHIR": fhir.parse_bundle, "HL7V2": lambda raw: hl7v2.parse(raw)[0], "DEVICE": devices.parse,
           "PHARMACY": ncpdp.parse}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def demo_key(slug: str) -> str:
    return f"{get_settings().integration_demo_key}-{slug}"


def ensure_sources(db: Session) -> int:
    """Create any missing built-in sources (idempotent; also upgrades databases seeded before integrations)."""
    existing = set(db.scalars(select(IntegrationSource.slug)))
    created = 0
    for slug, name, channel, desc in SOURCES:
        if slug in existing:
            continue
        key = demo_key(slug)
        db.add(IntegrationSource(slug=slug, name=name, channel=channel, description=desc, key_hash=hash_key(key),
                                 key_prefix=key[:12]))
        created += 1
    db.flush()
    return created


def rotate_key(db: Session, source: IntegrationSource) -> str:
    key = f"rc_{source.slug}_{secrets.token_urlsafe(24)}"
    source.key_hash, source.key_prefix = hash_key(key), key[:12]
    source.key_rotated_at = datetime.now(timezone.utc)
    return key


def authenticate(db: Session, key: str | None, channel: str) -> IntegrationSource:
    if not key:
        raise HTTPException(401, "X-Integration-Key header required")
    source = db.scalars(select(IntegrationSource).where(IntegrationSource.key_hash == hash_key(key))).first()
    if not source:
        raise HTTPException(401, "Unknown integration key")
    if not source.is_active:
        raise HTTPException(403, "Integration source is disabled")
    if source.channel != channel:
        raise HTTPException(403, f"This source may only send {source.channel} messages")
    return source


def ingest(db: Session, source: IntegrationSource, raw: str, *, simulated: bool = False
           ) -> tuple[InboundMessage, bool]:
    """Process one message. Returns (logged message, was_duplicate)."""
    started = time.perf_counter()
    channel = source.channel
    try:
        rec = PARSERS[channel](raw)
        parse_error = None
    except ParseError as exc:
        rec, parse_error = InboundRecord(channel, "UNPARSEABLE", payload_id(raw)), str(exc)

    previous = db.scalars(select(InboundMessage).where(InboundMessage.source_id == source.id,
                                                       InboundMessage.external_id == rec.external_id[:120])).first()
    if previous:
        metrics.inc("integration_messages", channel=channel, status="DUPLICATE")
        return previous, True

    msg = InboundMessage(source_id=source.id, channel=channel, message_type=rec.message_type[:60],
                         external_id=rec.external_id[:120], payload=raw, simulated=simulated,
                         errors=list(rec.errors))
    patient = None
    if parse_error:
        msg.status, msg.errors = "REJECTED", [parse_error]
    else:
        patient = db.scalars(select(Patient).where(Patient.mrn == rec.patient_mrn)).first()
        if not patient or patient.enrollment_status != "ACTIVE":
            msg.status = "REJECTED"
            msg.errors = ["No actively enrolled patient with this MRN. Messages never create enrollments; "
                          "enroll the patient first."] + msg.errors
            patient = None
        else:
            msg.patient_id, msg.status = patient.id, "RECEIVED"  # flushed first so readings can reference it
            db.add(msg)
            db.flush()
            msg.result = _apply(db, source, msg, rec, patient)
            msg.errors = list(rec.errors)  # reassigned (not mutated) so the JSON column is saved
            msg.status = "PARTIAL" if msg.errors else "PROCESSED"

    msg.processing_ms = int((time.perf_counter() - started) * 1000)
    db.add(msg)
    source.last_message_at = datetime.now(timezone.utc)
    db.flush()
    metrics.inc("integration_messages", channel=channel, status=msg.status)
    audit.record(db, "INTEGRATION_MESSAGE_RECEIVED", actor_role="INTEGRATION",
                 patient_id=patient.id if patient else None, resource_type="inbound_message", resource_id=msg.id,
                 outcome="SUCCESS" if msg.status != "REJECTED" else "DENIED",
                 details={"source": source.slug, "channel": channel, "message_type": msg.message_type,
                          "external_id": msg.external_id, "status": msg.status, "result": msg.result,
                          "error_count": len(msg.errors), "simulated": simulated})
    return msg, False


def _apply(db: Session, source: IntegrationSource, msg: InboundMessage, rec: InboundRecord, patient: Patient) -> dict:
    ctx = IntakeContextAgent().load(db, patient)
    ep = ctx.episode
    result: dict = {"warnings": []}

    if rec.discharge_date:
        if not ep:
            result["warnings"].append("Discharge received but the patient has no active surgical episode")
        elif rec.discharge_date < ep.surgery_date:
            rec.errors.append(f"Discharge date {rec.discharge_date} is before surgery date {ep.surgery_date}")
        elif ep.discharge_date and (rec.discharge_date - ep.surgery_date).days > MAX_AUTO_DISCHARGE_DAYS:
            result["warnings"].append(f"Discharge {rec.discharge_date} is more than {MAX_AUTO_DISCHARGE_DAYS} days "
                                      f"after surgery; recorded date {ep.discharge_date} kept for review")
        elif ep.discharge_date != rec.discharge_date:
            result["discharge_date"] = {"from": ep.discharge_date.isoformat(), "to": rec.discharge_date.isoformat()}
            ep.discharge_date = rec.discharge_date
        else:
            result["discharge_date"] = "unchanged"

    if rec.procedure:
        result["procedure_reported"] = rec.procedure.get("name")
        performed = (rec.procedure.get("performed") or "")[:10]
        if ep and performed and performed != ep.surgery_date.isoformat():
            result["warnings"].append(f"Procedure date {performed} differs from enrolled surgery date "
                                      f"{ep.surgery_date}; please review")

    if rec.medications:
        result["medications"] = _medications(db, patient, ep, rec.medications, source)
    if rec.appointments:
        result["appointments"] = _appointments(db, patient, ep, rec.appointments)
    if rec.observations:
        result["readings"] = _readings(db, source, msg, rec, patient, ctx)
    if rec.fills:
        result["fills"] = _fills(db, msg, rec, patient, ep)
    if not result["warnings"]:
        del result["warnings"]
    return result


def _medications(db: Session, patient: Patient, ep, meds: list[dict], source: IntegrationSource) -> dict:
    active = {m.name.lower(): m for m in db.scalars(select(Medication).where(
        Medication.patient_id == patient.id, Medication.is_active.is_(True)))}
    created, updated, unchanged = [], 0, 0
    for m in meds:
        existing = active.get(m["name"].lower())
        fields = {k: m[k] for k in ("dose_text", "frequency", "route", "as_needed")}
        if m.get("prescriber"):
            fields["prescriber"] = m["prescriber"][:200]
        if existing:
            changed = {k: v for k, v in fields.items() if getattr(existing, k) != v}
            for k, v in changed.items():
                setattr(existing, k, v)
            updated, unchanged = updated + bool(changed), unchanged + (not changed)
        else:
            # No missed-dose guidance: the Medication Safety Agent refuses those questions until the doctor approves it.
            db.add(Medication(patient_id=patient.id, episode_id=ep.id if ep else None, name=m["name"],
                              indication=m["indication"], start_date=m.get("start_date") or datetime.now(timezone.utc).date(),
                              instructions=f"Received from {source.name}.", **fields))
            created.append(m["name"])
    db.flush()
    if created:
        AlertEscalationAgent().from_policy(
            db, patient, "INT-MED-RECONCILE", f"Reconcile {len(created)} new discharge medication(s) from the EHR",
            [{"medications": created, "source": source.slug}], source="INTEGRATION",
            episode_id=ep.id if ep else None)
    return {"created": len(created), "updated": updated, "unchanged": unchanged}


def _appointments(db: Session, patient: Patient, ep, appts: list[dict]) -> dict:
    created = updated = 0
    for a in appts:
        existing = db.scalars(select(Appointment).where(
            Appointment.patient_id == patient.id, Appointment.scheduled_at == a["scheduled_at"],
            Appointment.appointment_type == a["appointment_type"])).first()
        fields = {k: a[k] for k in ("provider_name", "location", "duration_minutes", "status")}
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            updated += 1
        elif a["status"] == "SCHEDULED":
            db.add(Appointment(patient_id=patient.id, episode_id=ep.id if ep else None,
                               appointment_type=a["appointment_type"], scheduled_at=a["scheduled_at"], **fields))
            created += 1
    db.flush()
    return {"created": created, "updated": updated}


def _readings(db: Session, source: IntegrationSource, msg: InboundMessage, rec: InboundRecord, patient: Patient,
              ctx) -> dict:
    now = datetime.now(timezone.utc)
    rows = []
    for o in rec.observations:
        row = DeviceReading(patient_id=patient.id, message_id=msg.id, kind=o.kind, value=o.value, unit=o.unit,
                            code=o.code, device=(o.device or source.name)[:120], measured_at=o.measured_at)
        db.add(row)
        rows.append(row)
    db.flush()
    out: dict = {"stored": len(rows), "risk_level": "GREEN", "alert_id": None}

    fresh = [r for r in rows if r.measured_at >= now - ALERT_WINDOW and r.measured_at <= now + timedelta(minutes=10)]
    if len(fresh) < len(rows):
        out["not_evaluated"] = len(rows) - len(fresh)  # stored, but too old (or future-dated) to alert on
    if not fresh:
        return out

    # Latest value per fact; protocols referencing facts a device can't supply simply don't match.
    facts: dict = {"recovery_day": ctx.recovery_day}
    for r in sorted(fresh, key=lambda r: r.measured_at):
        facts[FACT_FOR_KIND[r.kind]] = r.value
    evaluation = evaluate_protocols(approved_protocols(db, DEVICE_EXCLUDED_CATEGORIES), facts, ctx.procedure_type)
    out["risk_level"] = evaluation.risk_level
    out["rules_triggered"] = [m.rule_id for m in evaluation.matches]
    if not evaluation.matches:
        return out

    primary = evaluation.matches[0]
    evidence = [{"rule_id": m.rule_id, "name": m.name, "severity": m.severity, "evidence": m.evidence}
                for m in evaluation.matches]
    evidence.append({"source": source.slug, "message_id": str(msg.id),
                     "readings": [{"kind": r.kind, "value": r.value, "unit": r.unit, "device": r.device,
                                   "measured_at": r.measured_at.isoformat()} for r in fresh]})
    alert = AlertEscalationAgent().from_rule_match(
        db, patient, replace(primary, evidence=evidence, name=f"{primary.name} (device reading)"),
        episode_id=ctx.episode.id if ctx.episode else None, source="INTEGRATION")
    for r in fresh:
        r.alert_id = alert.id
    out["alert_id"] = str(alert.id)
    if primary.patient_message and patient.user_id:
        notify(db, category="DEVICE_READING_ALERT", title="Your care team has been alerted",
               body=primary.patient_message, user=db.get(User, patient.user_id), patient=patient,
               dedupe_key=f"device-alert:{alert.id}")
    return out


def _match_medication(meds: list[Medication], description: str) -> Medication | None:
    """Match a dispensed drug to the medication list by drug name (first word, e.g. 'apixaban')."""
    word = description.lower().split()[0] if description.strip() else ""
    hits = [m for m in meds if m.name.lower().split()[0] == word]
    return hits[0] if len(hits) == 1 else None


def _fills(db: Session, msg: InboundMessage, rec: InboundRecord, patient: Patient, ep) -> dict:
    meds = list(db.scalars(select(Medication).where(Medication.patient_id == patient.id,
                                                    Medication.is_active.is_(True))))
    out: dict = {"recorded": 0, "not_dispensed": 0, "unmatched": [], "alert_id": None}
    missing = []
    for f in rec.fills:
        med = _match_medication(meds, f["drug_description"])
        row = PharmacyFill(patient_id=patient.id, medication_id=med.id if med else None, message_id=msg.id,
                           **{k: f[k] for k in ("drug_description", "status", "quantity", "days_supply", "fill_date",
                                                "pharmacy_name", "reason")})
        db.add(row)
        out["recorded"] += 1
        if not med:
            out["unmatched"].append(f["drug_description"])
        if f["status"] == "NOT_DISPENSED":
            out["not_dispensed"] += 1
            missing.append(row)
    db.flush()
    if out["unmatched"]:
        rec.errors.append(f"{len(out['unmatched'])} dispensed drug(s) are not on the patient's medication list")
    if missing:
        # Outreach first (nurse); any change to the prescription itself is the doctor's decision.
        alert = AlertEscalationAgent().from_policy(
            db, patient, "INT-RX-NOT-FILLED", f"Pharmacy reports {len(missing)} prescription(s) not picked up",
            [{"fact": "fill_status", "actual": "NOT_DISPENSED", "drugs": [r.drug_description for r in missing],
              "reasons": [r.reason for r in missing if r.reason], "pharmacy": missing[0].pharmacy_name}],
            source="INTEGRATION", episode_id=ep.id if ep else None)
        for r in missing:
            r.alert_id = alert.id
        out["alert_id"] = str(alert.id)
    if not out["unmatched"]:
        del out["unmatched"]
    return out


def stats(db: Session, since: datetime) -> dict:
    rows = db.execute(select(InboundMessage.source_id, InboundMessage.status, func.count())
                      .where(InboundMessage.received_at >= since)
                      .group_by(InboundMessage.source_id, InboundMessage.status)).all()
    out: dict = {}
    for source_id, status, n in rows:
        out.setdefault(str(source_id), {})[status] = n
    return out
