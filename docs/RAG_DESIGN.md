# RAG Design

## Governance first

Patients may only receive answers grounded in content that is **explicitly approved** and **currently valid**.
Every document carries:

| Field | Values / meaning |
|---|---|
| `document_key` + `version` | Stable identity across versions; new uploads create a new version |
| `authority` | `SURGEON_APPROVED`, `HOSPITAL_APPROVED`, `PROGRAM_APPROVED` |
| `approval_status` | DRAFT → PENDING → APPROVED → RETIRED (or REJECTED) |
| `approved_by`, `approved_at` | Approver must differ from uploader; surgeon-approved content requires a surgeon |
| `effective_date`, `expiry_date` | Retrieval window |
| `procedure_type`, `patient_population` | Scoping |
| `is_active` | Approving a version deactivates/retires prior active versions of the same key |
| `checksum`, `storage_uri` | Integrity; S3 location in AWS |

Retrieval filter (in SQL, before ranking):
`approval_status='APPROVED' AND is_active AND authority IN (allowed) AND effective_date<=today AND
(expiry_date IS NULL OR expiry_date>=today) AND procedure_type IN ('ALL', patient's procedure)`.

Tests prove a DRAFT document ("return to skiing after 6 weeks") and an EXPIRED document ("drive after 1 week") are
never returned, that approval makes new content retrievable and retirement removes it immediately.

## Pipeline

```
upload (.md/.txt/.pdf, JSON or multipart)          rag/ingestion.py
  → extract text (pypdf for PDF)
  → checksum, version, PENDING
  → heading-aware chunking (rag/chunking.py): split on Markdown headings; section path kept for
    citations; long sections split at ~160 words with 1-paragraph overlap
  → embed "section + content" (rag/embeddings.py) → document_chunks (pgvector, HNSW cosine)
approve → becomes retrievable
```

## Retrieval & ranking (`rag/retrieval.py`)

1. Embed the question; ANN candidate set (top_k×6) by cosine distance from approved chunks only.
2. Re-rank: `0.5 × vector similarity + 0.5 × lexical coverage of the question's content terms
   + 0.15 heading match + 0.05 procedure-specific`. Lexical terms are stop-worded, stemmed and canonicalized
   with a small clinical synonym map (e.g. *bath → shower*, *PT → physiotherapy*, *go back to work → return work*).
3. Require ≥ 1 shared content term (prevents "nearest neighbour of nothing" answers) and score ≥ `RAG_MIN_SCORE`.
4. Return top `RAG_TOP_K` with metadata: query terms, candidates, scores, embedding model.

## Embeddings

| Provider | Setting | Notes |
|---|---|---|
| Hashing (default) | `EMBEDDING_PROVIDER=hashing`, dim 384 | Deterministic, offline, reproducible tests; lexical-level semantics |
| OpenAI | `openai`, `text-embedding-3-small` @ 384 dims | Requires `OPENAI_API_KEY` |
| Ollama | `ollama`, `nomic-embed-text` | Set `EMBEDDING_DIM` to the model's dimension |
| (AWS) Bedrock Titan / Cohere | add a provider class | Recommended for production |

Changing provider/dimension: update `.env`, `make reset` (dimension change) or `make reindex` (same dimension).

## Generation & citations

Top chunks become `<source id="S1" title=… section=…>` blocks. The model returns `source_ids`; validation rejects
unknown IDs, uncited answers, numbers not present in cited sources, and diagnosis/dosing language. Citations
returned to the UI include document title, version, section, authority, approver, score and an excerpt.
Patients' own prescribed-medication instructions are offered as additional approved sources for medication
questions (cited as "Medication record").

## No answer ≠ general knowledge

If retrieval returns nothing, or the model says the sources don't answer, or validation fails twice, the patient
gets: *"I couldn't find this in your approved recovery instructions. Please contact your care team."* and a
care-team task is created with the question and retrieval metadata.
