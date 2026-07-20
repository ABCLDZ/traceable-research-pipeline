#!/usr/bin/env python3
"""Install the canonical Agent Skill for Codex, Claude Code, or both."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


SKILL_NAME = "traceable-research"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = REPOSITORY_ROOT / "skills" / SKILL_NAME
PLATFORM_DIRS = {
    "codex": Path(".agents") / "skills",
    "claude": Path(".claude") / "skills",
}


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    files = (
        item
        for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix != ".pyc"
    )
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _platforms(value: str) -> list[str]:
    return list(PLATFORM_DIRS) if value == "all" else [value]


def _destinations(
    *,
    agent: str,
    scope: str,
    project_root: Path,
    home: Path,
) -> dict[str, Path]:
    base = project_root.resolve() if scope == "project" else home.resolve()
    return {
        platform: base / PLATFORM_DIRS[platform] / SKILL_NAME
        for platform in _platforms(agent)
    }


def _backup_path(
    *,
    platform: str,
    scope: str,
    project_root: Path,
    home: Path,
) -> Path:
    base = project_root.resolve() if scope == "project" else home.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        base
        / ".agent-skill-backups"
        / platform
        / f"{SKILL_NAME}-{stamp}-{uuid.uuid4().hex[:8]}"
    )


def install(
    *,
    agent: str,
    scope: str,
    project_root: Path,
    home: Path,
    replace: bool,
    dry_run: bool,
) -> dict[str, object]:
    if not (SOURCE_SKILL / "SKILL.md").is_file():
        raise FileNotFoundError(f"canonical skill is missing: {SOURCE_SKILL}")

    destinations = _destinations(
        agent=agent,
        scope=scope,
        project_root=project_root,
        home=home,
    )
    source_digest = _tree_digest(SOURCE_SKILL)
    conflicts = {
        platform: destination
        for platform, destination in destinations.items()
        if destination.exists() and _tree_digest(destination) != source_digest
    }
    if conflicts and not replace:
        rendered = ", ".join(f"{key}={value}" for key, value in conflicts.items())
        raise FileExistsError(
            f"different skill installation already exists ({rendered}); "
            "rerun with --replace to preserve it as a timestamped backup"
        )

    result: dict[str, object] = {
        "source": str(SOURCE_SKILL),
        "source_sha256": source_digest,
        "scope": scope,
        "dry_run": dry_run,
        "installations": [],
    }
    installations: list[dict[str, object]] = []
    result["installations"] = installations

    for platform, destination in destinations.items():
        if destination.exists() and _tree_digest(destination) == source_digest:
            installations.append(
                {"platform": platform, "path": str(destination), "status": "current"}
            )
            continue
        if dry_run:
            installations.append(
                {"platform": platform, "path": str(destination), "status": "planned"}
            )
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        stage_root = destination.parent / (
            f".{SKILL_NAME}.installing-{uuid.uuid4().hex}"
        )
        staged = stage_root / SKILL_NAME
        stage_root.mkdir()
        shutil.copytree(
            SOURCE_SKILL,
            staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        backup: Path | None = None
        try:
            if destination.exists():
                backup = _backup_path(
                    platform=platform,
                    scope=scope,
                    project_root=project_root,
                    home=home,
                )
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
            os.replace(staged, destination)
        except Exception:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

        installations.append(
            {
                "platform": platform,
                "path": str(destination),
                "status": "installed",
                "backup": str(backup) if backup else None,
            }
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the canonical traceable-research Agent Skill."
    )
    parser.add_argument(
        "--agent",
        choices=["codex", "claude", "all"],
        default="all",
        help="Target agent platform.",
    )
    parser.add_argument(
        "--scope",
        choices=["project", "user"],
        default="project",
        help="Install into the current project or the user's home directory.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root used for project-scoped installation.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace a different installation after preserving a timestamped backup.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = install(
        agent=args.agent,
        scope=args.scope,
        project_root=args.project_root,
        home=args.home,
        replace=args.replace,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
