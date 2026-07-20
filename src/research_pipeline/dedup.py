"""去重模块。

支持：
- 完全 URL 规范化与去重
- 完全相同内容的 SHA-256 哈希去重
- 标题和正文高度相似的近重复检测（简化版）
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

from research_pipeline.models import DocumentRecord


# ── URL 去重 ──

def normalize_url(url: str) -> str:
    """标准化 URL：去掉 fragment、规范化 scheme、去掉尾部 slash（根路径除外）。"""
    parsed = urlparse(url)
    # 统一 scheme 为小写
    scheme = parsed.scheme.lower()
    # 去掉 fragment
    fragment = ""
    # 去掉 www. 前缀
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # 去掉尾部斜杠（根路径保留）
    path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path

    # query 保持原样
    normalized = urlunparse((scheme, netloc, path, parsed.params, parsed.query, fragment))
    return normalized


def dedup_urls(urls: list[str]) -> list[str]:
    """URL 去重：标准化后去重，保持原始顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        norm = normalize_url(url)
        if norm not in seen:
            seen.add(norm)
            result.append(url)
    return result


# ── 内容哈希去重 ──

def content_hash(text: str) -> str:
    """计算文本的 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dedup_by_hash(
    documents: list[DocumentRecord],
) -> tuple[list[DocumentRecord], list[DocumentRecord]]:
    """按内容哈希去重。

    Returns:
        (unique_documents, duplicates)
    """
    seen: set[str] = set()
    unique: list[DocumentRecord] = []
    duplicates: list[DocumentRecord] = []

    for doc in documents:
        if doc.content_hash in seen:
            duplicates.append(doc)
        else:
            seen.add(doc.content_hash)
            unique.append(doc)

    return unique, duplicates


# ── 近重复检测（简化版） ──

def _simple_normalize(text: str) -> str:
    """简单文本规范化：去空格、去标点、转小写。"""
    import re
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w一-鿿]", "", text)
    return text.strip()


def is_near_duplicate(
    a: str,
    b: str,
    threshold: float = 0.85,
) -> bool:
    """基于字符级 Jaccard 相似度的近重复判断。

    适合第一版 MVP，后续可替换为 SimHash/MinHash。
    """
    norm_a = _simple_normalize(a)
    norm_b = _simple_normalize(b)

    if not norm_a or not norm_b:
        return False

    # 用字符 bigram 计算 Jaccard 相似度
    def bigrams(s: str) -> set[tuple[str, str]]:
        return set(zip(s[:-1], s[1:]))

    bigram_a = bigrams(norm_a)
    bigram_b = bigrams(norm_b)

    intersection = len(bigram_a & bigram_b)
    union = len(bigram_a | bigram_b)

    if union == 0:
        return False

    return intersection / union >= threshold
