"""证据抽取引擎。

按 chunk 调用 DeepSeek 提取证据卡，执行原文回查验证，合并去重。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from research_pipeline.chunker import chunk_document
from research_pipeline.manifest import complete_manifest, create_manifest, save_manifest
from research_pipeline.models import (
    DocumentChunk,
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    NumericValue,
    SourceTier,
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
from research_pipeline.storage import Storage
from research_pipeline.ids import stable_id
from research_pipeline.verification import verify_excerpt_in_chunk, verify_excerpt_in_document


# ── 提示词加载 ──

def load_prompt(prompt_path: str | Path) -> str:
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
    return path.read_text(encoding="utf-8")


# ── JSON 解析 ──

def _try_parse_json(text: str) -> Optional[list[dict[str, Any]]]:
    """从 LLM 输出中提取 JSON 数组。"""
    # 尝试直接解析
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return None
    except json.JSONDecodeError:
        pass

    # 尝试查找 [ 和 ] 之间的内容
    m = re.search(r"\[(.*)\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


# ── 单 chunk 抽取 ──

def extract_from_chunk(
    chunk: DocumentChunk,
    provider: LLMProvider,
    system_prompt: str,
    user_prompt_template: str,
    logger: Optional[CallLogger] = None,
) -> list[EvidenceCard]:
    """从单个 chunk 提取证据卡。"""
    if not chunk.text.strip():
        return []

    user_prompt = user_prompt_template.replace("{{CHUNK_TEXT}}", chunk.text)

    request = LLMRequest(
        prompt_name="extract_evidence",
        prompt_version="v1",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=4096,
        metadata={"chunk_id": chunk.chunk_id},
    )

    response = provider.complete(request)
    if logger:
        logger.log(request, response)

    if response.error:
        print(f"  ⚠️ Chunk {chunk.chunk_index} LLM 错误: {response.error}")
        return []

    raw_cards = _try_parse_json(response.content)
    if raw_cards is None:
        print(f"  ⚠️ Chunk {chunk.chunk_index} JSON 解析失败")
        return []

    cards: list[EvidenceCard] = []
    for rc in raw_cards:
        card = _raw_to_evidence_card(rc, chunk, response)
        if card:
            # 验证原文摘录
            ver = verify_excerpt_in_chunk(card, chunk)
            card.excerpt_verification = ver

            if not ver.exact_match and not ver.normalized_match and not ver.fuzzy_match:
                print(f"  ⚠️ 原文摘录验证失败: {card.original_excerpt[:60]}")
                card.status = "unverified"
            else:
                card.status = "extracted"

            cards.append(card)

    return cards


def _raw_to_evidence_card(
    rc: dict[str, Any],
    chunk: DocumentChunk,
    response: LLMResponse,
) -> Optional[EvidenceCard]:
    """将 LLM 输出的 raw dict 转换为 EvidenceCard。"""
    try:
        evidence_type_str = rc.get("evidence_type", "qualitative")
        try:
            evidence_type = EvidenceType(evidence_type_str)
        except ValueError:
            evidence_type = EvidenceType.QUALITATIVE

        numeric_values: list[NumericValue] = []
        for nv in rc.get("numeric_values", []) or []:
            if isinstance(nv, dict) and nv.get("value"):
                numeric_values.append(NumericValue(
                    value=str(nv["value"]),
                    unit=nv.get("unit"),
                    currency=nv.get("currency"),
                    time_range=nv.get("time_range"),
                    metric_name=nv.get("metric_name"),
                    scope=nv.get("scope"),
                    notes=nv.get("notes"),
                ))

        evidence_id = rc.get("evidence_id") or stable_id(
            "EVC",
            "v1",
            chunk.document_id,
            chunk.chunk_index,
            rc.get("claim", ""),
            rc.get("original_excerpt", ""),
        )

        card = EvidenceCard(
            evidence_id=evidence_id,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            project_id="",
            topic=rc.get("topic", "general"),
            evidence_type=evidence_type,
            claim=rc.get("claim", "").strip(),
            original_excerpt=rc.get("original_excerpt", "").strip(),
            page_number=rc.get("page_number", chunk.page_start),
            section=rc.get("section"),
            source_url="",
            source_tier=SourceTier.TIER_4,
            extraction_method="auto_llm",
            confidence=rc.get("confidence"),
            numeric_values=numeric_values,
            tags=rc.get("tags", []),
            status="unverified",
        )
        return card
    except Exception as e:
        print(f"  ⚠️ 证据卡转换失败: {e}")
        return None


# ── 跨 chunk 去重 ──

def dedup_evidence_cards(cards: list[EvidenceCard]) -> list[EvidenceCard]:
    """按 claim 相似性和原文摘录去重。"""
    seen_claims: set[str] = set()
    result: list[EvidenceCard] = []

    for card in cards:
        # 用 claim 前 80 个字符做去重键
        key = card.claim[:80].strip().lower()
        if key and key not in seen_claims:
            seen_claims.add(key)
            result.append(card)

    return result


# ── 完整抽取流程 ──

def extract_evidence(
    document: DocumentRecord,
    provider: LLMProvider,
    system_prompt: str,
    user_prompt_template: str,
    storage: Storage,
    logger: Optional[CallLogger] = None,
    max_chunk_chars: int = 3000,
) -> list[EvidenceCard]:
    """完整抽取流程：分块 → 逐块抽取 → 验证 → 去重 → 保存。"""
    # 1. 分块
    chunks = chunk_document(
        document.document_id,
        document.text,
        max_chunk_chars=max_chunk_chars,
    )
    print(f"  📦 {len(chunks)} chunks")

    # 2. 逐块抽取
    all_cards: list[EvidenceCard] = []
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i+1}/{len(chunks)} ({len(chunk.text)} chars)...", end=" ")
        cards = extract_from_chunk(chunk, provider, system_prompt, user_prompt_template, logger)
        # 补充缺失字段
        for card in cards:
            card.document_id = document.document_id
            card.project_id = document.project_id
            card.source_url = document.source_url
            card.publisher = document.publisher
            card.published_at = document.published_at
            card.source_tier = document.source_tier
        print(f"{len(cards)} cards")
        all_cards.extend(cards)

    # 3. 去重
    unique = dedup_evidence_cards(all_cards)
    print(f"  🎯 去重后: {len(unique)} cards")

    # 4. 保存
    for card in unique:
        storage.save_evidence(document.project_id, card)

    return unique
