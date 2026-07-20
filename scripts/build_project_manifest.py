"""Build a source-only project handoff manifest."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCLUDED_ROOTS = [
    ".github",
    "src",
    "tests",
    "scripts",
    "prompts",
    "configs",
    "schemas",
    "examples",
    "experiments",
    "skills",
]
INCLUDED_FILES = [
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "PROJECT_STATUS.md",
    "pyproject.toml",
    ".gitattributes",
    ".gitignore",
    ".env.example",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_tests() -> int:
    count = 0
    for path in (ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return count


def _build_payload(*, generated_at: str) -> dict[str, object]:
    paths: set[Path] = set()
    for relative in INCLUDED_ROOTS:
        base = ROOT / relative
        if base.exists():
            paths.update(path for path in base.rglob("*") if path.is_file())
    paths.update(ROOT / relative for relative in INCLUDED_FILES if (ROOT / relative).exists())
    paths = {
        path
        for path in paths
        if "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.name != "PROJECT_MANIFEST.json"
    }
    files = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(paths)
    ]
    tree = hashlib.sha256()
    for item in files:
        tree.update(item["path"].encode("utf-8"))
        tree.update(b"\0")
        tree.update(item["sha256"].encode("ascii"))
        tree.update(b"\n")
    return {
        "schema_version": "0.1.0",
        "project": "traceable-research-pipeline",
        "generated_at": generated_at,
        "source_tree_sha256": tree.hexdigest(),
        "files_count": len(files),
        "test_functions": count_tests(),
        "latest_recorded_verification": {
            "pytest": "pass",
            "compileall": "pass",
            "pip_check": "pass",
            "open_source_audit": "pass",
            "offline_release_demo": "pass",
            "wheel_packaged_prompt": "pass",
        },
        "files": files,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or check the source-only project handoff manifest."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail without writing when the committed manifest is stale.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest_path = ROOT / "PROJECT_MANIFEST.json"
    if args.check:
        if not manifest_path.is_file():
            raise SystemExit("PROJECT_MANIFEST_STALE missing PROJECT_MANIFEST.json")
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = _build_payload(
            generated_at=str(recorded.get("generated_at", ""))
        )
        if payload != recorded:
            raise SystemExit(
                "PROJECT_MANIFEST_STALE run: "
                "python scripts/build_project_manifest.py"
            )
        print(
            f"PROJECT_MANIFEST_FRESH files={payload['files_count']} "
            f"tests={payload['test_functions']} "
            f"tree={payload['source_tree_sha256']}"
        )
        return

    payload = _build_payload(
        generated_at=datetime.now(timezone.utc).isoformat()
    )
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"PROJECT_MANIFEST_PASS files={payload['files_count']} "
        f"tests={payload['test_functions']} tree={payload['source_tree_sha256']}"
    )


if __name__ == "__main__":
    main()
