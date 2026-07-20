"""Batch review and admission of candidate EvidenceCards."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from research_pipeline.ids import canonical_json, stable_id
from research_pipeline.io_utils import write_json_atomic
from research_pipeline.models import (
    DocumentRecord,
    EvidenceCard,
    EvidenceRecord,
    EvidenceRecordStatus,
    EvidenceSourceReference,
    EvidenceType,
    NumericValue,
)


class ReviewDecision(str, Enum):
    PENDING = "pending"
    ADMIT = "admit"
    REJECT = "reject"
    MERGE = "merge"
    REVISE = "revise"


class ReviewItem(BaseModel):
    card_id: str
    authoritative_card_sha256: str
    document_id: str
    authoritative_document_sha256: str
    claim: str
    original_excerpt: str
    evidence_type: EvidenceType
    automatic_blockers: list[str] = Field(default_factory=list)
    automatic_warnings: list[str] = Field(default_factory=list)
    source_parse_quality: str = "unknown"
    manual_source_review_required: bool = False
    source_quality_signals: list[str] = Field(default_factory=list)
    decision: ReviewDecision = ReviewDecision.PENDING
    merge_group: str | None = None
    record_title: str | None = None
    revised_summary: str | None = None
    time_range: str | None = None
    geography: str | None = None
    industry_scope: str | None = None
    applicability: str | None = None
    prohibited_extrapolations: list[str] = Field(default_factory=list)
    review_notes: str | None = None
    manual_override_reason: str | None = None


class ReviewPack(BaseModel):
    schema_version: str = "0.2.0"
    project_id: str
    research_question: str
    created_at: datetime
    instructions: list[str]
    items: list[ReviewItem]


class EvidenceRecordCollection(BaseModel):
    schema_version: str = "0.2.0"
    project_id: str
    research_question: str
    reviewer: str
    admitted_at: datetime
    source_review_pack_sha256: str
    records: list[EvidenceRecord]


def _checks(card: EvidenceCard) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    verification = card.excerpt_verification
    if verification is None or not verification.exact_match:
        blockers.append("original_excerpt_is_not_exactly_bound")
    if not card.document_id:
        blockers.append("missing_document_id")
    if not card.original_excerpt.strip():
        blockers.append("empty_original_excerpt")
    if not card.claim.strip():
        blockers.append("empty_claim")
    if not card.source_url:
        warnings.append("missing_source_url")
    if not card.published_at:
        warnings.append("missing_published_at")
    if card.evidence_type == EvidenceType.QUANTITATIVE and not card.numeric_values:
        warnings.append("quantitative_card_has_no_structured_numeric_value")
    return blockers, warnings


def _payload_sha256(payload: dict[str, Any]) -> str:
    encoded = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _card_sha256(card: EvidenceCard) -> str:
    payload = card.model_dump(mode="json", exclude_none=True)
    payload.pop("verified_at", None)
    verification = payload.get("excerpt_verification")
    if isinstance(verification, dict):
        verification.pop("verified_at", None)
    return _payload_sha256(payload)


def _document_sha256(document: DocumentRecord) -> str:
    payload = document.model_dump(mode="json", exclude_none=True)
    payload.pop("retrieved_at", None)
    payload.pop("raw_path", None)
    payload.pop("parsed_path", None)
    fetch_record = payload.get("fetch_record")
    if isinstance(fetch_record, dict):
        fetch_record.pop("fetched_at", None)
        fetch_record.pop("fetch_duration_ms", None)
    return _payload_sha256(payload)


def _document_checks(document: DocumentRecord) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if document.parse_quality.value == "failed":
        blockers.append("source_document_parse_failed")
    elif document.manual_review_required:
        warnings.append("source_document_requires_manual_review")
    return blockers, warnings


def _cross_checks(
    card: EvidenceCard,
    document: DocumentRecord,
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if card.original_excerpt not in document.text:
        blockers.append("original_excerpt_not_found_in_source_document")
    accepted_urls = {document.source_url}
    if document.final_url:
        accepted_urls.add(document.final_url)
    if card.source_url not in accepted_urls:
        blockers.append("card_source_url_does_not_match_source_document")
    return blockers, warnings


def build_review_pack(
    cards: list[EvidenceCard],
    *,
    project_id: str,
    research_question: str,
    output_path: str | Path,
    documents: list[DocumentRecord],
) -> Path:
    documents_by_id = {document.document_id: document for document in documents}
    if len(documents_by_id) != len(documents):
        raise ValueError("documents contain duplicate document IDs")
    items: list[ReviewItem] = []
    for card in sorted(cards, key=lambda item: (item.document_id, item.evidence_id)):
        if card.project_id != project_id:
            raise ValueError(
                f"{card.evidence_id} belongs to project {card.project_id!r}, "
                f"not {project_id!r}"
            )
        blockers, warnings = _checks(card)
        document = documents_by_id.get(card.document_id)
        if document is None:
            raise ValueError(
                f"source document {card.document_id!r} for {card.evidence_id} is missing"
            )
        if document.project_id != project_id:
            raise ValueError(
                f"{document.document_id} belongs to project {document.project_id!r}, "
                f"not {project_id!r}"
            )
        document_blockers, document_warnings = _document_checks(document)
        blockers.extend(document_blockers)
        warnings.extend(document_warnings)
        cross_blockers, cross_warnings = _cross_checks(card, document)
        blockers.extend(cross_blockers)
        warnings.extend(cross_warnings)
        items.append(
            ReviewItem(
                card_id=card.evidence_id,
                authoritative_card_sha256=_card_sha256(card),
                document_id=card.document_id,
                authoritative_document_sha256=_document_sha256(document),
                claim=card.claim,
                original_excerpt=card.original_excerpt,
                evidence_type=card.evidence_type,
                automatic_blockers=blockers,
                automatic_warnings=warnings,
                source_parse_quality=document.parse_quality.value,
                manual_source_review_required=document.manual_review_required,
                source_quality_signals=document.quality_signals,
            )
        )
    pack = ReviewPack(
        project_id=project_id,
        research_question=research_question,
        created_at=datetime.now(timezone.utc),
        instructions=[
            "Set every decision to admit, reject, merge, or revise.",
            "Merge items must share a non-empty merge_group.",
            "Use manual_override_reason before admitting an item with automatic blockers.",
            "Only decision, merge/revision fields, notes, and override reasons are editable.",
            "All card/source snapshots and automatic checks are verified again at admission.",
            "This file is applied as one batch; pending items block the whole admission.",
        ],
        items=items,
    )
    return write_json_atomic(output_path, pack.model_dump(mode="json", exclude_none=True))


def _dedupe_numeric_values(cards: list[EvidenceCard]) -> list[NumericValue]:
    values: list[NumericValue] = []
    seen: set[str] = set()
    for card in cards:
        for value in card.numeric_values:
            key = value.model_dump_json(exclude_none=True)
            if key not in seen:
                seen.add(key)
                values.append(value)
    return values


def _single_override(items: list[ReviewItem], field: str) -> Any:
    values = {
        getattr(item, field)
        for item in items
        if getattr(item, field) not in (None, "", [])
    }
    if len(values) > 1:
        raise ValueError(f"conflicting {field} values in merge group")
    return next(iter(values), None)


def _build_record(
    *,
    cards: list[EvidenceCard],
    items: list[ReviewItem],
    project_id: str,
    research_question: str,
    reviewer: str,
    reviewed_at: datetime,
    documents_by_id: dict[str, DocumentRecord],
) -> EvidenceRecord:
    cards = sorted(cards, key=lambda card: card.evidence_id)
    card_ids = sorted(card.evidence_id for card in cards)
    document_ids = sorted({card.document_id for card in cards})
    evidence_types = {card.evidence_type for card in cards}
    if len(evidence_types) == 1:
        evidence_type = next(iter(evidence_types))
    else:
        evidence_type = EvidenceType.QUALITATIVE

    revised_summary = _single_override(items, "revised_summary")
    title = _single_override(items, "record_title")
    summary = revised_summary or " ".join(card.claim.strip() for card in cards)
    title = title or summary[:120]
    time_range = _single_override(items, "time_range")
    if time_range is None:
        observed_ranges = {
            value.time_range
            for card in cards
            for value in card.numeric_values
            if value.time_range
        }
        time_range = next(iter(observed_ranges)) if len(observed_ranges) == 1 else None

    source_references = [
        EvidenceSourceReference(
            card_id=card.evidence_id,
            document_id=card.document_id,
            source_url=card.source_url,
            title=documents_by_id[card.document_id].title,
            publisher=(
                documents_by_id[card.document_id].publisher or card.publisher
            ),
            published_at=(
                documents_by_id[card.document_id].published_at or card.published_at
            ),
            content_hash=documents_by_id[card.document_id].content_hash,
            page_number=card.page_number,
            section=card.section,
            original_excerpt=card.original_excerpt,
        )
        for card in cards
    ]
    geography = _single_override(items, "geography")
    industry_scope = _single_override(items, "industry_scope")
    applicability = _single_override(items, "applicability")
    prohibited_extrapolations = sorted(
        {
            limitation
            for item in items
            for limitation in item.prohibited_extrapolations
        }
    )
    numeric_values = _dedupe_numeric_values(cards)
    review_notes = _single_override(items, "review_notes")
    override_notes = sorted(
        f"{item.card_id}: {item.manual_override_reason.strip()}"
        for item in items
        if item.manual_override_reason and item.manual_override_reason.strip()
    )
    if override_notes:
        override_text = "Manual overrides: " + " | ".join(override_notes)
        review_notes = (
            f"{review_notes}\n{override_text}" if review_notes else override_text
        )
    semantic_identity = {
        "project_id": project_id,
        "research_question": research_question,
        "card_ids": card_ids,
        "document_ids": document_ids,
        "title": title,
        "summary": summary,
        "evidence_type": evidence_type.value,
        "source_references": [
            reference.model_dump(mode="json", exclude_none=True)
            for reference in source_references
        ],
        "numeric_values": [
            value.model_dump(mode="json", exclude_none=True)
            for value in numeric_values
        ],
        "time_range": time_range,
        "geography": geography,
        "industry_scope": industry_scope,
        "applicability": applicability,
        "prohibited_extrapolations": prohibited_extrapolations,
    }

    return EvidenceRecord(
        evidence_record_id=stable_id("EVR", semantic_identity),
        project_id=project_id,
        research_question=research_question,
        card_ids=card_ids,
        document_ids=document_ids,
        title=title,
        summary=summary,
        evidence_type=evidence_type,
        original_excerpts=[card.original_excerpt for card in cards],
        source_references=source_references,
        numeric_values=numeric_values,
        time_range=time_range,
        geography=geography,
        industry_scope=industry_scope,
        applicability=applicability,
        prohibited_extrapolations=prohibited_extrapolations,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        review_notes=review_notes,
        status=EvidenceRecordStatus.ADMITTED,
    )


def admit_review_pack(
    *,
    review_pack_path: str | Path,
    cards: list[EvidenceCard],
    documents: list[DocumentRecord],
    expected_project_id: str,
    expected_research_question: str,
    output_path: str | Path,
    reviewer: str,
) -> Path:
    pack_path = Path(review_pack_path)
    raw = pack_path.read_bytes()
    pack = ReviewPack.model_validate_json(raw)
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if pack.project_id != expected_project_id:
        raise ValueError(
            "review pack project_id does not match the approved project configuration"
        )
    if pack.research_question != expected_research_question:
        raise ValueError(
            "review pack research_question does not match the approved project configuration"
        )

    by_id = {card.evidence_id: card for card in cards}
    if len(by_id) != len(cards):
        raise ValueError("cards contain duplicate evidence IDs")
    documents_by_id = {document.document_id: document for document in documents}
    if len(documents_by_id) != len(documents):
        raise ValueError("documents contain duplicate document IDs")
    for card in cards:
        if card.project_id != expected_project_id:
            raise ValueError(
                f"{card.evidence_id} belongs to an unexpected project"
            )
        if card.document_id not in documents_by_id:
            raise ValueError(
                f"source document {card.document_id!r} for {card.evidence_id} is missing"
            )
    for document in documents_by_id.values():
        if document.project_id != expected_project_id:
            raise ValueError(
                f"{document.document_id} belongs to an unexpected project"
            )

    pack_ids = [item.card_id for item in pack.items]
    if len(pack_ids) != len(set(pack_ids)):
        raise ValueError("review pack contains duplicate card IDs")
    if set(pack_ids) != set(by_id):
        missing = sorted(set(pack_ids) - set(by_id))
        extra = sorted(set(by_id) - set(pack_ids))
        raise ValueError(f"review pack/card inventory mismatch; missing={missing}, extra={extra}")

    for item in pack.items:
        card = by_id[item.card_id]
        document = documents_by_id[card.document_id]
        blockers, warnings = _checks(card)
        document_blockers, document_warnings = _document_checks(document)
        blockers.extend(document_blockers)
        warnings.extend(document_warnings)
        cross_blockers, cross_warnings = _cross_checks(card, document)
        blockers.extend(cross_blockers)
        warnings.extend(cross_warnings)
        expected_snapshot = {
            "authoritative_card_sha256": _card_sha256(card),
            "document_id": card.document_id,
            "authoritative_document_sha256": _document_sha256(document),
            "claim": card.claim,
            "original_excerpt": card.original_excerpt,
            "evidence_type": card.evidence_type,
            "automatic_blockers": blockers,
            "automatic_warnings": warnings,
            "source_parse_quality": document.parse_quality.value,
            "manual_source_review_required": document.manual_review_required,
            "source_quality_signals": document.quality_signals,
        }
        changed = [
            field
            for field, expected in expected_snapshot.items()
            if getattr(item, field) != expected
        ]
        if changed:
            raise ValueError(
                f"{item.card_id} authoritative review snapshot was modified "
                f"({', '.join(changed)}); rebuild the review pack"
            )

    pending = [item.card_id for item in pack.items if item.decision == ReviewDecision.PENDING]
    if pending:
        raise ValueError(f"review pack still has {len(pending)} pending decisions")

    admitted_items = [
        item
        for item in pack.items
        if item.decision in {ReviewDecision.ADMIT, ReviewDecision.MERGE, ReviewDecision.REVISE}
    ]
    for item in admitted_items:
        authoritative_blockers, _ = _checks(by_id[item.card_id])
        document_blockers, _ = _document_checks(
            documents_by_id[by_id[item.card_id].document_id]
        )
        authoritative_blockers.extend(document_blockers)
        cross_blockers, _ = _cross_checks(
            by_id[item.card_id],
            documents_by_id[by_id[item.card_id].document_id],
        )
        authoritative_blockers.extend(cross_blockers)
        if authoritative_blockers and not (
            item.manual_override_reason and item.manual_override_reason.strip()
        ):
            raise ValueError(
                f"{item.card_id} has automatic blockers and no manual_override_reason"
            )
        if item.decision == ReviewDecision.MERGE and not item.merge_group:
            raise ValueError(f"{item.card_id} is marked merge without merge_group")
        if item.decision == ReviewDecision.REVISE and not item.revised_summary:
            raise ValueError(f"{item.card_id} is marked revise without revised_summary")

    grouped: dict[str, list[ReviewItem]] = defaultdict(list)
    for item in admitted_items:
        key = item.merge_group if item.decision == ReviewDecision.MERGE else item.card_id
        grouped[key].append(item)
    for key, items in grouped.items():
        if any(item.decision == ReviewDecision.MERGE for item in items) and len(items) < 2:
            raise ValueError(f"merge group {key} must contain at least two cards")

    admitted_at = datetime.now(timezone.utc)
    records = [
        _build_record(
            cards=[by_id[item.card_id] for item in items],
            items=items,
            project_id=pack.project_id,
            research_question=pack.research_question,
            reviewer=reviewer,
            reviewed_at=admitted_at,
            documents_by_id=documents_by_id,
        )
        for _, items in sorted(grouped.items())
    ]
    collection = EvidenceRecordCollection(
        project_id=pack.project_id,
        research_question=pack.research_question,
        reviewer=reviewer,
        admitted_at=admitted_at,
        source_review_pack_sha256=hashlib.sha256(raw).hexdigest(),
        records=records,
    )
    return write_json_atomic(
        output_path,
        collection.model_dump(mode="json", exclude_none=True),
    )


def load_evidence_records(path: str | Path) -> EvidenceRecordCollection:
    return EvidenceRecordCollection.model_validate_json(Path(path).read_text(encoding="utf-8"))
