"""Unit tests: validation, extractive provider, router, chunking, text normalization, embeddings."""
import json

from ai.providers.base import LLMProvider, LLMRequest, LLMResponse
from ai.providers.extractive import ExtractiveProvider
from ai.router import ModelRouter, Task
from ai.validation import validate_answer
from app.core.config import Settings
from rag.chunking import chunk_markdown
from rag.embeddings import HashingEmbedder
from rag.text import content_terms

SRC = [{"id": "S1", "title": "TKA", "section": "Driving",
        "content": "Do not drive for at least 4 weeks after surgery. Never drive while taking opioid pain medicine."}]


def j(**kw):
    return json.dumps({"answerable": True, "answer": "", "source_ids": ["S1"]} | kw)


# --------------------------------------------------------------------------- validation
def test_valid_grounded_answer_passes():
    v = validate_answer(j(answer="Do not drive for at least 4 weeks."), SRC)
    assert v.ok and v.answerable


def test_invented_number_rejected():
    v = validate_answer(j(answer="You can drive after 2 weeks."), SRC)
    assert not v.ok and any("ungrounded_numbers" in i for i in v.issues)


def test_unknown_source_rejected():
    v = validate_answer(j(answer="Do not drive.", source_ids=["S9"]), SRC)
    assert not v.ok


def test_missing_citation_rejected():
    assert not validate_answer(j(answer="Do not drive.", source_ids=[]), SRC).ok


def test_diagnosis_language_rejected():
    v = validate_answer(j(answer="It sounds like an infection, you may have a DVT."), SRC)
    assert not v.ok and any("diagnosis" in i for i in v.issues)


def test_dose_change_language_rejected():
    v = validate_answer(j(answer="You should double the dose tonight."), SRC)
    assert not v.ok and any("dose change" in i for i in v.issues)


def test_malformed_output_rejected():
    assert not validate_answer("not json", SRC).ok


def test_not_answerable_is_ok_but_empty():
    v = validate_answer(json.dumps({"answerable": False, "answer": "", "source_ids": []}), SRC)
    assert v.ok and not v.answerable


# --------------------------------------------------------------------------- extractive provider
def test_extractive_quotes_source_only():
    r = ExtractiveProvider().generate(LLMRequest("", "", context={"question": "When can I drive?", "sources": SRC}))
    data = json.loads(r.text)
    assert data["answerable"] and data["source_ids"] == ["S1"]
    assert all(s.strip() in SRC[0]["content"] for s in data["answer"].split(". ") if s)


def test_extractive_refuses_low_coverage():
    r = ExtractiveProvider().generate(LLMRequest("", "", context={"question": "Can I go scuba diving?", "sources": SRC}))
    assert json.loads(r.text)["answerable"] is False


# --------------------------------------------------------------------------- router
class FakeLLM(LLMProvider):
    name, model = "claude", "fake"

    def __init__(self, ok=True):
        self.ok = ok

    def available(self):
        return self.ok

    def generate(self, req):
        return LLMResponse("{}", self.name, self.model)


def router(ok=True, provider="claude"):
    s = Settings(llm_provider=provider)
    return ModelRouter(s, providers={"claude": FakeLLM(ok), "extractive": ExtractiveProvider()})


def test_router_never_uses_llm_for_red():
    d = router().route(Task.PATIENT_CLINICAL_QA, "RED")
    assert d.provider is None


def test_router_uses_claude_by_default_for_clinical_qa():
    assert router().route(Task.PATIENT_CLINICAL_QA, "GREEN").provider.name == "claude"


def test_router_falls_back_to_extractive_when_unavailable():
    assert router(ok=False).route(Task.PATIENT_CLINICAL_QA, "GREEN").provider.name == "extractive"


# --------------------------------------------------------------------------- RAG primitives
def test_chunking_keeps_sections():
    md = "# Title\n\n## Driving\nDo not drive.\n\n## Showering\nShower after 48 hours."
    chunks = chunk_markdown(md, "Title")
    assert [c.section for c in chunks] == ["Driving", "Showering"]


def test_chunking_splits_long_sections():
    md = "## Long\n" + "\n\n".join("word " * 60 for _ in range(6))
    assert len(chunk_markdown(md, "T", max_words=150)) > 1


def test_synonyms_and_stemming():
    assert "drive" in content_terms("When can I start driving?")
    assert "shower" in content_terms("Can I take a bath?")
    assert "physiotherapy" in content_terms("When does PT begin?")
    assert "swell" in content_terms("My knee is swollen")


def test_hashing_embedder_similarity():
    e = HashingEmbedder(384)
    q, a, b = e.embed(["when can I drive", "Driving: do not drive for 4 weeks", "Shower after 48 hours"])
    cos = lambda x, y: sum(i * k for i, k in zip(x, y))  # noqa: E731
    assert cos(q, a) > cos(q, b)
    assert abs(sum(v * v for v in a) - 1) < 1e-6
