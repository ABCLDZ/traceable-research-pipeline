"""证据抽取引擎 V2 — 基于 span-selection 协议。

模型返回句子 ID，代码拼装原文摘录，实现 100% 原文绑定。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from research_pipeline.chunker import (
    build_excerpt_from_spans,
    build_text_with_ids,
    chunk_document,
)
from research_pipeline.models import (
    DocumentChunk,
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    ExcerptVerification,
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
from research_pipeline.verification import verify_excerpt_in_chunk


def load_prompt(prompt_path: str | Path) -> str:
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
    return path.read_text(encoding="utf-8")


def _try_parse_json(text: str) -> Optional[list[dict[str, Any]]]:
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
    m = re.search(r"\[(.*)\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


def extract_from_chunk_v2(
    chunk: DocumentChunk,
    provider: LLMProvider,
    system_prompt: str,
    user_prompt_template: str,
    logger: Optional[CallLogger] = None,
) -> list[EvidenceCard]:
    """V2 抽取：模型选句子 ID，代码拼 excerpt。"""
    if not chunk.text.strip():
        return []

    # 生成带 [S001] 标记的文本
    tagged_text = build_text_with_ids(chunk)
    user_prompt = user_prompt_template.replace("{{CHUNK_TEXT}}", tagged_text)

    request = LLMRequest(
        prompt_name="extract_evidence_v2",
        prompt_version="v2",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=2048,
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
        card = _raw_to_card_v2(rc, chunk)
        if card:
            cards.append(card)

    return cards


def _raw_to_card_v2(
    rc: dict[str, Any],
    chunk: DocumentChunk,
) -> Optional[EvidenceCard]:
    """V2: 从 LLM 输出转换，用 sentence_ids 拼装 excerpt。"""
    try:
        sentence_ids = rc.get("sentence_ids", [])
        if not sentence_ids:
            return None

        # 代码拼装原文摘录
        excerpt, all_found = build_excerpt_from_spans(chunk, sentence_ids)
        if not excerpt.strip():
            return None

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

        eid = rc.get("evidence_id") or stable_id(
            "EVC",
            "v2",
            chunk.document_id,
            chunk.chunk_index,
            rc.get("claim", ""),
            sentence_ids,
        )

        card = EvidenceCard(
            evidence_id=eid,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            project_id="",
            topic=rc.get("topic", "general"),
            evidence_type=evidence_type,
            claim=rc.get("claim", "").strip(),
            original_excerpt=excerpt,
            page_number=chunk.page_start,
            section=rc.get("section"),
            source_url="",
            source_tier=SourceTier.TIER_4,
            extraction_method="auto_llm_v2",
            confidence=rc.get("confidence"),
            numeric_values=numeric_values,
            tags=rc.get("tags", []),
            status="extracted",
            verified_at=None,
            excerpt_verification=ExcerptVerification(
                exact_match=True,
                verification_method="auto_span",
            ),
        )
        return card
    except Exception as e:
        print(f"  ⚠️ 证据卡转换失败: {e}")
        return None


def dedup_evidence_cards(cards: list[EvidenceCard]) -> list[EvidenceCard]:
    seen_claims: set[str] = set()
    result = []
    for card in cards:
        key = card.claim[:80].strip().lower()
        if key and key not in seen_claims:
            seen_claims.add(key)
            result.append(card)
    return result


def extract_evidence_v2(
    document: DocumentRecord,
    provider: LLMProvider,
    system_prompt: str,
    user_prompt_template: str,
    storage: Storage,
    logger: Optional[CallLogger] = None,
    max_chunk_chars: int = 3000,
) -> list[EvidenceCard]:
    """完整 V2 抽取流程：分块 → 标注句子ID → 逐块抽取（选ID）→ 拼装 → 去重 → 保存。"""
    chunks = chunk_document(
        document.document_id,
        document.text,
        max_chunk_chars=max_chunk_chars,
    )
    print(f"  📦 {len(chunks)} chunks（已标注句子ID）")

    all_cards = []
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i+1}/{len(chunks)} ({len(chunk.text)} chars)...", end=" ")
        cards = extract_from_chunk_v2(chunk, provider, system_prompt, user_prompt_template, logger)
        for card in cards:
            card.document_id = document.document_id
            card.project_id = document.project_id
            card.source_url = document.source_url
            card.publisher = document.publisher
            card.published_at = document.published_at
            card.source_tier = document.source_tier
        print(f"{len(cards)} cards")
        all_cards.extend(cards)

    unique = dedup_evidence_cards(all_cards)
    print(f"  🎯 去重后: {len(unique)} cards")

    for card in unique:
        storage.save_evidence(document.project_id, card)

    return unique
