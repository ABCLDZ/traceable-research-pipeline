from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from research_pipeline.admission import (
    EvidenceRecordCollection,
    admit_review_pack,
    build_review_pack,
)
from research_pipeline.context import compile_context
from research_pipeline.ids import stable_id
from research_pipeline.models import (
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    ExcerptVerification,
    MimeType,
    ParseQuality,
    ResearchBrief,
    SourceTier,
    SourceType,
)
from research_pipeline.providers import CallLogger, LLMCache, LLMRequest, LLMResponse
from research_pipeline.quality import assess_parse_quality
from research_pipeline.release import freeze_release, verify_release
from research_pipeline.storage import Storage
from research_pipeline.url_policy import validate_public_url


def make_card(card_id: str = "EVC-001", claim: str = "Revenue reached 10.") -> EvidenceCard:
    return EvidenceCard(
        evidence_id=card_id,
        document_id="DOC-001",
        project_id="demo",
        topic="revenue_structure",
        evidence_type=EvidenceType.QUANTITATIVE,
        claim=claim,
        original_excerpt="Revenue reached 10 in the first quarter.",
        source_url="https://example.com/report",
        source_tier=SourceTier.TIER_1,
        excerpt_verification=ExcerptVerification(
            exact_match=True,
            verification_method="auto_span",
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )


def make_document() -> DocumentRecord:
    return DocumentRecord(
        document_id="DOC-001",
        project_id="demo",
        entity_name="Demo",
        title="Demo report",
        source_url="https://example.com/report",
        source_type=SourceType.ANNUAL_REPORT,
        source_tier=SourceTier.TIER_1,
        mime_type=MimeType.HTML,
        content_hash="a" * 64,
        text="Revenue reached 10 in the first quarter.",
        parse_quality=ParseQuality.USABLE,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_stable_id_is_deterministic():
    assert stable_id("EVC", "a", 1) == stable_id("EVC", "a", 1)
    assert stable_id("EVC", "a", 1) != stable_id("EVC", "a", 2)


def test_cache_key_includes_system_prompt_and_max_tokens():
    cache = LLMCache()
    response = LLMResponse(content="x", model="m")
    base = LLMRequest(
        prompt_name="p",
        prompt_version="v1",
        system_prompt="one",
        user_prompt="input",
        max_tokens=100,
    )
    changed_system = base.model_copy(update={"system_prompt": "two"})
    changed_tokens = base.model_copy(update={"max_tokens": 200})
    cache.set("mock", "m", base, response)
    assert cache.get("mock", "m", changed_system) is None
    assert cache.get("mock", "m", changed_tokens) is None


def test_logger_redacts_content_by_default(tmp_path):
    logger = CallLogger(tmp_path)
    logger.log(
        LLMRequest(
            prompt_name="p",
            prompt_version="v1",
            system_prompt="secret instructions",
            user_prompt="confidential material",
        ),
        LLMResponse(content="sensitive output", model="m"),
    )
    log_text = (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8")
    assert "confidential material" not in log_text
    assert "sensitive output" not in log_text
    assert "[REDACTED sha256:" in log_text


def test_url_policy_rejects_private_and_honors_allowlist():
    assert validate_public_url("http://127.0.0.1/private")[0] is False
    assert validate_public_url("file:///tmp/a")[0] is False
    assert validate_public_url(
        "https://sub.example.com/report",
        allowed_domains=["example.com"],
    )[0] is True
    assert validate_public_url(
        "https://other.com/report",
        allowed_domains=["example.com"],
    )[0] is False


def test_pdf_quality_is_conservative():
    quality, tables, manual, signals = assess_parse_quality(
        mime_type=MimeType.PDF,
        text="short",
        parse_error=None,
    )
    assert quality == ParseQuality.DEGRADED
    assert tables.value == "unknown"
    assert manual is True
    assert "pdf_table_structure_not_guaranteed" in signals


def test_document_metadata_roundtrip(tmp_path):
    storage = Storage(tmp_path)
    document = make_document()
    storage.save_document(document)
    loaded = storage.load_document("demo", "DOC-001")
    assert loaded is not None
    assert loaded.parse_quality == ParseQuality.USABLE
    assert storage.list_documents("demo")[0].document_id == "DOC-001"


def test_pending_review_pack_is_not_applied(tmp_path):
    review_path = tmp_path / "review.json"
    output_path = tmp_path / "records.json"
    build_review_pack(
        [make_card()],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[make_document()],
    )
    with pytest.raises(ValueError, match="pending"):
        admit_review_pack(
            review_pack_path=review_path,
            cards=[make_card()],
            documents=[make_document()],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=output_path,
            reviewer="tester",
        )
    assert not output_path.exists()


def test_review_pack_admission_and_context_compilation(tmp_path):
    card = make_card()
    review_path = tmp_path / "review.json"
    records_path = tmp_path / "records.json"
    build_review_pack(
        [card],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[make_document()],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["items"][0].update(
        {
            "decision": "admit",
            "record_title": "Quarterly revenue",
            "time_range": "2026Q1",
            "geography": "Global",
            "applicability": "Company-reported quarterly result",
            "prohibited_extrapolations": ["Do not treat as an industry-wide result."],
        }
    )
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    admit_review_pack(
        review_pack_path=review_path,
        cards=[card],
        documents=[make_document()],
        expected_project_id="demo",
        expected_research_question="What changed?",
        output_path=records_path,
        reviewer="tester",
    )
    collection = EvidenceRecordCollection.model_validate_json(
        records_path.read_text(encoding="utf-8")
    )
    assert len(collection.records) == 1
    record_id = collection.records[0].evidence_record_id

    brief_path = tmp_path / "brief.json"
    brief = ResearchBrief(
        project_id="demo",
        research_question="What changed?",
        approved_evidence_ids=[record_id],
        scope=["Company quarterly result"],
        open_questions=["Is the result durable?"],
    )
    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    context_json, context_md = compile_context(
        brief_path=brief_path,
        evidence_records_path=records_path,
        output_dir=tmp_path / "context",
    )
    assert context_json.exists()
    text = context_md.read_text(encoding="utf-8")
    assert record_id in text
    assert "Do not treat as an industry-wide result." in text


def test_admission_rejects_tampered_automatic_blockers(tmp_path):
    card = make_card().model_copy(
        update={
            "excerpt_verification": ExcerptVerification(
                exact_match=False,
                verification_method="failed_binding",
            )
        }
    )
    review_path = tmp_path / "review.json"
    build_review_pack(
        [card],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[make_document()],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["items"][0]["automatic_blockers"]
    review["items"][0]["automatic_blockers"] = []
    review["items"][0]["decision"] = "admit"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match="authoritative review snapshot was modified"):
        admit_review_pack(
            review_pack_path=review_path,
            cards=[card],
            documents=[make_document()],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=tmp_path / "records.json",
            reviewer="tester",
        )


def test_admission_recomputes_blockers_and_requires_explicit_override(tmp_path):
    card = make_card().model_copy(
        update={
            "excerpt_verification": ExcerptVerification(
                exact_match=False,
                verification_method="failed_binding",
            )
        }
    )
    review_path = tmp_path / "review.json"
    build_review_pack(
        [card],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[make_document()],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["items"][0]["decision"] = "admit"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match="no manual_override_reason"):
        admit_review_pack(
            review_pack_path=review_path,
            cards=[card],
            documents=[make_document()],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=tmp_path / "records.json",
            reviewer="tester",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("project_id", "other-project", "project_id does not match"),
        ("research_question", "A substituted question", "research_question does not match"),
    ],
)
def test_admission_rejects_tampered_pack_identity(
    tmp_path, field, value, message
):
    review_path = tmp_path / "review.json"
    build_review_pack(
        [make_card()],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[make_document()],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review[field] = value
    review["items"][0]["decision"] = "admit"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        admit_review_pack(
            review_pack_path=review_path,
            cards=[make_card()],
            documents=[make_document()],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=tmp_path / "records.json",
            reviewer="tester",
        )


def test_admission_rejects_tampered_snapshot_or_substituted_source(tmp_path):
    card = make_card()
    document = make_document()
    review_path = tmp_path / "review.json"
    build_review_pack(
        [card],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[document],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["items"][0]["decision"] = "admit"
    review["items"][0]["claim"] = "A modified display claim"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="authoritative review snapshot was modified"):
        admit_review_pack(
            review_pack_path=review_path,
            cards=[card],
            documents=[document],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=tmp_path / "records-a.json",
            reviewer="tester",
        )

    review["items"][0]["claim"] = card.claim
    review_path.write_text(json.dumps(review), encoding="utf-8")
    substituted_document = document.model_copy(
        update={"content_hash": "b" * 64, "text": "Substituted source text."}
    )
    with pytest.raises(ValueError, match="authoritative review snapshot was modified"):
        admit_review_pack(
            review_pack_path=review_path,
            cards=[card],
            documents=[substituted_document],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=tmp_path / "records-b.json",
            reviewer="tester",
        )


def test_admitted_record_keeps_source_provenance_and_semantic_id_changes(tmp_path):
    card = make_card()
    document = make_document()
    record_ids: list[str] = []
    for index, summary in enumerate(("First reviewed summary", "Revised reviewed summary")):
        review_path = tmp_path / f"review-{index}.json"
        records_path = tmp_path / f"records-{index}.json"
        build_review_pack(
            [card],
            project_id="demo",
            research_question="What changed?",
            output_path=review_path,
            documents=[document],
        )
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["items"][0].update(
            {"decision": "revise", "revised_summary": summary}
        )
        review_path.write_text(json.dumps(review), encoding="utf-8")
        admit_review_pack(
            review_pack_path=review_path,
            cards=[card],
            documents=[document],
            expected_project_id="demo",
            expected_research_question="What changed?",
            output_path=records_path,
            reviewer="tester",
        )
        record = EvidenceRecordCollection.model_validate_json(
            records_path.read_text(encoding="utf-8")
        ).records[0]
        record_ids.append(record.evidence_record_id)
        assert record.source_references[0].source_url == document.source_url
        assert record.source_references[0].content_hash == document.content_hash
        assert record.source_references[0].original_excerpt == card.original_excerpt

    assert record_ids[0] != record_ids[1]


def test_release_freeze_and_tamper_detection(tmp_path):
    card = make_card()
    review_path = tmp_path / "review.json"
    records_path = tmp_path / "records.json"
    build_review_pack(
        [card],
        project_id="demo",
        research_question="What changed?",
        output_path=review_path,
        documents=[make_document()],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["items"][0]["decision"] = "admit"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    admit_review_pack(
        review_pack_path=review_path,
        cards=[card],
        documents=[make_document()],
        expected_project_id="demo",
        expected_research_question="What changed?",
        output_path=records_path,
        reviewer="tester",
    )
    collection = EvidenceRecordCollection.model_validate_json(
        records_path.read_text(encoding="utf-8")
    )
    brief = ResearchBrief(
        project_id="demo",
        research_question="What changed?",
        approved_evidence_ids=[collection.records[0].evidence_record_id],
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    context_json, context_md = compile_context(
        brief_path=brief_path,
        evidence_records_path=records_path,
        output_dir=tmp_path / "context",
    )
    report_path = tmp_path / "report.md"
    report_path.write_text("# Result\n", encoding="utf-8")
    release_dir = tmp_path / "release-v1"
    freeze_release(
        release_dir=release_dir,
        report_path=report_path,
        brief_path=brief_path,
        evidence_records_path=records_path,
        context_json_path=context_json,
        context_markdown_path=context_md,
        package_root=Path(__file__).parents[1] / "src" / "research_pipeline",
        reviewed_by="tester",
    )
    assert verify_release(release_dir) == []
    (release_dir / "report.md").write_text("tampered", encoding="utf-8")
    assert any("report.md" in error for error in verify_release(release_dir))
