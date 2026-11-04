"""Approved-content governance: documents (RAG sources), education, warning protocols, plan approvals."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.recovery_plan import RecoveryPlanAgent
from app.api.deps import get_current_user, my_patient, require
from app.api.serializers import document_out, iso, protocol_out
from app.core.database import get_db
from app.core.security import Perm, Role
from app.models import (
    Document, DocumentChunk, EducationContent, Patient, RecoveryPlan, RecoveryPlanVersion, User, WarningProtocol,
)
from app.schemas import DocumentCreate, DocumentSearch, PlanVersionCreate, ProtocolCreate
from app.services import audit
from app.services.patients import active_episode, phase_for_day, recovery_day
from rag.ingestion import checksum, extract_text, index_document
from rag.retrieval import retrieve
from rules.engine import RuleDefinitionError, validate_condition

router = APIRouter(tags=["Content, Protocols & Plans"])


# =========================================================================== documents
def _create_document(db: Session, user: User, meta: DocumentCreate) -> Document:
    last = db.scalars(select(Document).where(Document.document_key == meta.document_key)
                      .order_by(Document.version.desc())).first()
    doc = Document(**meta.model_dump(), version=(last.version + 1) if last else 1, approval_status="PENDING",
                   is_active=False, checksum=checksum(meta.content), uploaded_by_id=user.id,
                   storage_uri=f"s3://recovery-companion-documents/{meta.document_key}/v{(last.version + 1) if last else 1}")
    db.add(doc)
    db.flush()
    n = index_document(db, doc)
    audit.record(db, "DOCUMENT_UPLOADED", actor=user, resource_type="document", resource_id=doc.id,
                 details={"document_key": doc.document_key, "version": doc.version, "chunks": n,
                          "checksum": doc.checksum})
    return doc


@router.get("/documents", summary="List knowledge documents (all versions)")
def list_documents(user: User = Depends(require(Perm.CONTENT_MANAGE, Perm.CONTENT_APPROVE)),
                   db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).order_by(Document.document_key, Document.version.desc())).all()
    counts = dict(db.execute(select(DocumentChunk.document_id, func.count()).group_by(DocumentChunk.document_id)).all())
    return [document_out(d) | {"chunk_count": counts.get(d.id, 0)} for d in docs]


@router.post("/documents", status_code=201, summary="Create a document version (JSON). Starts PENDING approval")
def create_document(body: DocumentCreate, user: User = Depends(require(Perm.CONTENT_MANAGE)),
                    db: Session = Depends(get_db)):
    doc = _create_document(db, user, body)
    db.commit()
    return document_out(doc)


@router.post("/documents/upload", status_code=201, summary="Upload a .md/.txt/.pdf document (multipart)")
async def upload_document(file: UploadFile = File(...), document_key: str = Form(...), title: str = Form(...),
                          doc_type: str = Form(...), authority: str = Form(...), author: str = Form(...),
                          procedure_type: str = Form("ALL"), patient_population: str = Form("Adult post-surgical"),
                          effective_date: date | None = Form(None), expiry_date: date | None = Form(None),
                          user: User = Depends(require(Perm.CONTENT_MANAGE)), db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 5 MB)")
    if not (file.filename or "").lower().endswith((".md", ".markdown", ".txt", ".pdf")):
        raise HTTPException(415, "Only .md, .txt and .pdf are supported")
    text, fmt = extract_text(file.filename or "upload.txt", data)
    meta = DocumentCreate(document_key=document_key, title=title, doc_type=doc_type, authority=authority,
                          author=author, procedure_type=procedure_type, patient_population=patient_population,
                          effective_date=effective_date, expiry_date=expiry_date, content=text)
    doc = _create_document(db, user, meta)
    doc.content_format = fmt
    db.commit()
    return document_out(doc)


@router.get("/documents/{document_id}", summary="Document detail with content and chunks")
def get_document(document_id: uuid.UUID, user: User = Depends(require(Perm.CONTENT_MANAGE, Perm.CONTENT_APPROVE)),
                 db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if not d:
        raise HTTPException(404, "Not found")
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == d.id)
                        .order_by(DocumentChunk.chunk_index)).all()
    return document_out(d, include_content=True) | {
        "chunks": [{"index": c.chunk_index, "section": c.section, "content": c.content, "tokens": c.token_count,
                    "embedding_model": c.embedding_model} for c in chunks]}


@router.post("/documents/{document_id}/approve", summary="Approve + activate (supersedes other active versions)")
def approve_document(document_id: uuid.UUID, user: User = Depends(require(Perm.CONTENT_APPROVE)),
                     db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if not d:
        raise HTTPException(404, "Not found")
    if d.uploaded_by_id == user.id:
        raise HTTPException(409, "Documents must be approved by someone other than the uploader")
    if d.authority == "SURGEON_APPROVED" and user.role_name != Role.SURGEON.value:
        raise HTTPException(403, "Surgeon-approved content must be approved by a surgeon")
    for other in db.scalars(select(Document).where(Document.document_key == d.document_key, Document.id != d.id,
                                                   Document.is_active.is_(True))):
        other.is_active = False
        other.approval_status = "RETIRED"
    d.approval_status, d.is_active = "APPROVED", True
    d.approved_by_id, d.approved_at = user.id, datetime.now(timezone.utc)
    d.effective_date = d.effective_date or date.today()
    audit.record(db, "DOCUMENT_APPROVED", actor=user, resource_type="document", resource_id=d.id,
                 details={"document_key": d.document_key, "version": d.version, "authority": d.authority})
    db.commit()
    return document_out(d)


@router.post("/documents/{document_id}/retire", summary="Retire a document (removed from retrieval immediately)")
def retire_document(document_id: uuid.UUID, user: User = Depends(require(Perm.CONTENT_MANAGE)),
                    db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if not d:
        raise HTTPException(404, "Not found")
    d.is_active, d.approval_status = False, "RETIRED"
    audit.record(db, "DOCUMENT_RETIRED", actor=user, resource_type="document", resource_id=d.id)
    db.commit()
    return document_out(d)


@router.post("/documents/search", summary="Test retrieval (approved content only) — for content reviewers")
def search_documents(body: DocumentSearch, user: User = Depends(require(Perm.CONTENT_MANAGE, Perm.CONTENT_APPROVE)),
                     db: Session = Depends(get_db)):
    r = retrieve(db, body.query, body.procedure_type)
    return {"meta": r.meta(), "results": [c.citation() | {"content": c.content, "vector_score": round(c.vector_score, 3),
                                                          "lexical_score": round(c.lexical_score, 3)} for c in r.chunks]}


# =========================================================================== education
@router.get("/education", summary="Approved education for the current patient (or all, for staff)")
def education(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(EducationContent).where(EducationContent.status == "APPROVED")
    current_phase = None
    if user.role_name == Role.PATIENT.value:
        p = my_patient(db, user)
        ep = active_episode(db, p.id)
        if ep:
            stmt = stmt.where(EducationContent.procedure_type.in_(["ALL", ep.procedure_type]))
            current_phase = phase_for_day(recovery_day(ep))["key"]
    elif user.role_name == Role.CAREGIVER.value:
        raise HTTPException(403, "Not available to caregivers")
    items = db.scalars(stmt.order_by(EducationContent.title)).all()
    out = []
    for e in items:
        doc = db.get(Document, e.document_id) if e.document_id else None
        out.append({"id": str(e.id), "title": e.title, "summary": e.summary, "body": e.body, "phase": e.phase,
                    "procedure_type": e.procedure_type, "reading_minutes": e.reading_minutes,
                    "recommended": current_phase is not None and e.phase in (current_phase, "ALL"),
                    "source": {"title": doc.title, "version": doc.version, "authority": doc.authority} if doc else None})
    out.sort(key=lambda x: (not x["recommended"], x["title"]))
    return out


# =========================================================================== warning protocols
@router.get("/protocols", summary="Warning protocols (rules engine configuration)")
def list_protocols(user: User = Depends(require(Perm.PROTOCOL_MANAGE, Perm.PROTOCOL_APPROVE, Perm.ALERT_READ)),
                   db: Session = Depends(get_db)):
    return [protocol_out(p) for p in db.scalars(select(WarningProtocol)
                                                 .order_by(WarningProtocol.severity.desc(), WarningProtocol.rule_id,
                                                           WarningProtocol.version.desc()))]


@router.post("/protocols", status_code=201, summary="Propose a protocol version (DRAFT until surgeon approval)")
def create_protocol(body: ProtocolCreate, user: User = Depends(require(Perm.PROTOCOL_MANAGE)),
                    db: Session = Depends(get_db)):
    try:
        validate_condition(body.condition)
    except RuleDefinitionError as exc:
        raise HTTPException(422, f"Invalid condition: {exc}")
    last = db.scalars(select(WarningProtocol).where(WarningProtocol.rule_id == body.rule_id)
                      .order_by(WarningProtocol.version.desc())).first()
    p = WarningProtocol(**body.model_dump(), version=(last.version + 1) if last else 1, status="DRAFT")
    db.add(p)
    db.flush()
    audit.record(db, "PROTOCOL_PROPOSED", actor=user, resource_type="warning_protocol", resource_id=p.id,
                 details=body.model_dump())
    db.commit()
    return protocol_out(p)


@router.post("/protocols/{protocol_id}/approve", summary="Surgeon approval — activates this protocol version")
def approve_protocol(protocol_id: uuid.UUID, user: User = Depends(require(Perm.PROTOCOL_APPROVE)),
                     db: Session = Depends(get_db)):
    p = db.get(WarningProtocol, protocol_id)
    if not p:
        raise HTTPException(404, "Not found")
    for other in db.scalars(select(WarningProtocol).where(WarningProtocol.rule_id == p.rule_id,
                                                          WarningProtocol.id != p.id,
                                                          WarningProtocol.status == "APPROVED")):
        other.status = "RETIRED"
    p.status, p.approved_by_id, p.approved_at = "APPROVED", user.id, datetime.now(timezone.utc)
    audit.record(db, "PROTOCOL_APPROVED", actor=user, resource_type="warning_protocol", resource_id=p.id,
                 details={"rule_id": p.rule_id, "version": p.version})
    db.commit()
    return protocol_out(p)


# =========================================================================== recovery plans
@router.get("/plans/pending", summary="Plan versions awaiting approval")
def pending_plans(user: User = Depends(require(Perm.PLAN_APPROVE)), db: Session = Depends(get_db)):
    out = []
    for v in db.scalars(select(RecoveryPlanVersion).where(RecoveryPlanVersion.status == "PENDING_APPROVAL")
                        .order_by(RecoveryPlanVersion.created_at)):
        plan = db.get(RecoveryPlan, v.plan_id)
        p = db.get(Patient, plan.patient_id)
        out.append({"version_id": str(v.id), "version": v.version, "plan_title": plan.title,
                    "patient_id": str(p.id), "patient_name": p.full_name, "change_summary": v.change_summary,
                    "created_by": v.created_by.full_name if v.created_by else None, "created_at": iso(v.created_at),
                    "content": v.content})
    return out


@router.post("/plans/{plan_id}/versions", status_code=201, summary="Propose a new plan version")
def propose_plan_version(plan_id: uuid.UUID, body: PlanVersionCreate,
                         user: User = Depends(require(Perm.PLAN_APPROVE, Perm.NOTE_WRITE)),
                         db: Session = Depends(get_db)):
    plan = db.get(RecoveryPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    v = RecoveryPlanAgent().create_version(db, plan, body.content, user, body.change_summary)
    db.commit()
    return {"version_id": str(v.id), "version": v.version, "status": v.status}


@router.post("/plans/versions/{version_id}/approve", summary="Approve a recovery plan version (surgeon)")
def approve_plan(version_id: uuid.UUID, user: User = Depends(require(Perm.PLAN_APPROVE)),
                 db: Session = Depends(get_db)):
    v = db.get(RecoveryPlanVersion, version_id)
    if not v:
        raise HTTPException(404, "Not found")
    RecoveryPlanAgent().approve(db, v, user)
    db.commit()
    return {"version_id": str(v.id), "version": v.version, "status": v.status, "approved_at": iso(v.approved_at)}
