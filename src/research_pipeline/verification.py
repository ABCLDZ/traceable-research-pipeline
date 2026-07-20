"""原文摘录验证模块。

自动验证 EvidenceCard 中的 original_excerpt 是否确实存在于对应的文本块中。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from research_pipeline.models import DocumentChunk, EvidenceCard, ExcerptVerification


def verify_excerpt_in_chunk(
    card: EvidenceCard,
    chunk: DocumentChunk,
) -> ExcerptVerification:
    """验证证据卡中的原文摘录是否在指定 chunk 中。

    验证策略：
    1. 精确匹配（逐字节）
    2. 规范化空白后匹配
    3. 模糊匹配（SequenceMatcher）
    """
    excerpt = card.original_excerpt
    chunk_text = chunk.text

    if not excerpt or not chunk_text:
        return ExcerptVerification(
            exact_match=False,
            verification_method="auto",
        )

    # 1. 精确匹配
    if excerpt in chunk_text:
        return ExcerptVerification(
            exact_match=True,
            verification_method="auto",
        )

    # 2. 规范化空白后匹配
    norm_excerpt = _normalize_whitespace(excerpt)
    norm_chunk = _normalize_whitespace(chunk_text)
    if norm_excerpt in norm_chunk:
        return ExcerptVerification(
            exact_match=False,
            normalized_match=True,
            verification_method="auto",
        )

    # 3. 模糊匹配
    score = SequenceMatcher(None, norm_excerpt, norm_chunk).ratio()
    if score > 0.85:
        return ExcerptVerification(
            exact_match=False,
            normalized_match=False,
            fuzzy_match=True,
            fuzzy_score=score,
            verification_method="auto",
        )

    # 在全文范围内尝试找最佳匹配
    best_score = 0.0
    # 取 excerpt 前 50 个字符尝试滑动匹配
    excerpt_prefix = norm_excerpt[:80]
    if excerpt_prefix:
        for m in re.finditer(re.escape(excerpt_prefix[:20]), norm_chunk):
            window = norm_chunk[m.start():m.start() + len(norm_excerpt) + 50]
            s = SequenceMatcher(None, norm_excerpt, window).ratio()
            if s > best_score:
                best_score = s

    return ExcerptVerification(
        exact_match=False,
        normalized_match=False,
        fuzzy_match=best_score > 0.7,
        fuzzy_score=best_score if best_score > 0 else None,
        verification_method="auto",
    )


def verify_excerpt_in_document(
    card: EvidenceCard,
    chunks: list[DocumentChunk],
) -> ExcerptVerification:
    """遍历 ch unk 查找最佳匹配的原文位置。"""
    best: Optional[ExcerptVerification] = None
    best_score = 0.0

    for chunk in chunks:
        result = verify_excerpt_in_chunk(card, chunk)
        if result.exact_match:
            return result
        if result.normalized_match and (best is None or not best.exact_match):
            best = result
        if result.fuzzy_match and result.fuzzy_score and result.fuzzy_score > best_score:
            best = result
            best_score = result.fuzzy_score

    return best or ExcerptVerification(
        exact_match=False,
        verification_method="auto",
    )


def _normalize_whitespace(text: str) -> str:
    """规范化空白：多空格→单空格，去除首尾。"""
    return re.sub(r"\s+", " ", text).strip()
