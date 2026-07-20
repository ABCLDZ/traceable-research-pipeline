from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_project_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_project_manifest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_canonical_bytes_normalizes_text_line_endings(tmp_path: Path) -> None:
    text_file = tmp_path / "sample.txt"
    text_file.write_bytes(b"first\r\nsecond\r\n")

    assert MODULE.canonical_bytes(text_file) == b"first\nsecond\n"


def test_canonical_bytes_preserves_binary_content(tmp_path: Path) -> None:
    binary_file = tmp_path / "sample.png"
    payload = b"\x89PNG\r\n\x00\r\n"
    binary_file.write_bytes(payload)

    assert MODULE.canonical_bytes(binary_file) == payload
