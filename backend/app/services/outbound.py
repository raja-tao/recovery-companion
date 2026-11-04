"""Outbound to the EHR: alerts as FHIR Communication, surveys as QuestionnaireResponse.

Messages are queued in `outbound_messages` and delivered by the scheduler with retries
(exponential backoff, FAILED after MAX_ATTEMPTS — retry from Admin › Integrations).
With no OUTBOUND_FHIR_URL configured, delivery is SIMULATED: the resource is built and
logged but not sent anywhere.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import log_event, metrics
from app.models import Alert, OutboundMessage, Patient, PromResponse

logger = logging.getLogger("outbound")

DESTINATION = "ehr-fhir"
MAX_ATTEMPTS = 5
# Only clinical findings go to the chart; INFO tasks (transport, reconciliation…) stay in the program.
ALERT_SEVERITIES = ("RED", "AMBER")


def _subject(p: Patient) -> dict:
    return {"identifier": {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                               "code": "MR"}]}, "value": p.mrn}, "display": p.full_name}


def _queue(db: Session, resource_type: str, dedupe_key: str, patient: Patient, related_type: str, related_id,
           resource: dict) -> OutboundMessage | None:
    if db.scalars(select(OutboundMessage.id).where(OutboundMessage.dedupe_key == dedupe_key)).first():
        return None
    m = OutboundMessage(destination=DESTINATION, resource_type=resource_type, dedupe_key=dedupe_key,
                        patient_id=patient.id, related_type=related_type, related_id=str(related_id),
                        payload=json.dumps(resource), status="PENDING")
    db.add(m)
    db.flush()
    metrics.inc("outbound_queued", resource_type=resource_type)
    return m


def queue_alert(db: Session, alert: Alert, patient: Patient) -> OutboundMessage | None:
    if alert.severity not in ALERT_SEVERITIES:
        return None
    resource = {
        "resourceType": "Communication", "status": "completed",
        "identifier": [{"system": "urn:recovery-companion:alert", "value": str(alert.id)}],
        "category": [{"text": "Post-surgical recovery program alert"}],
        "priority": "stat" if alert.severity == "RED" else "urgent",
        "subject": _subject(patient), "sent": alert.created_at.isoformat(),
        "sender": {"display": "Recovery Companion"},
        "payload": [{"contentString": f"{alert.severity} alert ({alert.rule_id}): {alert.trigger_summary}. "
                                      f"Care-team response required within {alert.required_response_minutes} min."}],
    }
    return _queue(db, "Communication", f"alert:{alert.id}", patient, "alert", alert.id, resource)


def queue_prom(db: Session, prom: PromResponse, patient: Patient) -> OutboundMessage | None:
    from app.services.proms import questionnaire_response

    return _queue(db, "QuestionnaireResponse", f"prom:{prom.id}", patient, "prom_response", prom.id,
                  questionnaire_response(prom, patient.mrn))


def deliver(db: Session, m: OutboundMessage, now: datetime | None = None) -> OutboundMessage:
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    m.attempts += 1
    if not s.outbound_fhir_url:
        m.status, m.delivery_mode, m.sent_at, m.last_error = "SENT", "SIMULATED", now, None
        log_event(logger, "outbound simulated", resource_type=m.resource_type, id=str(m.id))
        metrics.inc("outbound_delivered", mode="SIMULATED")
        return m
    url = f"{s.outbound_fhir_url.rstrip('/')}/{m.resource_type}"
    headers = {"Content-Type": "application/fhir+json"}
    if s.outbound_fhir_token:
        headers["Authorization"] = f"Bearer {s.outbound_fhir_token}"
    try:
        r = httpx.post(url, content=m.payload, headers=headers, timeout=10)
        m.response_status = r.status_code
        ok = 200 <= r.status_code < 300
        error = None if ok else f"HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        ok, error = False, f"{type(exc).__name__}: {exc}"[:500]
    m.delivery_mode = "HTTP"
    if ok:
        m.status, m.sent_at, m.last_error = "SENT", now, None
    else:
        m.last_error = error
        m.status = "FAILED" if m.attempts >= MAX_ATTEMPTS else "PENDING"
        m.next_attempt_at = now + timedelta(minutes=2 ** m.attempts)
    metrics.inc("outbound_delivered" if ok else "outbound_failed", mode="HTTP")
    return m


def deliver_due(db: Session, now: datetime | None = None, limit: int = 100) -> int:
    now = now or datetime.now(timezone.utc)
    due = db.scalars(select(OutboundMessage).where(OutboundMessage.status == "PENDING",
                                                   OutboundMessage.next_attempt_at <= now)
                     .order_by(OutboundMessage.next_attempt_at).limit(limit)).all()
    for m in due:
        deliver(db, m, now)
    return len(due)
