"""Re-chunk and re-embed every document (run after changing EMBEDDING_PROVIDER/EMBEDDING_DIM)."""
from app.core.database import SessionLocal, init_schema
from rag.ingestion import reindex_all

if __name__ == "__main__":
    init_schema()
    db = SessionLocal()
    try:
        print(f"Indexed {reindex_all(db)} chunks")
    finally:
        db.close()
