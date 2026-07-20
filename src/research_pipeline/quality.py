"""Conservative parser-quality signals.

These heuristics flag risk; they do not certify that a document was parsed
completely or that tables retained their original structure.
"""

from __future__ import annotations

from research_pipeline.models import MimeType, ParseQuality, TablePreservation


def assess_parse_quality(
    *,
    mime_type: MimeType,
    text: str,
    parse_error: str | None,
) -> tuple[ParseQuality, TablePreservation, bool, list[str]]:
    signals: list[str] = []
    stripped = text.strip()

    if parse_error:
        signals.append(f"parser_error:{parse_error[:160]}")
    if not stripped:
        return ParseQuality.FAILED, TablePreservation.UNKNOWN, True, signals + ["empty_text"]

    replacement_ratio = stripped.count("\ufffd") / max(len(stripped), 1)
    if replacement_ratio > 0.005:
        signals.append(f"replacement_character_ratio:{replacement_ratio:.4f}")

    if mime_type == MimeType.PDF:
        table_state = TablePreservation.UNKNOWN
        signals.append("pdf_table_structure_not_guaranteed")
        if len(stripped) < 500:
            signals.append("low_pdf_text_volume")
    else:
        table_state = TablePreservation.NOT_APPLICABLE

    degraded = bool(parse_error) or replacement_ratio > 0.005
    degraded = degraded or (mime_type == MimeType.PDF and len(stripped) < 500)
    quality = ParseQuality.DEGRADED if degraded else ParseQuality.USABLE
    return quality, table_state, degraded, signals
