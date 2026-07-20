"""证据抽取引擎 V3 — 基于 span-selection 协议，支持定性和定量混合提取。"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any, Optional

from research_pipeline.chunker import build_excerpt_from_spans, build_text_with_ids, chunk_document
from research_pipeline.models import (
    DocumentChunk,
    DocumentRecord,
    EvidenceCard,
    EvidenceType,
    ExcerptVerification,
    NumericValue,
    SourceTier,
)
from research_pipeline.providers import LLMProvider, LLMRequest, LLMResponse, CallLogger
from research_pipeline.storage import Storage
from research_pipeline.ids import stable_id


class ExtractionError(RuntimeError):
    """Base exception for an extraction run that must be retried."""


class ChunkExtractionError(ExtractionError):
    """Raised when one chunk did not produce a trustworthy extraction result."""

    def __init__(self, chunk: DocumentChunk, reason: str) -> None:
        self.chunk_id = chunk.chunk_id
        self.chunk_index = chunk.chunk_index
        self.reason = reason
        super().__init__(f"chunk {chunk.chunk_index} ({chunk.chunk_id}): {reason}")


def load_prompt(prompt_path: str | Path | None = None) -> str:
    if prompt_path is None:
        return (
            files("research_pipeline.resources")
            .joinpath("extract_evidence_v3.md")
            .read_text(encoding="utf-8")
        )
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
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
    # Truncated JSON recovery: scan for balanced braces
    if text.startswith("[") and not text.endswith("]"):
        depth = 0
        last_complete = 0
        for j, ch in enumerate(text):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    last_complete = j
        if last_complete > 0:
            try:
                data = json.loads(text[:last_complete + 1] + "]")
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
    return None


def extract_from_chunk_v3(chunk: DocumentChunk, provider: LLMProvider,
                          system_prompt: str, user_prompt_template: str,
                          logger: Optional[CallLogger] = None) -> list[EvidenceCard]:
    """Extract one chunk.

    An empty list means the provider returned a valid empty JSON array. Provider
    failures, invalid JSON, and invalid card payloads raise
    :class:`ChunkExtractionError` so callers cannot mistake them for "no evidence".
    """
    if not chunk.text.strip():
        return []
    tagged_text = build_text_with_ids(chunk)
    user_prompt = user_prompt_template.replace("{{CHUNK_TEXT}}", tagged_text)
    request = LLMRequest(prompt_name="extract_evidence_v3", prompt_version="v3",
                         system_prompt=system_prompt, user_prompt=user_prompt,
                         temperature=0.1, max_tokens=4096,
                         metadata={"chunk_id": chunk.chunk_id})
    try:
        response = provider.complete(request)
    except Exception as exc:
        raise ChunkExtractionError(chunk, f"provider call failed: {exc}") from exc
    if logger:
        logger.log(request, response)
    if response.error:
        raise ChunkExtractionError(chunk, f"provider error: {response.error}")
    raw_cards = _try_parse_json(response.content)
    if raw_cards is None:
        raise ChunkExtractionError(chunk, "response is not a valid JSON array")
    cards = []
    invalid_items: list[int] = []
    for item_index, rc in enumerate(raw_cards):
        if not isinstance(rc, dict):
            invalid_items.append(item_index)
            continue
        card = _raw_to_card_v3(rc, chunk)
        if card:
            cards.append(card)
        else:
            invalid_items.append(item_index)
    if invalid_items:
        joined = ", ".join(str(index) for index in invalid_items)
        raise ChunkExtractionError(chunk, f"invalid evidence item(s) at index: {joined}")
    return cards


def _raw_to_card_v3(rc: dict[str, Any], chunk: DocumentChunk) -> Optional[EvidenceCard]:
    try:
        sentence_ids = rc.get("sentence_ids", [])
        if not isinstance(sentence_ids, list) or not sentence_ids:
            return None
        excerpt, all_found = build_excerpt_from_spans(chunk, sentence_ids)
        if not all_found or not excerpt.strip() or excerpt not in chunk.text:
            return None
        etype_str = rc.get("evidence_type", "qualitative")
        try:
            evidence_type = EvidenceType(etype_str)
        except ValueError:
            return None
        numeric_values = []
        for nv in rc.get("numeric_values", []) or []:
            if (
                isinstance(nv, dict)
                and "value" in nv
                and nv["value"] is not None
                and str(nv["value"]).strip() != ""
            ):
                numeric_values.append(NumericValue(value=str(nv["value"]), unit=nv.get("unit"),
                    currency=nv.get("currency"), time_range=nv.get("time_range"),
                    metric_name=nv.get("metric_name"), scope=nv.get("scope"), notes=nv.get("notes")))
        eid = stable_id(
            "EVC",
            "v3",
            chunk.document_id,
            chunk.chunk_index,
            rc.get("claim", ""),
            sentence_ids,
        )
        card = EvidenceCard(evidence_id=eid, document_id=chunk.document_id, chunk_id=chunk.chunk_id,
            project_id="", topic=rc.get("topic", "general"), evidence_type=evidence_type,
            claim=rc.get("claim", "").strip(), original_excerpt=excerpt, page_number=chunk.page_start,
            section=rc.get("section"), source_url="", source_tier=SourceTier.TIER_4,
            extraction_method="auto_llm_v3", confidence=rc.get("confidence"),
            numeric_values=numeric_values, tags=rc.get("tags", []),
            selected_sentence_ids=sentence_ids, status="extracted",
            verified_at=None, excerpt_verification=ExcerptVerification(
                exact_match=True,
                verification_method="auto_span_exact_source_slice",
            ))
        return card
    except Exception:
        return None


def dedup_evidence_cards(cards: list[EvidenceCard]) -> list[EvidenceCard]:
    seen: set[tuple[str, str, str, str]] = set()
    result = []
    for card in cards:
        normalized_claim = " ".join(card.claim.split()).casefold()
        key = (
            card.document_id,
            card.original_excerpt,
            normalized_claim,
            card.evidence_type.value,
        )
        if normalized_claim and key not in seen:
            seen.add(key)
            result.append(card)
    return result


def extract_evidence_v3(document: DocumentRecord, provider: LLMProvider,
                        system_prompt: str, user_prompt_template: str,
                        storage: Storage, logger: Optional[CallLogger] = None,
                        max_chunk_chars: int = 3000) -> list[EvidenceCard]:
    chunks = chunk_document(document.document_id, document.text, max_chunk_chars=max_chunk_chars)
    print(f"  chunks: {len(chunks)}")
    all_cards = []
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i+1}/{len(chunks)} ({len(chunk.text)} chars)...", end=" ")
        try:
            cards = extract_from_chunk_v3(
                chunk,
                provider,
                system_prompt,
                user_prompt_template,
                logger,
            )
        except ChunkExtractionError:
            print("FAILED")
            raise
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
    print(f"  deduped: {len(unique)} cards")
    for card in unique:
        storage.save_evidence(document.project_id, card)
    return unique
