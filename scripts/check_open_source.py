#!/usr/bin/env python3
"""Fail when public source files contain common private or project-specific residue."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    ".github",
    "configs",
    "examples",
    "experiments",
    "prompts",
    "scripts",
    "skills",
    "src",
    "tests",
)
ROOT_FILES = (
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "LICENSE",
    "NOTICE",
    "PROJECT_STATUS.md",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
)
TEXT_SUFFIXES = {
    "",
    ".html",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "data",
    "dist",
    "releases",
}


def source_files() -> list[Path]:
    paths: set[Path] = set()
    for relative in SCAN_ROOTS:
        base = ROOT / relative
        if base.exists():
            paths.update(
                path
                for path in base.rglob("*")
                if path.is_file()
                and path.suffix.lower() in TEXT_SUFFIXES
                and not any(part in SKIP_PARTS for part in path.parts)
                and not any(part.endswith(".egg-info") for part in path.parts)
            )
    paths.update(ROOT / name for name in ROOT_FILES if (ROOT / name).is_file())
    return sorted(paths)


def main() -> int:
    findings: list[dict[str, str]] = []
    company_markers = ("x" + "peng", "小" + "鹏")
    secret_patterns = (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    )
    private_path_patterns = (
        re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+"),
        re.compile(r"(?i)\b[A-Z]:\\3\\"),
    )

    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        for marker in company_markers:
            if marker.lower() in lowered:
                findings.append({"path": relative, "issue": "company-specific marker"})
                break
        for pattern in (*secret_patterns, *private_path_patterns):
            if pattern.search(text):
                findings.append(
                    {"path": relative, "issue": f"matched {pattern.pattern}"}
                )

    required = (
        ROOT / "LICENSE",
        ROOT / "NOTICE",
        ROOT / "SECURITY.md",
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "skills" / "traceable-research" / "SKILL.md",
        ROOT / "configs" / "example.yaml",
    )
    for path in required:
        if not path.is_file():
            findings.append(
                {"path": str(path.relative_to(ROOT)), "issue": "required file missing"}
            )

    payload = {
        "status": "pass" if not findings else "fail",
        "files_scanned": len(source_files()),
        "findings": findings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
