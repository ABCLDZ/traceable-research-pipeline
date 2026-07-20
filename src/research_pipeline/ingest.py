"""采集工作流：配置 → 抓取 → 解析 → 保存 → 去重。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from research_pipeline.config import load_config
from research_pipeline.dedup import dedup_by_hash, normalize_url
from research_pipeline.fetcher import fetch_url
from research_pipeline.models import (
    DocumentRecord,
    EvidenceCard,
    FetchStatus,
    IngestStats,
    MimeType,
    ParseStatus,
    ProjectConfig,
    SourceTier,
    SourceType,
)
from research_pipeline.parser import extract_text
from research_pipeline.quality import assess_parse_quality
from research_pipeline.storage import Storage
from research_pipeline.url_policy import validate_public_url

# 简单 MIME 类型到 MimeType 枚举映射
MIME_MAP: dict[str, MimeType] = {
    "text/html": MimeType.HTML,
    "application/pdf": MimeType.PDF,
    "text/plain": MimeType.PLAIN_TEXT,
    "text/markdown": MimeType.MARKDOWN,
    "application/json": MimeType.JSON,
}


def _detect_mime(mime_str: Optional[str], url: str) -> MimeType:
    """从 MIME 字符串或 URL 扩展名推断 MimeType。"""
    if mime_str:
        # 取出主类型（如 "text/html; charset=utf-8" → "text/html"）
        base = mime_str.split(";")[0].strip().lower()
        if base in MIME_MAP:
            return MIME_MAP[base]

    # fallback: 从 URL 后缀判断
    lower_url = url.lower()
    if lower_url.endswith(".pdf") or "pdf" in lower_url:
        return MimeType.PDF
    elif lower_url.endswith(".html") or lower_url.endswith(".htm"):
        return MimeType.HTML
    elif lower_url.endswith(".txt"):
        return MimeType.PLAIN_TEXT
    elif lower_url.endswith(".json"):
        return MimeType.JSON

    return MimeType.UNKNOWN


def _detect_source_type(publisher: Optional[str], url: str) -> SourceType:
    """简单规则判断资料类型。"""
    lower_url = url.lower()
    if any(x in lower_url for x in ["sec.gov", "exchange", "filing"]):
        return SourceType.EXCHANGE_FILING
    elif any(x in lower_url for x in ["investor", "ir.", "earnings"]):
        if any(x in lower_url for x in ["presentation", "slide", "deck"]):
            return SourceType.INVESTOR_PRESENTATION
        return SourceType.EARNINGS_RELEASE
    elif any(x in lower_url for x in ["annual-report", "10-k", "10k", "20-f", "20f"]):
        return SourceType.ANNUAL_REPORT
    elif any(x in lower_url for x in ["eia.gov", "ferc.gov", "nerc.com", "energy.gov"]):
        return SourceType.GOVERNMENT_REPORT
    elif any(x in lower_url for x in ["iea.", "imf.", "worldbank"]):
        return SourceType.INDUSTRY_REPORT
    return SourceType.OTHER


def _detect_source_tier(source_type: SourceType, publisher: Optional[str]) -> SourceTier:
    """根据资料类型和发布者推断来源等级。"""
    if source_type in (
        SourceType.EXCHANGE_FILING,
        SourceType.ANNUAL_REPORT,
    ):
        return SourceTier.TIER_1
    elif source_type in (
        SourceType.EARNINGS_RELEASE,
        SourceType.INVESTOR_PRESENTATION,
    ):
        return SourceTier.TIER_2
    elif source_type in (
        SourceType.GOVERNMENT_REPORT,
        SourceType.INDUSTRY_REPORT,
    ):
        return SourceTier.TIER_3
    return SourceTier.TIER_4


def ingest_single_url(
    url: str,
    project_id: str,
    entity_name: str,
    storage: Storage,
    config: ProjectConfig,
) -> tuple[Optional[DocumentRecord], IngestStats]:
    """抓取并解析单个 URL，返回 DocumentRecord。"""
    stats = IngestStats(project_id=project_id)

    # 1. 抓取
    allowed, reason = validate_public_url(
        url,
        allowed_domains=config.source_policy.allowed_domains,
        blocked_domains=config.source_policy.blocked_domains,
    )
    if not allowed:
        stats.failed += 1
        return None, stats

    content_bytes, content_type, fetch_record = fetch_url(
        url,
        allowed_domains=config.source_policy.allowed_domains,
        blocked_domains=config.source_policy.blocked_domains,
    )
    if content_bytes is None:
        stats.failed += 1
        return None, stats
    stats.fetched += 1

    # 2. 检测 MIME 类型
    mime = _detect_mime(content_type, url)

    # 3. 解析正文
    parsed_text, detected_mime_str, parse_error = extract_text(content_bytes, mime.value, url)
    if parsed_text and len(parsed_text) > 20:
        parse_status = ParseStatus.SUCCESS
        if "html" in mime.value:
            stats.parsed_html += 1
        elif "pdf" in mime.value:
            stats.parsed_pdf += 1
    else:
        parse_status = ParseStatus.FAILED
        stats.parse_failed += 1
    parse_quality, table_preservation, manual_review_required, quality_signals = (
        assess_parse_quality(
            mime_type=mime,
            text=parsed_text,
            parse_error=parse_error,
        )
    )

    # 4. 生成 document_id
    content_hash = storage.hash_content(content_bytes)
    doc_id = f"{project_id}__{content_hash[:12]}"

    # 5. 构建 DocumentRecord
    source_type = _detect_source_type(None, url)
    source_tier = _detect_source_tier(source_type, None)
    # 如果最终 URL 和原始 URL 不一样用最终 URL
    final_url = fetch_record.final_url or url

    doc = DocumentRecord(
        document_id=doc_id,
        project_id=project_id,
        entity_name=entity_name,
        title=url,  # 占位，解析后可能更新
        source_url=url,
        final_url=final_url,
        source_type=source_type,
        source_tier=source_tier,
        mime_type=mime,
        content_hash=content_hash,
        text=parsed_text,
        fetch_status=FetchStatus.SUCCESS,
        parse_status=parse_status,
        parse_quality=parse_quality,
        table_preservation=table_preservation,
        manual_review_required=manual_review_required,
        quality_signals=quality_signals,
        fetch_record=fetch_record,
    )

    # 6. 保存原始文件和解析文本
    raw_path = storage.save_raw(project_id, doc_id, content_bytes, mime.value)
    doc.raw_path = str(raw_path)

    if parsed_text:
        parsed_path = storage.save_parsed_text(project_id, doc_id, parsed_text)
        doc.parsed_path = str(parsed_path)
    storage.save_document(doc)

    stats.total_documents += 1
    return doc, stats


def ingest_project(
    config_path: str | Path,
    data_dir: str | Path,
) -> tuple[list[DocumentRecord], IngestStats]:
    """完整采集流程：加载配置 → 逐 URL 抓取 → 去重。"""
    start = time.monotonic()
    config = load_config(config_path)
    storage = Storage(data_dir)

    all_stats = IngestStats(project_id=config.project_id)
    documents: list[DocumentRecord] = []

    urls = config.seed_urls
    if not urls:
        print("⚠️  没有 seed URLs，跳过采集。")
        return [], all_stats

    print(f"📋 开始采集项目 '{config.project_id}'，共 {len(urls)} 个 URL")
    all_stats.total_urls = len(urls)

    for idx, url in enumerate(urls, 1):
        print(f"  [{idx}/{len(urls)}] {url[:80]}...", end=" ")
        doc, stats = ingest_single_url(
            url=url,
            project_id=config.project_id,
            entity_name=config.entity.name,
            storage=storage,
            config=config,
        )
        if doc:
            documents.append(doc)
            print(f"✅ ({len(doc.text)} chars)")
        else:
            print(f"❌ ({stats.failed} failures)")

        # 合并统计
        all_stats.fetched += stats.fetched
        all_stats.failed += stats.failed
        all_stats.parsed_html += stats.parsed_html
        all_stats.parsed_pdf += stats.parsed_pdf
        all_stats.parse_failed += stats.parse_failed

    # 去重
    unique, dups = dedup_by_hash(documents)
    all_stats.duplicates_removed = len(dups)
    all_stats.total_documents = len(unique)

    # 来源等级统计
    for doc in unique:
        tier_key = doc.source_tier.value
        all_stats.tier_breakdown[tier_key] = all_stats.tier_breakdown.get(tier_key, 0) + 1

    all_stats.total_duration_ms = int((time.monotonic() - start) * 1000)

    print(f"\n✅ 采集完成: {len(unique)} 去重文档, "
          f"{all_stats.duplicates_removed} 重复移除, "
          f"{all_stats.failed} 失败")

    return unique, all_stats
