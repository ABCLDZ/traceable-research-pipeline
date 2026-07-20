"""Deterministic identifiers used across runs and releases."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_identifier(value: str, *, field_name: str = "identifier") -> str:
    """Reject identifiers that could escape or reshape filesystem paths."""
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(
            f"{field_name} must be 1-128 ASCII letters, digits, '.', '_' or '-', "
            "and must start with a letter or digit"
        )
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_id(prefix: str, *parts: Any, length: int = 20) -> str:
    payload = canonical_json(parts).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:length]
    return f"{prefix}-{digest}"
