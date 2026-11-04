"""Document ingestion pipeline: extract → chunk → embed → store.

Ingestion is allowed for any document (so reviewers can preview chunks), but
retrieval only ever returns chunks of ACTIVE + APPROVED documents inside their
effective/expiry window (see rag/retrieval.py).
"""
from __future__ import annotations

import hashlib
import io

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from rag.chunking import chunk_markdown
from rag.embeddings import get_embedder


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """Return (text, format). Supports .md/.txt and .pdf."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages), "pdf"
    text = data.decode("utf-8", errors="replace")
    return text, "markdown" if name.endswith((".md", ".markdown")) else "text"


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def index_document(db: Session, doc: Document) -> int:
    """(Re)build chunks + embeddings for one document. Returns chunk count."""
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    chunks = chunk_markdown(doc.content, doc.title)
    if not chunks:
        return 0
    embedder = get_embedder()
    # Section title is embedded with the body so headings like "Driving" are matchable.
    vectors = embedder.embed([f"{c.section}\n{c.content}" for c in chunks])
    for c, vec in zip(chunks, vectors):
        db.add(DocumentChunk(
            document_id=doc.id, chunk_index=c.index, section=c.section[:300], content=c.content,
            token_count=c.token_count, embedding=vec, embedding_model=embedder.name,
            meta={"document_key": doc.document_key, "version": doc.version, "doc_type": doc.doc_type,
                  "authority": doc.authority, "procedure_type": doc.procedure_type},
        ))
    db.flush()
    return len(chunks)


def reindex_all(db: Session) -> int:
    total = 0
    for doc in db.query(Document).all():
        total += index_document(db, doc)
    db.commit()
    return total
