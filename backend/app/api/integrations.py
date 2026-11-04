"""Inbound integrations (EHR FHIR / HL7 v2, RPM devices) and their admin console.

Inbound endpoints authenticate the *sending system* with `X-Integration-Key`, not a user JWT.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.serializers import iso
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import Perm
from app.models import InboundMessage, IntegrationSource, OutboundMessage, Patient, SurgicalEpisode, User
from app.services import audit
from app.services import integrations as svc
from app.services import outbound
from integrations import catalog, hl7v2, ncpdp, samples

router = APIRouter(tags=["Integrations"])

ENDPOINTS = {"FHIR": "/api/integrations/fhir", "HL7V2": "/api/integrations/hl7v2", "DEVICE": "/api/integrations/devices",
             "PHARMACY": "/api/integrations/ncpdp"}
ACK_CODE = {"PROCESSED": "AA", "PARTIAL": "AE", "REJECTED": "AR"}


async def _body(request: Request) -> str:
    raw = await request.body()
    if len(raw) > get_settings().integration_max_bytes:
        raise HTTPException(413, "Message too large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Body must be UTF-8") from None


def _message_out(m: InboundMessage, mrn: str | None = None) -> dict:
    return {"id": str(m.id), "received_at": iso(m.received_at), "source": m.source.name, "source_slug": m.source.slug,
            "channel": m.channel, "message_type": m.message_type, "external_id": m.external_id, "status": m.status,
            "patient_id": str(m.patient_id) if m.patient_id else None, "patient_mrn": mrn,
            "result": m.result or {}, "errors": m.errors or [], "processing_ms": m.processing_ms,
            "simulated": m.simulated}


def _receipt(m: InboundMessage, duplicate: bool) -> dict:
    """What the sender gets back: status and counts, never patient details."""
    return {"message_id": str(m.id), "external_id": m.external_id, "status": m.status, "duplicate": duplicate,
            "result": m.result or {}, "errors": m.errors or []}


def _json_inbound(db: Session, channel: str, raw: str, key: str | None) -> JSONResponse:
    source = svc.authenticate(db, key, channel)
    msg, duplicate = svc.ingest(db, source, raw)
    db.commit()
    return JSONResponse(_receipt(msg, duplicate), status_code=422 if msg.status == "REJECTED" else 200)


# --------------------------------------------------------------------------- inbound (system-to-system)
@router.post("/integrations/fhir", summary="Receive a FHIR R4 Bundle (Patient, Encounter, MedicationRequest, "
                                           "Appointment, Observation, Procedure)")
async def receive_fhir(request: Request, db: Session = Depends(get_db),
                       x_integration_key: str | None = Header(None)):
    return _json_inbound(db, "FHIR", await _body(request), x_integration_key)


@router.post("/integrations/devices", summary="Receive remote-monitoring / wearable readings (JSON)")
async def receive_devices(request: Request, db: Session = Depends(get_db),
                          x_integration_key: str | None = Header(None)):
    return _json_inbound(db, "DEVICE", await _body(request), x_integration_key)


@router.post("/integrations/hl7v2", response_class=PlainTextResponse,
             summary="Receive an HL7 v2 message (ADT^A03, ORU^R01, SIU^S12); replies with an HL7 ACK")
async def receive_hl7v2(request: Request, db: Session = Depends(get_db), x_integration_key: str | None = Header(None)):
    raw = await _body(request)
    source = svc.authenticate(db, x_integration_key, "HL7V2")
    msg, _ = svc.ingest(db, source, raw)
    db.commit()
    text = "; ".join(msg.errors) or ("Accepted" if msg.status == "PROCESSED" else msg.status)
    return PlainTextResponse(hl7v2.ack(raw, ACK_CODE[msg.status], text), media_type="text/plain")


@router.post("/integrations/ncpdp", summary="Receive an NCPDP SCRIPT RxFill (pharmacy fill status); replies with "
                                            "NCPDP Status 010 or Error 900")
async def receive_ncpdp(request: Request, db: Session = Depends(get_db), x_integration_key: str | None = Header(None)):
    raw = await _body(request)
    source = svc.authenticate(db, x_integration_key, "PHARMACY")
    msg, _ = svc.ingest(db, source, raw)
    db.commit()
    return Response(_ncpdp_reply(raw, msg), media_type="application/xml",
                    status_code=422 if msg.status == "REJECTED" else 200)


def _ncpdp_reply(raw: str, msg: InboundMessage) -> str:
    return ncpdp.status_response(ncpdp.message_id_of(raw), msg.status != "REJECTED",
                                 "; ".join(msg.errors) or "Accepted")


def _reply_for(channel: str, raw: str, msg: InboundMessage) -> str | None:
    if channel == "HL7V2":
        return hl7v2.ack(raw, ACK_CODE[msg.status], "; ".join(msg.errors) or "Accepted")
    if channel == "PHARMACY":
        return _ncpdp_reply(raw, msg)
    return None


# --------------------------------------------------------------------------- admin console
class SimulateRequest(BaseModel):
    scenario: str
    mrn: str


@router.get("/admin/integrations", summary="Integration use cases, sources and simulator options (admin)")
def overview(user: User = Depends(require(Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db),
             days: int = Query(30, ge=1, le=365)):
    s = get_settings()
    counts = svc.stats(db, datetime.now(timezone.utc) - timedelta(days=days))
    sources = [{
        "id": str(src.id), "slug": src.slug, "name": src.name, "channel": src.channel, "description": src.description,
        "is_active": src.is_active, "key_prefix": src.key_prefix, "key_rotated_at": iso(src.key_rotated_at),
        "last_message_at": iso(src.last_message_at), "endpoint": ENDPOINTS[src.channel],
        "counts": counts.get(str(src.id), {}),
        # Development convenience only: the seeded key, until it is rotated.
        "dev_key": svc.demo_key(src.slug) if not s.is_production and not src.key_rotated_at else None,
    } for src in db.scalars(select(IntegrationSource).order_by(IntegrationSource.name))]
    patients = [{"mrn": p.mrn, "name": p.full_name, "procedure": proc}
                for p, proc in db.execute(
                    select(Patient, SurgicalEpisode.procedure_type)
                    .outerjoin(SurgicalEpisode, (SurgicalEpisode.patient_id == Patient.id)
                               & (SurgicalEpisode.status == "ACTIVE"))
                    .where(Patient.enrollment_status == "ACTIVE").order_by(Patient.last_name))]
    scenarios = [{"key": k, "title": t, "source": src, "content_type": ct, "expect": exp}
                 for k, (t, src, ct, _, exp) in samples.SCENARIOS.items()]
    out_counts = dict(db.execute(select(OutboundMessage.status, func.count()).group_by(OutboundMessage.status)).all())
    return {"window_days": days, "use_cases": catalog.USE_CASES, "standards": catalog.STANDARDS,
            "pipeline": catalog.PIPELINE, "outbound_pipeline": catalog.OUTBOUND_PIPELINE, "sources": sources,
            "scenarios": scenarios, "patients": patients,
            "outbound": {"destination": outbound.DESTINATION, "mode": "HTTP" if s.outbound_fhir_url else "SIMULATED",
                         "url_configured": bool(s.outbound_fhir_url), "counts": out_counts,
                         "max_attempts": outbound.MAX_ATTEMPTS}}


@router.get("/admin/integrations/messages", summary="Inbound message log (admin)")
def messages(user: User = Depends(require(Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db),
             status: str | None = None, source: str | None = None, limit: int = Query(100, le=500)):
    stmt = (select(InboundMessage, Patient.mrn).outerjoin(Patient, Patient.id == InboundMessage.patient_id)
            .order_by(InboundMessage.received_at.desc()).limit(limit))
    if status:
        stmt = stmt.where(InboundMessage.status == status.upper())
    if source:
        stmt = stmt.join(IntegrationSource, IntegrationSource.id == InboundMessage.source_id).where(
            IntegrationSource.slug == source)
    return [_message_out(m, mrn) for m, mrn in db.execute(stmt)]


@router.get("/admin/integrations/messages/{message_id}", summary="One inbound message including its raw payload")
def message_detail(message_id: uuid.UUID, user: User = Depends(require(Perm.PROGRAM_MANAGE)),
                   db: Session = Depends(get_db)):
    m = db.get(InboundMessage, message_id)
    if not m:
        raise HTTPException(404, "Not found")
    mrn = db.get(Patient, m.patient_id).mrn if m.patient_id else None
    # The raw payload contains PHI, so opening it is audited.
    audit.record(db, "PHI_VIEW_INBOUND_MESSAGE", actor=user, patient_id=m.patient_id,
                 resource_type="inbound_message", resource_id=m.id)
    db.commit()
    return _message_out(m, mrn) | {"payload": m.payload}


@router.post("/admin/integrations/sources/{source_id}/rotate-key",
             summary="Issue a new key for a source. The key is shown once and stored only as a hash.")
def rotate(source_id: uuid.UUID, user: User = Depends(require(Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db)):
    src = db.get(IntegrationSource, source_id)
    if not src:
        raise HTTPException(404, "Not found")
    key = svc.rotate_key(db, src)
    audit.record(db, "INTEGRATION_KEY_ROTATED", actor=user, resource_type="integration_source", resource_id=src.id,
                 details={"source": src.slug, "key_prefix": src.key_prefix})
    db.commit()
    return {"id": str(src.id), "key": key, "key_prefix": src.key_prefix}


@router.post("/admin/integrations/sources/{source_id}/active", summary="Enable or disable a source")
def set_active(source_id: uuid.UUID, active: bool, user: User = Depends(require(Perm.PROGRAM_MANAGE)),
               db: Session = Depends(get_db)):
    src = db.get(IntegrationSource, source_id)
    if not src:
        raise HTTPException(404, "Not found")
    src.is_active = active
    audit.record(db, "INTEGRATION_SOURCE_ENABLED" if active else "INTEGRATION_SOURCE_DISABLED", actor=user,
                 resource_type="integration_source", resource_id=src.id, details={"source": src.slug})
    db.commit()
    return {"id": str(src.id), "is_active": src.is_active}


@router.post("/admin/integrations/simulate",
             summary="Generate a sample message for a patient and run it through the real inbound pipeline")
def simulate(body: SimulateRequest, user: User = Depends(require(Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db)):
    if body.scenario not in samples.SCENARIOS:
        raise HTTPException(404, "Unknown scenario")
    title, slug, content_type, build, _ = samples.SCENARIOS[body.scenario]
    src = db.scalars(select(IntegrationSource).where(IntegrationSource.slug == slug)).first()
    if not src:
        raise HTTPException(409, f"Source {slug} is not configured")
    if not src.is_active:
        raise HTTPException(409, f"{src.name} is disabled; enable it to simulate")
    episode = db.scalars(select(SurgicalEpisode).join(Patient, Patient.id == SurgicalEpisode.patient_id).where(
        Patient.mrn == body.mrn, SurgicalEpisode.status == "ACTIVE")).first()
    raw = build(body.mrn, episode.surgery_date if episode else None)
    msg, duplicate = svc.ingest(db, src, raw, simulated=True)
    audit.record(db, "INTEGRATION_SIMULATED", actor=user, patient_id=msg.patient_id, resource_type="inbound_message",
                 resource_id=msg.id, details={"scenario": body.scenario, "status": msg.status})
    db.commit()
    mrn = body.mrn if msg.patient_id else None
    return {"scenario": body.scenario, "title": title, "content_type": content_type, "raw": raw,
            "ack": _reply_for(src.channel, raw, msg),
            "message": _message_out(msg, mrn), "duplicate": duplicate}


# --------------------------------------------------------------------------- outbound to the EHR
def _outbound_out(m: OutboundMessage, mrn: str | None) -> dict:
    return {"id": str(m.id), "created_at": iso(m.created_at), "destination": m.destination,
            "resource_type": m.resource_type, "related_type": m.related_type, "related_id": m.related_id,
            "patient_mrn": mrn, "status": m.status, "delivery_mode": m.delivery_mode, "attempts": m.attempts,
            "next_attempt_at": iso(m.next_attempt_at), "last_error": m.last_error,
            "response_status": m.response_status, "sent_at": iso(m.sent_at)}


@router.get("/admin/integrations/outbound", summary="Outbound queue to the EHR (admin)")
def outbound_list(user: User = Depends(require(Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db),
                  status: str | None = None, limit: int = Query(100, le=500)):
    stmt = (select(OutboundMessage, Patient.mrn).outerjoin(Patient, Patient.id == OutboundMessage.patient_id)
            .order_by(OutboundMessage.created_at.desc()).limit(limit))
    if status:
        stmt = stmt.where(OutboundMessage.status == status.upper())
    return [_outbound_out(m, mrn) for m, mrn in db.execute(stmt)]


@router.get("/admin/integrations/outbound/{message_id}", summary="One outbound message including its FHIR payload")
def outbound_detail(message_id: uuid.UUID, user: User = Depends(require(Perm.PROGRAM_MANAGE)),
                    db: Session = Depends(get_db)):
    m = db.get(OutboundMessage, message_id)
    if not m:
        raise HTTPException(404, "Not found")
    mrn = db.get(Patient, m.patient_id).mrn if m.patient_id else None
    audit.record(db, "PHI_VIEW_OUTBOUND_MESSAGE", actor=user, patient_id=m.patient_id,
                 resource_type="outbound_message", resource_id=m.id)
    db.commit()
    return _outbound_out(m, mrn) | {"payload": m.payload}


@router.post("/admin/integrations/outbound/{message_id}/retry", summary="Deliver a pending or failed message now")
def outbound_retry(message_id: uuid.UUID, user: User = Depends(require(Perm.PROGRAM_MANAGE)),
                   db: Session = Depends(get_db)):
    m = db.get(OutboundMessage, message_id)
    if not m:
        raise HTTPException(404, "Not found")
    if m.status == "SENT":
        raise HTTPException(409, "Already sent")
    m.status = "PENDING"
    outbound.deliver(db, m)
    audit.record(db, "OUTBOUND_RETRIED", actor=user, patient_id=m.patient_id, resource_type="outbound_message",
                 resource_id=m.id, details={"status": m.status, "attempts": m.attempts})
    db.commit()
    mrn = db.get(Patient, m.patient_id).mrn if m.patient_id else None
    return _outbound_out(m, mrn)


@router.post("/admin/integrations/outbound/deliver", summary="Run the outbound delivery job now")
def outbound_deliver_now(user: User = Depends(require(Perm.PROGRAM_MANAGE)), db: Session = Depends(get_db)):
    n = outbound.deliver_due(db)
    audit.record(db, "OUTBOUND_DELIVERY_RUN", actor=user, details={"processed": n})
    db.commit()
    return {"processed": n}
