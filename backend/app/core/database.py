from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def configure_engine(url: str | None = None):
    """(Re)configure the global engine. Tests call this with the test DB URL."""
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        configure_engine()
    return _engine


def SessionLocal() -> Session:  # noqa: N802 - factory style name
    if _SessionLocal is None:
        configure_engine()
    return _SessionLocal()  # type: ignore[misc]


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Audit events are append-only. Enforced in the database so that no application
# code path (or a compromised one) can silently rewrite history.
AUDIT_IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();
"""


def init_schema(engine=None) -> None:
    """Create extension, tables, vector index and audit trigger (idempotent).

    POC decision: SQLAlchemy create_all instead of Alembic migrations. See
    docs/DATABASE.md for the migration plan before production.
    """
    from app import models  # noqa: F401  (register models)

    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw ON document_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        ))
        conn.execute(text(AUDIT_IMMUTABILITY_SQL))
