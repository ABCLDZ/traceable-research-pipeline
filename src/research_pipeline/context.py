"""Compile and validate sparse, auditable research context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_pipeline.admission import (
    EvidenceRecordCollection,
    load_evidence_records,
)
from research_pipeline.io_utils import write_json_atomic, write_text_atomic
from research_pipeline.models import EvidenceRecord, ResearchBrief


CONTEXT_SCHEMA_VERSION = "0.2.0"
CONTEXT_RULES = [
    "Treat EvidenceRecords as admitted evidence, not as guaranteed conclusions.",
    "Do not exceed the stated applicability or prohibited-extrapolation boundaries.",
    "Keep facts, forecasts, policy targets, and management statements distinct.",
    "Preserve counterevidence and unresolved questions in the analysis.",
]


def load_brief(path: str | Path) -> ResearchBrief:
    return ResearchBrief.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _select_records(
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
) -> list[EvidenceRecord]:
    if brief.project_id != collection.project_id:
        raise ValueError("ResearchBrief and EvidenceRecord project IDs differ")
    if brief.research_question != collection.research_question:
        raise ValueError("ResearchBrief and EvidenceRecord research questions differ")
    if not brief.approved_evidence_ids:
        raise ValueError("ResearchBrief.approved_evidence_ids is empty")

    record_by_id = {record.evidence_record_id: record for record in collection.records}
    if len(record_by_id) != len(collection.records):
        raise ValueError("EvidenceRecord collection contains duplicate record IDs")
    missing = sorted(set(brief.approved_evidence_ids) - set(record_by_id))
    if missing:
        raise ValueError(f"ResearchBrief references unknown EvidenceRecords: {missing}")
    if len(brief.approved_evidence_ids) != len(set(brief.approved_evidence_ids)):
        raise ValueError("ResearchBrief.approved_evidence_ids contains duplicates")
    return [record_by_id[record_id] for record_id in brief.approved_evidence_ids]


def build_context_payload(
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
) -> dict[str, Any]:
    selected = _select_records(brief, collection)
    return {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "brief": brief.model_dump(mode="json", exclude_none=True),
        "evidence_records": [
            record.model_dump(mode="json", exclude_none=True) for record in selected
        ],
        "context_rules": CONTEXT_RULES,
    }


def _render_record(record: EvidenceRecord) -> list[str]:
    lines = [
        f"### {record.evidence_record_id}: {record.title}",
        "",
        f"- 类型：`{record.evidence_type.value}`",
        f"- 摘要：{record.summary}",
        f"- 来源文档：{', '.join(record.document_ids)}",
    ]
    if record.time_range:
        lines.append(f"- 时间范围：{record.time_range}")
    if record.geography:
        lines.append(f"- 地理范围：{record.geography}")
    if record.industry_scope:
        lines.append(f"- 行业范围：{record.industry_scope}")
    if record.applicability:
        lines.append(f"- 适用说明：{record.applicability}")
    if record.prohibited_extrapolations:
        lines.append(
            "- 禁止外推：" + "；".join(record.prohibited_extrapolations)
        )
    if record.numeric_values:
        lines.append("- 结构化数值：")
        for value in record.numeric_values:
            pieces = [value.metric_name or "未命名指标", value.value]
            if value.unit:
                pieces.append(value.unit)
            if value.currency:
                pieces.append(value.currency)
            if value.time_range:
                pieces.append(value.time_range)
            lines.append(f"  - {' | '.join(pieces)}")
    lines.append("- 来源定位：")
    for source in record.source_references:
        locator = source.source_url
        if source.page_number is not None:
            locator += f"（第{source.page_number}页）"
        elif source.section:
            locator += f"（{source.section}）"
        lines.append(f"  - {source.title}：{locator}")
    lines.append("- 原文：")
    for excerpt in record.original_excerpts:
        lines.append(f"  > {excerpt.replace(chr(10), ' ')}")
    lines.append("")
    return lines


def render_context_markdown(
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
) -> str:
    selected = _select_records(brief, collection)
    lines = [
        "# 编译研究上下文",
        "",
        "## 研究问题",
        "",
        brief.research_question,
        "",
        f"- 项目：`{brief.project_id}`",
        f"- 资料截止日期：{brief.as_of_date or '未指定'}",
        "",
        "## 范围",
        "",
    ]
    lines.extend(f"- {item}" for item in brief.scope or ["未指定"])
    lines.extend(["", "## 排除项", ""])
    lines.extend(f"- {item}" for item in brief.exclusions or ["未指定"])
    lines.extend(["", "## 当前核心假设（待验证）", ""])
    lines.extend(f"- {item}" for item in brief.core_hypotheses or ["无"])
    lines.extend(["", "## 已知反证", ""])
    lines.extend(f"- {item}" for item in brief.counterevidence or ["无"])
    lines.extend(["", "## 开放问题", ""])
    lines.extend(f"- {item}" for item in brief.open_questions or ["无"])
    lines.extend(["", "## 输出要求", ""])
    lines.extend(f"- {item}" for item in brief.output_requirements or ["无"])
    lines.extend(["", "## 已准入证据", ""])
    for record in selected:
        lines.extend(_render_record(record))
    lines.extend(
        [
            "## 使用边界",
            "",
            "- EvidenceRecord只证明证据已经完成准入，不证明最终结论正确。",
            "- 分析者必须整体阅读证据、反证和开放问题。",
            "- 不得将缺少适用性说明的局部证据自动外推到更大范围。",
        ]
    )
    return "\n".join(lines) + "\n"


def validate_compiled_context(
    *,
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
    context_json_path: str | Path,
    context_markdown_path: str | Path,
) -> None:
    expected_payload = build_context_payload(brief, collection)
    try:
        actual_payload = json.loads(Path(context_json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid compiled context JSON: {exc}") from exc
    if actual_payload != expected_payload:
        raise ValueError(
            "compiled context JSON does not match the approved brief and evidence records"
        )

    expected_markdown = render_context_markdown(brief, collection)
    try:
        actual_markdown = Path(context_markdown_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"invalid compiled context Markdown: {exc}") from exc
    if actual_markdown != expected_markdown:
        raise ValueError(
            "compiled context Markdown does not match the approved brief and evidence records"
        )


def compile_context(
    *,
    brief_path: str | Path,
    evidence_records_path: str | Path,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    brief = load_brief(brief_path)
    collection = load_evidence_records(evidence_records_path)
    payload = build_context_payload(brief, collection)
    markdown = render_context_markdown(brief, collection)

    output = Path(output_dir)
    json_path = write_json_atomic(output / "compiled_context.json", payload)
    markdown_path = write_text_atomic(output / "compiled_context.md", markdown)
    return json_path, markdown_path
