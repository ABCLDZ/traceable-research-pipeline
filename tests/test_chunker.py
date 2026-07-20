"""Chunk 化、引用验证、Run Manifest 测试。"""

from __future__ import annotations

from research_pipeline.chunker import (
    _hash_text,
    _link_chunks,
    build_excerpt_from_spans,
    chunk_document,
)
from research_pipeline.models import DocumentChunk, EvidenceCard, EvidenceType, SourceTier
from research_pipeline.verification import verify_excerpt_in_chunk, verify_excerpt_in_document
from research_pipeline.manifest import create_manifest, complete_manifest


def test_chunk_by_page_markers():
    text = "--- Page 1 ---\nheader\n\n--- Page 2 ---\ncontent"
    chunks = chunk_document("doc-1", text)
    assert len(chunks) == 2
    assert chunks[0].page_start == 1
    assert chunks[1].page_start == 2
    assert "content" in chunks[1].text


def test_chunk_by_paragraph():
    text = "para1.\n\npara2.\n\npara3."
    chunks = chunk_document("doc-2", text)
    assert len(chunks) == 3
    assert "para1" in chunks[0].text


def test_chunk_linking():
    text = "a.\n\nb.\n\nc."
    chunks = chunk_document("doc-3", text)
    assert chunks[0].next_chunk_id == chunks[1].chunk_id
    assert chunks[1].previous_chunk_id == chunks[0].chunk_id
    assert chunks[1].next_chunk_id == chunks[2].chunk_id
    assert chunks[2].next_chunk_id is None
    assert chunks[0].previous_chunk_id is None


def test_chunk_has_hash():
    text = "some content to hash"
    chunks = chunk_document("doc-4", text)
    assert len(chunks) == 1
    assert chunks[0].text_hash == _hash_text(text)


def test_chunk_oversized():
    text = "line\n" * 500
    chunks = chunk_document("doc-5", text, max_chunk_chars=500)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 500


def test_chunk_oversized_single_line_respects_limit_and_offsets():
    text = "prefix\n\n" + ("x" * 1001) + "\n\nsuffix"
    chunks = chunk_document("doc-long-line", text, max_chunk_chars=500)
    long_line_chunks = [chunk for chunk in chunks if set(chunk.text) == {"x"}]
    assert [len(chunk.text) for chunk in long_line_chunks] == [500, 500, 1]
    for chunk in chunks:
        assert len(chunk.text) <= 500
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert text[chunk.char_start:chunk.char_end] == chunk.text


def test_chunk_page_offsets_reference_original_text():
    text = "--- Page 1 ---\nalpha\nbeta\n--- Page 2 ---\n" + ("z" * 23)
    chunks = chunk_document("doc-pages", text, max_chunk_chars=10)
    assert len(chunks) > 2
    for chunk in chunks:
        assert len(chunk.text) <= 10
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert text[chunk.char_start:chunk.char_end] == chunk.text


def test_chunk_rejects_nonpositive_limit():
    import pytest

    with pytest.raises(ValueError, match="greater than zero"):
        chunk_document("doc-invalid", "text", max_chunk_chars=0)


def test_chunk_empty():
    chunks = chunk_document("doc-empty", "")
    assert chunks == []


def test_build_excerpt_preserves_original_separator():
    chunk = chunk_document("doc-lines", "first line\nsecond line\nthird line")[0]
    excerpt, verified = build_excerpt_from_spans(chunk, ["S0001", "S0002"])
    assert verified
    assert excerpt == "first line\nsecond line"
    assert excerpt in chunk.text


def test_build_excerpt_rejects_missing_or_nonconsecutive_ids():
    chunk = chunk_document("doc-lines", "first line\nsecond line\nthird line")[0]
    assert build_excerpt_from_spans(chunk, ["S0001", "S9999"]) == ("", False)
    assert build_excerpt_from_spans(chunk, ["S0001", "S0003"]) == ("", False)
    assert build_excerpt_from_spans(chunk, ["S0002", "S0001"]) == ("", False)
    assert build_excerpt_from_spans(chunk, ["S0001", "S0001"]) == ("", False)


# Verification

def test_exact_match():
    chunk = DocumentChunk(
        chunk_id="c1", document_id="d1", chunk_index=0,
        text="Example Mobility revenue 30.89 billion", text_hash="x")
    card = EvidenceCard(
        evidence_id="e1", document_id="d1", project_id="p1",
        topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
        claim="revenue 30.89B",
        original_excerpt="Example Mobility revenue 30.89 billion",
        source_url="https://example.com", source_tier=SourceTier.TIER_1)
    ver = verify_excerpt_in_chunk(card, chunk)
    assert ver.exact_match


def test_normalized_match():
    """Tab vs space should be normalized and match."""
    chunk = DocumentChunk(
        chunk_id="c1", document_id="d1", chunk_index=0,
        text="Example Mobility revenue\t30.89 billion", text_hash="x")
    card = EvidenceCard(
        evidence_id="e1", document_id="d1", project_id="p1",
        topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
        claim="revenue 30.89B",
        original_excerpt="Example Mobility revenue 30.89 billion",
        source_url="https://example.com", source_tier=SourceTier.TIER_1)
    ver = verify_excerpt_in_chunk(card, chunk)
    assert ver.normalized_match


def test_no_match():
    chunk = DocumentChunk(
        chunk_id="c1", document_id="d1", chunk_index=0,
        text="completely different content", text_hash="x")
    card = EvidenceCard(
        evidence_id="e1", document_id="d1", project_id="p1",
        topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
        claim="revenue",
        original_excerpt="Example Mobility revenue 30.89 billion",
        source_url="https://example.com", source_tier=SourceTier.TIER_1)
    ver = verify_excerpt_in_chunk(card, chunk)
    assert not ver.exact_match
    assert not ver.normalized_match
    assert not ver.fuzzy_match


def test_verify_in_document():
    chunks = [
        DocumentChunk(chunk_id="c1", document_id="d1", chunk_index=0,
                      text="first unrelated paragraph", text_hash="a"),
        DocumentChunk(chunk_id="c2", document_id="d1", chunk_index=1,
                      text="Example Mobility revenue 30.89 billion in 2024", text_hash="b"),
    ]
    card = EvidenceCard(
        evidence_id="e1", document_id="d1", project_id="p1",
        topic="rev", evidence_type=EvidenceType.QUANTITATIVE,
        claim="revenue 30.89B",
        original_excerpt="Example Mobility revenue 30.89 billion",
        source_url="https://example.com", source_tier=SourceTier.TIER_1)
    ver = verify_excerpt_in_document(card, chunks)
    assert ver.exact_match


# Run Manifest

def test_create_manifest():
    m = create_manifest(project_id="test-p", run_type="ingest")
    assert m.project_id == "test-p"
    assert m.run_type == "ingest"
    assert m.status == "running"


def test_complete_manifest():
    m = create_manifest(project_id="test-p", run_type="ingest")
    m.fetch_success = 3
    m.fetch_failed = 0
    complete_manifest(m, status="completed")
    assert m.status == "completed"
    assert m.finished_at is not None


def test_manifest_with_errors():
    m = create_manifest(project_id="test-p", run_type="ingest")
    complete_manifest(m, status="failed", errors=["HTTP 403 on FERC"])
    assert m.status == "failed"
    assert len(m.errors) == 1


def test_manifest_with_warnings():
    m = create_manifest(project_id="p", run_type="ingest")
    complete_manifest(m, status="completed",
                       warnings=["PDF table extraction failed"])
    assert m.status == "completed"
    assert len(m.warnings) == 1
