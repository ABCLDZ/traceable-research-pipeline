"""Provider、缓存、抽取测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_pipeline.chunker import chunk_document
from research_pipeline.models import (
    DocumentChunk,
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    MimeType,
    ParseQuality,
    SourceTier,
    SourceType,
)
from research_pipeline.providers import (
    CachedProvider,
    CallLogger,
    DeepSeekProvider,
    LLMCache,
    LLMProvider,
    LLMRequest,
    LLMResponse,
)
from research_pipeline.extractor import (
    ChunkExtractionError,
    _try_parse_json,
    dedup_evidence_cards,
    extract_evidence_v3,
    extract_from_chunk_v3,
    load_prompt,
)
from research_pipeline.storage import Storage


class MockProvider(LLMProvider):
    def __init__(self, response_text: str = '[]', fail: bool = False):
        self._response = response_text
        self._fail = fail
        self.calls: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self._fail:
            return LLMResponse(content="", model="mock", error="mock failure")
        return LLMResponse(
            content=self._response,
            model="mock",
            input_tokens=50,
            output_tokens=100,
            total_tokens=150,
        )


class SequenceProvider(MockProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = responses

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return self._responses.pop(0)


def test_llm_request_defaults():
    req = LLMRequest(prompt_name="test", prompt_version="v1", user_prompt="hello")
    assert req.temperature == 0.1


def test_llm_response_cached():
    resp = LLMResponse(content="hi", model="m", cached=True)
    assert resp.cached
    assert resp.total_tokens == 0


def test_cache_miss():
    cache = LLMCache()
    req = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="hello")
    result = cache.get("mock", "m", req)
    assert result is None


def test_cache_hit():
    cache = LLMCache()
    req = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="hello")
    resp = LLMResponse(content="hi", model="m")
    cache.set("mock", "m", req, resp)
    cached = cache.get("mock", "m", req)
    assert cached is not None
    assert cached.cached
    assert cached.content == "hi"


def test_cache_key_differs_by_input():
    cache = LLMCache()
    r1 = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="hello")
    r2 = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="world")
    resp = LLMResponse(content="hi", model="m")
    cache.set("mock", "m", r1, resp)
    assert cache.get("mock", "m", r2) is None


def test_cache_clear():
    cache = LLMCache()
    req = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="hello")
    cache.set("mock", "m", req, LLMResponse(content="hi", model="m"))
    cache.clear()
    assert cache.get("mock", "m", req) is None


def test_cached_provider():
    cache = LLMCache()
    inner = MockProvider(response_text='[{"claim": "test"}]')
    provider = CachedProvider(inner, cache)
    req = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="hello")
    r1 = provider.complete(req)
    assert r1.content == '[{"claim": "test"}]'
    assert len(inner.calls) == 1
    r2 = provider.complete(req)
    assert r2.cached
    assert len(inner.calls) == 1


def test_call_logger(tmp_path):
    logger = CallLogger(tmp_path)
    req = LLMRequest(prompt_name="t", prompt_version="v1", user_prompt="hello")
    resp = LLMResponse(content="hi", model="m", input_tokens=50, output_tokens=100, total_tokens=150)
    logger.log(req, resp)
    summary = logger.summary()
    assert summary["calls"] == 1
    assert summary["total_tokens"] == 150
    log_path = tmp_path / "llm_calls.jsonl"
    assert log_path.exists()


def test_parse_json_direct():
    result = _try_parse_json('[{"claim": "test"}]')
    assert result is not None
    assert len(result) == 1


def test_parse_json_with_markdown():
    result = _try_parse_json('```json\n[{"claim": "test"}]\n```')
    assert result is not None
    assert result[0]["claim"] == "test"


def test_parse_json_empty():
    result = _try_parse_json("[]")
    assert result == []


def test_parse_invalid():
    result = _try_parse_json("not json at all")
    assert result is None


def test_dedup_identical():
    cards = [
        EvidenceCard(evidence_id="e1", document_id="d1", project_id="p1",
                     topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
                     claim="Revenue is 30.89 billion",
                     original_excerpt="revenue 30.89 billion",
                     source_url="x.com", source_tier=SourceTier.TIER_1),
        EvidenceCard(evidence_id="e2", document_id="d1", project_id="p1",
                     topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
                     claim="Revenue is 30.89 billion",
                     original_excerpt="revenue 30.89 billion",
                     source_url="x.com", source_tier=SourceTier.TIER_1),
    ]
    result = dedup_evidence_cards(cards)
    assert len(result) == 1


def test_dedup_different():
    cards = [
        EvidenceCard(evidence_id="e1", document_id="d1", project_id="p1",
                     topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
                     claim="Revenue is 30.89 billion",
                     original_excerpt="revenue 30.89 billion",
                     source_url="x.com", source_tier=SourceTier.TIER_1),
        EvidenceCard(evidence_id="e2", document_id="d1", project_id="p1",
                     topic="cost", evidence_type=EvidenceType.QUANTITATIVE,
                     claim="COGS is 20 billion",
                     original_excerpt="cogs 20 billion",
                     source_url="x.com", source_tier=SourceTier.TIER_1),
    ]
    result = dedup_evidence_cards(cards)
    assert len(result) == 2


def test_dedup_does_not_collapse_distinct_claims_with_same_prefix():
    shared_prefix = "A" * 90
    cards = [
        EvidenceCard(
            evidence_id="e1",
            document_id="d1",
            project_id="p1",
            topic="test",
            evidence_type=EvidenceType.QUALITATIVE,
            claim=f"{shared_prefix} first conclusion",
            original_excerpt="first source excerpt",
            source_url="https://example.com/1",
            source_tier=SourceTier.TIER_1,
        ),
        EvidenceCard(
            evidence_id="e2",
            document_id="d1",
            project_id="p1",
            topic="test",
            evidence_type=EvidenceType.QUALITATIVE,
            claim=f"{shared_prefix} second conclusion",
            original_excerpt="second source excerpt",
            source_url="https://example.com/1",
            source_tier=SourceTier.TIER_1,
        ),
    ]
    assert dedup_evidence_cards(cards) == cards


def test_load_prompt():
    prompt = load_prompt("prompts/extract_evidence_v1.md")
    assert "Extract Evidence Cards" in prompt


def test_load_default_packaged_prompt_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt = load_prompt()
    assert "# Extract Evidence Cards V3" in prompt
    assert "[S0001]" in prompt


def test_extract_from_chunk_with_mock():
    chunk = chunk_document(
        "d1",
        "Example Mobility revenue was 30.89 billion in 2024.",
    )[0]
    provider = MockProvider(
        response_text='[{"sentence_ids": ["S0001"], '
                      '"claim": "Example Mobility revenue 30.89B", "topic": "revenue", '
                      '"evidence_type": "quantitative", '
                      '"numeric_values": []}]'
    )
    cards = extract_from_chunk_v3(
        chunk,
        provider,
        "extract",
        "text: {{CHUNK_TEXT}}",
    )
    assert len(cards) == 1
    assert cards[0].claim == "Example Mobility revenue 30.89B"
    assert cards[0].excerpt_verification is not None
    assert cards[0].excerpt_verification.exact_match
    assert cards[0].selected_sentence_ids == ["S0001"]


def test_extract_rejects_partial_or_nonconsecutive_span():
    chunk = chunk_document("d1", "first line\nsecond line\nthird line")[0]
    provider = MockProvider(
        response_text='[{"sentence_ids": ["S0001", "S0003"], '
                      '"claim": "collapsed claim", "topic": "test", '
                      '"evidence_type": "qualitative"}]'
    )
    with pytest.raises(ChunkExtractionError, match="invalid evidence item"):
        extract_from_chunk_v3(chunk, provider, "extract", "text: {{CHUNK_TEXT}}")


def test_extract_ignores_model_supplied_evidence_id():
    chunk = chunk_document("d1", "A traceable fact.")[0]
    provider = MockProvider(
        response_text='[{"evidence_id": "../outside", "sentence_ids": ["S0001"], '
                      '"claim": "A traceable fact", "topic": "test", '
                      '"evidence_type": "qualitative"}]'
    )
    cards = extract_from_chunk_v3(chunk, provider, "extract", "text: {{CHUNK_TEXT}}")
    assert len(cards) == 1
    assert cards[0].evidence_id.startswith("EVC-")
    assert ".." not in cards[0].evidence_id


def test_extract_from_chunk_failure():
    chunk = chunk_document("d1", "some text.")[0]
    provider = MockProvider(fail=True)
    with pytest.raises(ChunkExtractionError, match="provider error"):
        extract_from_chunk_v3(
            chunk,
            provider,
            "extract",
            "text: {{CHUNK_TEXT}}",
        )


def test_extract_from_chunk_invalid_json_is_not_empty_evidence():
    chunk = chunk_document("d1", "some text.")[0]
    provider = MockProvider(response_text="not json")
    with pytest.raises(ChunkExtractionError, match="valid JSON array"):
        extract_from_chunk_v3(
            chunk,
            provider,
            "extract",
            "text: {{CHUNK_TEXT}}",
        )


def test_extract_from_chunk_valid_empty_array_is_success():
    chunk = chunk_document("d1", "some text.")[0]
    provider = MockProvider(response_text="[]")
    assert extract_from_chunk_v3(
        chunk,
        provider,
        "extract",
        "text: {{CHUNK_TEXT}}",
    ) == []


def test_extract_preserves_numeric_zero():
    chunk = chunk_document("d1", "The measured value was zero.")[0]
    provider = MockProvider(
        response_text='[{"sentence_ids": ["S0001"], "claim": "Value was zero", '
        '"topic": "test", "evidence_type": "quantitative", '
        '"numeric_values": [{"value": 0, "unit": "units"}]}]'
    )
    cards = extract_from_chunk_v3(chunk, provider, "extract", "text: {{CHUNK_TEXT}}")
    assert cards[0].numeric_values[0].value == "0"


def test_extract_rejects_unknown_evidence_type():
    chunk = chunk_document("d1", "A source fact.")[0]
    provider = MockProvider(
        response_text='[{"sentence_ids": ["S0001"], "claim": "A source fact", '
        '"topic": "test", "evidence_type": "invented_type"}]'
    )
    with pytest.raises(ChunkExtractionError, match="invalid evidence item"):
        extract_from_chunk_v3(chunk, provider, "extract", "text: {{CHUNK_TEXT}}")


def test_document_extraction_does_not_persist_partial_cards(tmp_path):
    document = DocumentRecord(
        document_id="DOC-1",
        project_id="project-1",
        entity_name="Example",
        title="Two chunks",
        source_url="https://example.com/source",
        source_type=SourceType.OTHER,
        source_tier=SourceTier.TIER_1,
        mime_type=MimeType.PLAIN_TEXT,
        content_hash="a" * 64,
        text="First fact.\n\nSecond fact.",
        parse_quality=ParseQuality.USABLE,
    )
    first_response = LLMResponse(
        content='[{"sentence_ids": ["S0001"], "claim": "First fact", '
        '"topic": "test", "evidence_type": "qualitative"}]',
        model="mock",
    )
    failed_response = LLMResponse(
        content="",
        model="mock",
        error="second chunk failed",
    )
    provider = SequenceProvider([first_response, failed_response])
    storage = Storage(tmp_path)

    with pytest.raises(ChunkExtractionError, match="second chunk failed"):
        extract_evidence_v3(
            document,
            provider,
            "extract",
            "text: {{CHUNK_TEXT}}",
            storage,
        )
    assert storage.list_evidence("project-1") == []
