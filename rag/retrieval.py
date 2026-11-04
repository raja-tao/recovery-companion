"""Knowledge retrieval restricted to approved, active, in-date content.

Hybrid scoring: pgvector cosine similarity (ANN candidate generation) re-ranked
with lexical coverage of the patient's question terms. Source filtering happens
in SQL so unapproved text can never reach the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document, DocumentChunk
from rag.embeddings import get_embedder
from rag.text import content_terms

ALLOWED_AUTHORITIES = ("SURGEON_APPROVED", "HOSPITAL_APPROVED", "PROGRAM_APPROVED")


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_key: str
    title: str
    version: int
    section: str
    content: str
    authority: str
    doc_type: str
    vector_score: float
    lexical_score: float
    score: float
    approved_by: str | None = None
    effective_date: str | None = None

    def citation(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "document_id": self.document_id, "document_key": self.document_key,
            "title": self.title, "version": self.version, "section": self.section, "authority": self.authority,
            "doc_type": self.doc_type, "score": round(self.score, 3), "approved_by": self.approved_by,
            "effective_date": self.effective_date, "excerpt": self.content[:400],
        }


@dataclass
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    candidates_considered: int = 0
    min_score: float = 0.0
    embedding_model: str = ""

    @property
    def found(self) -> bool:
        return bool(self.chunks)

    def meta(self) -> dict:
        return {
            "query_terms": content_terms(self.query), "candidates_considered": self.candidates_considered,
            "returned": len(self.chunks), "min_score": self.min_score, "embedding_model": self.embedding_model,
            "top_score": round(self.chunks[0].score, 3) if self.chunks else None,
            "scores": [round(c.score, 3) for c in self.chunks],
        }


def retrieve(db: Session, query: str, procedure_type: str | None, top_k: int | None = None,
             min_score: float | None = None, today: date | None = None) -> RetrievalResult:
    s = get_settings()
    top_k = top_k or s.rag_top_k
    min_score = s.rag_min_score if min_score is None else min_score
    today = today or date.today()
    embedder = get_embedder()
    qvec = embedder.embed_one(query)
    q_terms = set(content_terms(query))
    result = RetrievalResult(query=query, min_score=min_score, embedding_model=embedder.name)
    if not q_terms:
        return result

    distance = DocumentChunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(DocumentChunk, Document, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.approval_status == "APPROVED",
            Document.is_active.is_(True),
            Document.authority.in_(ALLOWED_AUTHORITIES),
            or_(Document.effective_date.is_(None), Document.effective_date <= today),
            or_(Document.expiry_date.is_(None), Document.expiry_date >= today),
            Document.procedure_type.in_(["ALL", procedure_type or "ALL"]),
        )
        .order_by(distance)
        .limit(top_k * 6)
    )
    rows = db.execute(stmt).all()
    result.candidates_considered = len(rows)
    scored: list[RetrievedChunk] = []
    for chunk, doc, dist in rows:
        vec_score = max(0.0, 1.0 - float(dist))
        chunk_terms = set(content_terms(chunk.section + " " + chunk.content))
        overlap = q_terms & chunk_terms
        lexical = len(overlap) / len(q_terms)
        # Section-heading match is a strong signal in structured discharge instructions.
        heading_bonus = 0.15 if q_terms & set(content_terms(chunk.section)) else 0.0
        score = 0.5 * vec_score + 0.5 * lexical + heading_bonus
        if not overlap:
            continue  # require at least one shared content term — prevents spurious matches
        # Procedure-specific content outranks generic content.
        if doc.procedure_type != "ALL":
            score += 0.05
        scored.append(RetrievedChunk(
            chunk_id=str(chunk.id), document_id=str(doc.id), document_key=doc.document_key, title=doc.title,
            version=doc.version, section=chunk.section, content=chunk.content, authority=doc.authority,
            doc_type=doc.doc_type, vector_score=vec_score, lexical_score=lexical, score=score,
            approved_by=doc.approved_by.full_name if doc.approved_by else None,
            effective_date=doc.effective_date.isoformat() if doc.effective_date else None,
        ))
    scored.sort(key=lambda c: -c.score)
    result.chunks = [c for c in scored if c.score >= min_score][:top_k]
    return result
