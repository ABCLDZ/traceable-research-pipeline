"""文本分块模块。

将 DocumentRecord.text 按页/自然段/固定大小拆分为 DocumentChunk，
确保每个证据卡都能精确回溯到原文位置。

支持 span-selection 协议：每个 chunk 中的句子带 [S001] 编号，
模型返回句子 ID，代码拼装原文摘录。
"""

from __future__ import annotations

import hashlib
import re

from research_pipeline.models import DocumentChunk


DEFAULT_MAX_CHUNK_CHARS = 3000


def chunk_document(
    document_id: str,
    text: str,
    *,
    parser_name: str = "pdfplumber",
    parser_version: str = "1.0",
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> list[DocumentChunk]:
    if max_chunk_chars <= 0:
        raise ValueError("max_chunk_chars must be greater than zero")

    chunks: list[DocumentChunk] = []

    if "--- Page " in text:
        page_chunks = _split_by_pages(document_id, text, parser_name, parser_version)
        for c in page_chunks:
            chunks.extend(_split_oversized_chunk(c, max_chunk_chars))
        if chunks:
            _reindex_chunks(chunks)
            _link_chunks(chunks)
            _annotate_sentences(chunks)
            return chunks

    for para_start, para_end in _nonempty_paragraph_spans(text):
        para = text[para_start:para_end]
        if not para:
            continue
        c = DocumentChunk(
            chunk_id=f"{document_id}_c{len(chunks):04d}",
            document_id=document_id,
            chunk_index=len(chunks),
            text=para,
            text_hash=_hash_text(para),
            char_start=para_start,
            char_end=para_end,
            parser_name=parser_name,
            parser_version=parser_version,
        )
        chunks.extend(_split_oversized_chunk(c, max_chunk_chars))

    if not chunks:
        return chunks

    _reindex_chunks(chunks)
    _link_chunks(chunks)
    _annotate_sentences(chunks)
    return chunks


def _split_by_pages(
    document_id: str, text: str, parser_name: str, parser_version: str,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    marker_pattern = re.compile(r"(?m)^--- Page (\d+) ---[ \t]*(?:\r?\n)?")
    markers = list(marker_pattern.finditer(text))

    def append_page(start: int, end: int, page_number: int) -> None:
        trimmed_start, trimmed_end = _trim_span(text, start, end)
        if trimmed_start >= trimmed_end:
            return
        page_text = text[trimmed_start:trimmed_end]
        chunks.append(DocumentChunk(
            chunk_id=f"{document_id}_p{len(chunks):04d}",
            document_id=document_id, chunk_index=len(chunks),
            text=page_text, text_hash=_hash_text(page_text),
            page_start=page_number,
            page_end=page_number,
            char_start=trimmed_start,
            char_end=trimmed_end,
            parser_name=parser_name, parser_version=parser_version,
        ))

    if markers and markers[0].start() > 0:
        append_page(0, markers[0].start(), 0)
    for index, marker in enumerate(markers):
        content_end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        append_page(marker.end(), content_end, int(marker.group(1)))
    return chunks


def _split_oversized_chunk(chunk: DocumentChunk, max_chars: int) -> list[DocumentChunk]:
    if len(chunk.text) <= max_chars:
        return [chunk]

    result: list[DocumentChunk] = []
    base_offset = chunk.char_start or 0
    start = 0
    while start < len(chunk.text):
        hard_end = min(start + max_chars, len(chunk.text))
        end = hard_end
        if hard_end < len(chunk.text):
            newline = chunk.text.rfind("\n", start, hard_end + 1)
            if newline >= start:
                end = newline + 1
        if end <= start:
            end = hard_end
        block_text = chunk.text[start:end]
        result.append(DocumentChunk(
            chunk_id=f"{chunk.document_id}_c{chunk.chunk_index:04d}s{len(result):02d}",
            document_id=chunk.document_id, chunk_index=chunk.chunk_index,
            text=block_text, text_hash=_hash_text(block_text),
            page_start=chunk.page_start, page_end=chunk.page_end,
            section_title=chunk.section_title,
            char_start=base_offset + start,
            char_end=base_offset + end,
            parser_name=chunk.parser_name, parser_version=chunk.parser_version,
        ))
        start = end
    return result


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _nonempty_paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for separator in re.finditer(r"\r?\n\r?\n+", text):
        para_start, para_end = _trim_span(text, start, separator.start())
        if para_start < para_end:
            spans.append((para_start, para_end))
        start = separator.end()
    para_start, para_end = _trim_span(text, start, len(text))
    if para_start < para_end:
        spans.append((para_start, para_end))
    return spans


def _reindex_chunks(chunks: list[DocumentChunk]) -> None:
    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index


def _link_chunks(chunks: list[DocumentChunk]) -> None:
    for i in range(len(chunks)):
        if i > 0:
            chunks[i].previous_chunk_id = chunks[i - 1].chunk_id
        if i < len(chunks) - 1:
            chunks[i].next_chunk_id = chunks[i + 1].chunk_id


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── span-selection 协议 ──

def _annotate_sentences(chunks: list[DocumentChunk]) -> None:
    for chunk in chunks:
        if not chunk.text.strip():
            continue
        sentences = _split_sentences(chunk.text)
        chunk.sentences = {}
        for idx, sent in enumerate(sentences, 1):
            chunk.sentences[f"S{idx:04d}"] = sent


def _split_sentences(text: str) -> list[str]:
    if "\n" in text:
        return [line for line in text.split("\n") if line.strip()]
    parts = re.split(r"(?<=[.?!])\s+", text)
    return [p for p in parts if p.strip()]


def build_excerpt_from_spans(
    chunk: DocumentChunk, sentence_ids: list[str],
) -> tuple[str, bool]:
    if not chunk.sentences or not sentence_ids:
        return "", False

    ordered_ids = list(chunk.sentences)
    positions = {sentence_id: index for index, sentence_id in enumerate(ordered_ids)}
    if (
        any(not isinstance(sentence_id, str) for sentence_id in sentence_ids)
        or len(set(sentence_ids)) != len(sentence_ids)
        or any(sentence_id not in positions for sentence_id in sentence_ids)
    ):
        return "", False

    selected_positions = [positions[sentence_id] for sentence_id in sentence_ids]
    expected_positions = list(
        range(selected_positions[0], selected_positions[0] + len(selected_positions))
    )
    if selected_positions != expected_positions:
        return "", False

    selected_sentences = [chunk.sentences[sentence_id] for sentence_id in sentence_ids]
    cursor = 0
    start: int | None = None
    end: int | None = None
    for sentence in selected_sentences:
        position = chunk.text.find(sentence, cursor)
        if position < 0:
            return "", False
        if start is None:
            start = position
        end = position + len(sentence)
        cursor = end

    if start is None or end is None:
        return "", False
    excerpt = chunk.text[start:end]
    return excerpt, excerpt in chunk.text


def build_text_with_ids(chunk: DocumentChunk) -> str:
    if not chunk.sentences:
        return chunk.text
    lines = []
    for sid in sorted(chunk.sentences.keys()):
        lines.append(f"[{sid}] {chunk.sentences[sid]}")
    return "\n".join(lines)
