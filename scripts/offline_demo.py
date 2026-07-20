"""Build a synthetic, offline release without network or LLM calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research_pipeline.admission import (
    EvidenceRecordCollection,
    admit_review_pack,
    build_review_pack,
)
from research_pipeline.context import compile_context
from research_pipeline.ids import stable_id
from research_pipeline.io_utils import write_json_atomic, write_text_atomic
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
from research_pipeline.release import freeze_release, verify_release
from research_pipeline.storage import Storage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"demo output already exists: {output}")
    output.mkdir(parents=True)

    data_dir = output / "data"
    project_id = "offline_demo"
    research_question = "示例公司本季度收入发生了什么变化？"
    storage = Storage(data_dir)
    excerpt = "示例公司本季度收入为人民币10亿元，同比增长25%。"
    document = DocumentRecord(
        document_id="DOC-DEMO-001",
        project_id=project_id,
        entity_name="示例公司",
        title="示例公司季度公告",
        publisher="示例公司",
        published_at="2026-06-30",
        source_url="https://example.com/demo-quarterly-report",
        source_type=SourceType.QUARTERLY_REPORT,
        source_tier=SourceTier.TIER_2,
        mime_type=MimeType.HTML,
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        text=excerpt,
        parse_quality=ParseQuality.USABLE,
    )
    storage.save_document(document)
    storage.save_parsed_text(project_id, document.document_id, excerpt)

    card = EvidenceCard(
        evidence_id=stable_id("EVC", document.document_id, "S001", excerpt),
        document_id=document.document_id,
        project_id=project_id,
        topic="revenue_structure",
        evidence_type=EvidenceType.QUANTITATIVE,
        claim="示例公司本季度收入为10亿元，同比增长25%。",
        original_excerpt=excerpt,
        source_url=document.source_url,
        publisher=document.publisher,
        published_at=document.published_at,
        source_tier=document.source_tier,
        extraction_method="offline_demo_span",
        excerpt_verification=ExcerptVerification(
            exact_match=True,
            verification_method="auto_span_exact_source_slice",
        ),
    )
    storage.save_evidence(project_id, card)

    review_path = output / "review_pack.json"
    build_review_pack(
        [card],
        project_id=project_id,
        research_question=research_question,
        output_path=review_path,
        documents=[document],
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["items"][0].update(
        {
            "decision": "admit",
            "record_title": "本季度收入增长",
            "time_range": "2026Q2",
            "geography": "示例范围",
            "applicability": "仅用于演示EvidenceCard到EvidenceRecord的准入流程",
            "prohibited_extrapolations": ["不得将合成示例当作现实公司事实。"],
            "review_notes": "离线演示自动填入的模拟审核结果。",
        }
    )
    write_json_atomic(review_path, review)

    records_path = output / "evidence_records.json"
    admit_review_pack(
        review_pack_path=review_path,
        cards=[card],
        documents=[document],
        expected_project_id=project_id,
        expected_research_question=research_question,
        output_path=records_path,
        reviewer="offline-demo-reviewer",
    )
    collection = EvidenceRecordCollection.model_validate_json(
        records_path.read_text(encoding="utf-8")
    )
    record_id = collection.records[0].evidence_record_id
    brief = ResearchBrief(
        project_id=project_id,
        research_question=research_question,
        scope=["单一公司单一季度的合成演示"],
        exclusions=["不代表真实企业或真实市场"],
        as_of_date="2026-06-30",
        core_hypotheses=["收入增长需要由正式材料和进一步证据验证。"],
        counterevidence=["当前没有成本、利润或现金流证据。"],
        open_questions=["收入增长是否转化为盈利改善？"],
        output_requirements=["明确说明材料为合成示例。"],
        approved_evidence_ids=[record_id],
    )
    brief_path = write_json_atomic(
        output / "research_brief.json",
        brief.model_dump(mode="json", exclude_none=True),
    )
    context_json, context_markdown = compile_context(
        brief_path=brief_path,
        evidence_records_path=records_path,
        output_dir=output / "context",
    )
    report_path = write_text_atomic(
        output / "report.md",
        (
            "# 合成演示报告\n\n"
            "根据唯一一条已准入的合成证据，示例公司本季度收入为10亿元，"
            "同比增长25%。该材料不能外推至真实企业、行业盈利能力或现金流表现。\n"
        ),
    )
    release_dir = output / "release-v1"
    package_root = Path(__file__).resolve().parents[1] / "src" / "research_pipeline"
    freeze_release(
        release_dir=release_dir,
        report_path=report_path,
        brief_path=brief_path,
        evidence_records_path=records_path,
        context_json_path=context_json,
        context_markdown_path=context_markdown,
        package_root=package_root,
        reviewed_by="offline-demo-reviewer",
    )
    errors = verify_release(release_dir)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: offline demo release verified at {release_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
