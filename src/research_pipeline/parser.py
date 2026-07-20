"""文档解析模块。

统一接口：输入原始内容（bytes）和 MIME 类型 → 输出纯文本。
"""

from __future__ import annotations

import io
from typing import Optional

import pdfplumber
import trafilatura
from bs4 import BeautifulSoup


def extract_text(
    content: bytes,
    mime_type: str,
    url: str = "",
) -> tuple[str, str, Optional[str]]:
    """解析文档内容，返回 (plain_text, detected_mime, error_message)。"""
    mtype = mime_type.lower() if mime_type else ""

    if "html" in mtype:
        return _extract_html(content, url)
    elif "pdf" in mtype:
        return _extract_pdf(content)
    else:
        return _extract_fallback(content)


def _extract_html(content: bytes, url: str) -> tuple[str, str, Optional[str]]:
    """HTML 提取，trafilatura 为主，降级到 BeautifulSoup。"""
    # 策略 1: trafilatura
    text = trafilatura.extract(
        content,
        url=url,
        include_links=False,
        include_tables=True,
        output_format="txt",
        with_metadata=True,
    )
    if text and len(text) > 50:
        return text, "text/html", None

    # 策略 2: 降级到 BeautifulSoup + lxml
    try:
        soup = BeautifulSoup(content, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if text:
            return text, "text/html", "trafilatura returned short text, used bs4 fallback"
    except Exception:
        pass

    # 策略 3: 裸解码
    try:
        text = content.decode("utf-8", errors="replace")
        return text, "text/html", "all structured parsers failed, raw decode"
    except Exception as e:
        return "", "text/html", f"decode failed: {e}"


def _extract_pdf(content: bytes) -> tuple[str, str, Optional[str]]:
    """PDF 文本提取。使用 pdfplumber，失败时降级到 raw text。"""
    error: Optional[str] = None
    all_text: list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    all_text.append(f"--- Page {page_num} ---\n{page_text}")
    except Exception as e:
        error = f"pdfplumber failed: {e}"

    if all_text:
        return "\n\n".join(all_text), "application/pdf", error

    try:
        return content.decode("utf-8", errors="replace"), "application/pdf", error or "empty pdf"
    except Exception as e:
        return "", "application/pdf", f"all pdf methods failed: {e}"


def _extract_fallback(content: bytes) -> tuple[str, str, Optional[str]]:
    """后备方案：尝试按 UTF-8 解码。"""
    try:
        text = content.decode("utf-8", errors="replace")
        return text, "text/plain", None
    except Exception as e:
        return "", "unknown", str(e)
