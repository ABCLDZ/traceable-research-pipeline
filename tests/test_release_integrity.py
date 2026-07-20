from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_pipeline.admission import (
    EvidenceRecordCollection,
    admit_review_pack,
    build_review_pack,
)
from research_pipeline.context import compile_context
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
from research_pipeline.release import freeze_release, sha256_file, verify_release


def _release_inputs(tmp_path: Path) -> dict[str, Path]:
    project_id = "release_integrity"
    question = "What changed?"
    excerpt = "Revenue reached 10 in the first quarter."
    document = DocumentRecord(
        document_id="DOC-001",
        project_id=project_id,
        entity_name="Synthetic Example",
        title="Synthetic quarterly report",
        publisher="Synthetic Example",
        published_at="2026-03-31",
        source_url="https://example.com/report",
        source_type=SourceType.QUARTERLY_REPORT,
        source_tier=SourceTier.TIER_1,
        mime_type=MimeType.HTML,
        content_hash="a" * 64,
        text=excerpt,
        parse_quality=ParseQuality.USABLE,
    )
    card = EvidenceCard(
        evidence_id="EVC-001",
        document_id=document.document_id,
        project_id=project_id,
        topic="revenue_structure",
        evidence_type=EvidenceType.QUANTITATIVE,
        claim="Revenue reached 10.",
        original_excerpt=excerpt,
        source_url=document.source_url,
        publisher=document.publisher,
        published_at=document.published_at,
        source_tier=SourceTier.TIER_1,
        excerpt_verification=ExcerptVerification(
            exact_match=True,
            verification_method="auto_span",
        ),
    )
    review_path = tmp_path / "review.json"
    build_review_pack(
        [card],
        project_id=project_id,
        research_question=question,
        output_path=review_path,
        documents=[document],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["items"][0]["decision"] = "admit"
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    records_path = tmp_path / "records.json"
    admit_review_pack(
        review_pack_path=review_path,
        cards=[card],
        documents=[document],
        expected_project_id=project_id,
        expected_research_question=question,
        output_path=records_path,
        reviewer="tester",
    )
    records = EvidenceRecordCollection.model_validate_json(
        records_path.read_text(encoding="utf-8")
    )
    brief = ResearchBrief(
        project_id=project_id,
        research_question=question,
        approved_evidence_ids=[records.records[0].evidence_record_id],
        open_questions=["Is the result durable?"],
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    context_json, context_md = compile_context(
        brief_path=brief_path,
        evidence_records_path=records_path,
        output_dir=tmp_path / "context",
    )
    report_path = tmp_path / "report.md"
    report_path.write_text("# Synthetic result\n", encoding="utf-8")
    return {
        "brief": brief_path,
        "records": records_path,
        "context_json": context_json,
        "context_md": context_md,
        "report": report_path,
    }


def _freeze(tmp_path: Path, inputs: dict[str, Path]) -> Path:
    release_dir = tmp_path / "release-v1"
    freeze_release(
        release_dir=release_dir,
        report_path=inputs["report"],
        brief_path=inputs["brief"],
        evidence_records_path=inputs["records"],
        context_json_path=inputs["context_json"],
        context_markdown_path=inputs["context_md"],
        package_root=Path(__file__).parents[1] / "src" / "research_pipeline",
        reviewed_by="tester",
    )
    return release_dir


def test_freeze_rejects_unrelated_compiled_context(tmp_path: Path) -> None:
    inputs = _release_inputs(tmp_path)
    inputs["context_json"].write_text(
        '{"project": "unrelated"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="compiled context JSON"):
        _freeze(tmp_path, inputs)
    assert not (tmp_path / "release-v1").exists()


def test_release_contains_source_index_and_default_prompt(tmp_path: Path) -> None:
    release = _freeze(tmp_path, _release_inputs(tmp_path))
    assert verify_release(release) == []
    source_index = json.loads(
        (release / "source_index.json").read_text(encoding="utf-8")
    )
    source = source_index["sources"][0]
    assert source["source_url"] == "https://example.com/report"
    assert source["content_hash"] == "a" * 64
    assert source["original_excerpt"] == "Revenue reached 10 in the first quarter."
    assert list((release / "prompts").glob("*_extract_evidence_v3.md"))


def test_verify_rejects_unmanifested_files(tmp_path: Path) -> None:
    release = _freeze(tmp_path, _release_inputs(tmp_path))
    (release / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    assert "unmanifested file: unexpected.txt" in verify_release(release)


def test_verify_checks_semantics_even_when_hash_is_rewritten(tmp_path: Path) -> None:
    release = _freeze(tmp_path, _release_inputs(tmp_path))
    context_path = release / "compiled_context.json"
    context_path.write_text('{"project": "unrelated"}\n', encoding="utf-8")
    manifest_path = release / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(
        item for item in manifest["files"] if item["path"] == "compiled_context.json"
    )
    entry["sha256"] = sha256_file(context_path)
    entry["bytes"] = context_path.stat().st_size
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    errors = verify_release(release)
    assert any("semantic validation failed" in error for error in errors)
