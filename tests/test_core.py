"""搜索工作流——测试套件。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from research_pipeline.config import load_config
from research_pipeline.dedup import (
    content_hash,
    dedup_by_hash,
    dedup_urls,
    is_near_duplicate,
    normalize_url,
)
from research_pipeline.models import (
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    IngestStats,
    MimeType,
    ProjectConfig,
    SourceTier,
    SourceType,
)
from research_pipeline.parser import extract_text
from research_pipeline.storage import Storage

TEST_FIXTURES = Path(__file__).parent / "fixtures"


def test_load_default_config():
    config = load_config(Path("configs/example.yaml"))
    assert isinstance(config, ProjectConfig)
    assert config.project_id == "example_research"
    assert config.entity.name == "Example Entity"
    assert isinstance(config.seed_urls, list)


class TestUrlDedup:
    def test_normalize_removes_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_normalize_lowercases_netloc(self):
        assert normalize_url("HTTPS://EXAMPLE.COM/Path") == "https://example.com/Path"

    def test_normalize_strips_www(self):
        assert normalize_url("https://www.example.com/page") == "https://example.com/page"

    def test_normalize_strips_trailing_slash(self):
        assert normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_normalize_keeps_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_dedup_urls_removes_duplicates(self):
        urls = ["https://example.com/page", "https://EXAMPLE.com/page", "https://example.com/page#frag"]
        result = dedup_urls(urls)
        assert len(result) == 1

    def test_dedup_urls_preserves_first(self):
        urls = ["https://a.com/first", "https://a.com/second", "https://A.com/first"]
        result = dedup_urls(urls)
        assert len(result) == 2
        assert "https://a.com/first" in result[0]


class TestContentDedup:
    def test_content_hash_is_consistent(self):
        h1 = content_hash("hello world")
        h2 = content_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64

    def test_content_hash_differs(self):
        h1 = content_hash("hello world")
        h2 = content_hash("hello world!")
        assert h1 != h2

    def test_dedup_by_hash(self):
        doc1 = _make_doc("doc1", "content A")
        doc2 = _make_doc("doc2", "content A")
        doc3 = _make_doc("doc3", "content B")
        unique, dups = dedup_by_hash([doc1, doc2, doc3])
        assert len(unique) == 2
        assert len(dups) == 1
        assert dups[0].document_id == "doc2"


class TestNearDuplicate:
    def test_identical_text(self):
        assert is_near_duplicate(
            "Example Mobility revenue was 12.4 billion",
            "Example Mobility revenue was 12.4 billion",
        )

    def test_very_similar(self):
        a = "Example Mobility revenue was 12.4 billion, up 18.2%"
        b = "Example Mobility revenue was 12.4 billion, up 18%"
        assert is_near_duplicate(a, b)

    def test_different_text(self):
        assert not is_near_duplicate(
            "Example Mobility revenue was 12.4 billion",
            "Sample Energy generated 90 terawatt-hours",
        )

    def test_empty_text(self):
        assert not is_near_duplicate("", "content")


class TestParser:
    def test_extract_html(self):
        html_content = b"<html><body><h1>Title</h1><p>Hello world</p></body></html>"
        text, mime, error = extract_text(html_content, "text/html")
        assert "Hello world" in text
        assert "Title" in text

    def test_extract_html_trafilatura(self):
        html_path = TEST_FIXTURES / "sample_report.html"
        content = html_path.read_bytes()
        text, mime, error = extract_text(content, "text/html")
        assert "12.4 billion" in text
        assert "84,000 devices" in text
        assert mime == "text/html"

    def test_extract_pdf_fallback(self):
        fake_pdf = b"%PDF-1.4 fake content but not real PDF"
        text, mime, error = extract_text(fake_pdf, "application/pdf")
        assert text

    def test_extract_fallback(self):
        content = b"\xe4\xbd\xa0\xe5\xa5\xbd"
        text, mime, error = extract_text(content, "application/octet-stream")
        assert "你好" in text


class TestStorage:
    def test_save_raw_and_parsed(self, tmp_path):
        storage = Storage(tmp_path)
        doc_id = "test-001"
        project_id = "test-project"
        raw = storage.save_raw(project_id, doc_id, b"<html>test</html>", "text/html")
        assert raw.exists()
        parsed = storage.save_parsed_text(project_id, doc_id, "test content")
        assert parsed.exists()
        assert raw in storage.list_raw_files(project_id)
        assert parsed in storage.list_parsed_files(project_id)

    def test_evidence_card_roundtrip(self, tmp_path):
        storage = Storage(tmp_path)
        project_id = "test-project"
        card = EvidenceCard(
            evidence_id="EVD-00001",
            document_id="DOC-001",
            project_id=project_id,
            topic="revenue",
            evidence_type=EvidenceType.QUANTITATIVE,
            claim="Synthetic annual revenue was 12.4 billion units",
            original_excerpt=(
                "Example Mobility reported synthetic annual revenue of "
                "12.4 billion units"
            ),
            source_url="https://example.com",
            source_tier=SourceTier.TIER_1,
        )
        path = storage.save_evidence(project_id, card)
        assert path.exists()
        loaded = storage.load_evidence(project_id, "EVD-00001")
        assert loaded is not None
        assert loaded.claim == card.claim
        all_cards = storage.list_evidence(project_id)
        assert len(all_cards) == 1

    def test_hash_consistency(self):
        content = b"consistent content"
        h1 = Storage.hash_content(content)
        h2 = Storage.hash_content(content)
        assert h1 == h2
        assert len(h1) == 64

    @pytest.mark.parametrize(
        "unsafe_id",
        ["../outside", r"..\outside", "/absolute", "a/b", r"a\b", ".", ""],
    )
    def test_rejects_unsafe_project_id(self, tmp_path, unsafe_id):
        storage = Storage(tmp_path)
        with pytest.raises(ValueError, match="project_id"):
            storage.save_raw(unsafe_id, "DOC-001", b"test", "text/plain")

    @pytest.mark.parametrize(
        "unsafe_id",
        ["../outside", r"..\outside", "/absolute", "a/b", r"a\b", ".", ""],
    )
    def test_rejects_unsafe_document_id(self, tmp_path, unsafe_id):
        storage = Storage(tmp_path)
        with pytest.raises(ValueError, match="document_id"):
            storage.save_raw("project-1", unsafe_id, b"test", "text/plain")

    def test_rejects_unsafe_evidence_id(self, tmp_path):
        storage = Storage(tmp_path)
        card = EvidenceCard(
            evidence_id="../outside",
            document_id="DOC-001",
            project_id="project-1",
            topic="test",
            evidence_type=EvidenceType.QUALITATIVE,
            claim="test claim",
            original_excerpt="test excerpt",
            source_url="https://example.com",
            source_tier=SourceTier.TIER_1,
        )
        with pytest.raises(ValueError, match="evidence_id"):
            storage.save_evidence("project-1", card)


class TestIngestStats:
    def test_stats_defaults(self):
        stats = IngestStats(project_id="test")
        assert stats.fetched == 0
        assert stats.failed == 0
        assert stats.total_documents == 0

    def test_stats_accumulates(self):
        stats = IngestStats(project_id="test")
        stats.fetched += 3
        stats.failed += 1
        assert stats.fetched == 3
        assert stats.failed == 1


def _make_doc(doc_id: str, text: str) -> DocumentRecord:
    return DocumentRecord(
        document_id=doc_id,
        project_id="test",
        entity_name="Test Corp",
        title=f"Doc {doc_id}",
        source_url=f"https://example.com/{doc_id}",
        source_type=SourceType.OTHER,
        source_tier=SourceTier.TIER_4,
        mime_type=MimeType.HTML,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
    )
