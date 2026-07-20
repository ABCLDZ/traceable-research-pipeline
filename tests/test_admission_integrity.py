from __future__ import annotations

import json

import pytest

from research_pipeline.admission import (
    EvidenceRecordCollection,
    admit_review_pack,
    build_review_pack,
)
from research_pipeline.models import (
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    ExcerptVerification,
    MimeType,
    ParseQuality,
    SourceTier,
    SourceType,
)


def _card() -> EvidenceCard:
    return EvidenceCard(
        evidence_id="EVC-001",
        document_id="DOC-001",
        project_id="demo",
        topic="general",
        evidence_type=EvidenceType.QUALITATIVE,
        claim="The source reports a material change.",
        original_excerpt="The source reports a material change.",
        source_url="https://example.com/report",
        source_tier=SourceTier.TIER_1,
        excerpt_verification=ExcerptVerification(
            exact_match=True,
            verification_method="auto_span",
        ),
    )


def _document() -> DocumentRecord:
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
        text="The source reports a material change.",
        parse_quality=ParseQuality.USABLE,
    )


def _build(tmp_path, card: EvidenceCard, document: DocumentRecord):
    path = tmp_path / "review.json"
    build_review_pack(
        [card],
        project_id="demo",
        research_question="What changed?",
        output_path=path,
        documents=[document],
    )
    return path, json.loads(path.read_text(encoding="utf-8"))


def _admit(review_path, tmp_path, card, document):
    return admit_review_pack(
        review_pack_path=review_path,
        cards=[card],
        documents=[document],
        expected_project_id="demo",
        expected_research_question="What changed?",
        output_path=tmp_path / "records.json",
        reviewer="tester",
    )


def test_exact_excerpt_is_rechecked_against_authoritative_document(tmp_path):
    card = _card()
    document = _document().model_copy(update={"text": "Different source text."})
    review_path, review = _build(tmp_path, card, document)
    assert "original_excerpt_not_found_in_source_document" in (
        review["items"][0]["automatic_blockers"]
    )
    review["items"][0].update(
        {
            "decision": "admit",
            "manual_override_reason": "A reviewer explicitly accepts this exception.",
        }
    )
    review_path.write_text(json.dumps(review), encoding="utf-8")
    records_path = _admit(review_path, tmp_path, card, document)
    record = EvidenceRecordCollection.model_validate_json(
        records_path.read_text(encoding="utf-8")
    ).records[0]
    assert "A reviewer explicitly accepts this exception." in record.review_notes


def test_card_url_is_rechecked_against_authoritative_document(tmp_path):
    card = _card().model_copy(update={"source_url": "https://other.example/report"})
    document = _document()
    review_path, review = _build(tmp_path, card, document)
    assert "card_source_url_does_not_match_source_document" in (
        review["items"][0]["automatic_blockers"]
    )
    review["items"][0]["decision"] = "admit"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="no manual_override_reason"):
        _admit(review_path, tmp_path, card, document)


def test_undisplayed_card_content_cannot_be_substituted_after_review(tmp_path):
    card = _card()
    document = _document()
    review_path, review = _build(tmp_path, card, document)
    review["items"][0]["decision"] = "admit"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    substituted = card.model_copy(update={"tags": ["substituted-after-review"]})
    with pytest.raises(ValueError, match="authoritative_card_sha256"):
        _admit(review_path, tmp_path, substituted, document)


def test_displayed_excerpt_is_read_only_in_review_pack(tmp_path):
    card = _card()
    document = _document()
    review_path, review = _build(tmp_path, card, document)
    review["items"][0].update(
        {
            "decision": "admit",
            "original_excerpt": "A reviewer-edited excerpt.",
        }
    )
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="original_excerpt"):
        _admit(review_path, tmp_path, card, document)
