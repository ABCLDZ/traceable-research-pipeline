"""Run Manifest — 运行清单管理。

记录每次采集/抽取运行的完整信息，确保实验可复现。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from research_pipeline.models import RunManifest


def create_manifest(
    project_id: str,
    run_type: str,
    *,
    run_id: Optional[str] = None,
    config_hash: Optional[str] = None,
    source_urls: Optional[list[str]] = None,
    parser_versions: Optional[dict[str, str]] = None,
) -> RunManifest:
    """创建新的运行清单。"""
    if run_id is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = f"{project_id}_{run_type}_{ts}"

    manifest = RunManifest(
        run_id=run_id,
        project_id=project_id,
        run_type=run_type,
        config_hash=config_hash,
        source_urls=source_urls or [],
        parser_versions=parser_versions or {},
    )
    return manifest


def save_manifest(manifest: RunManifest, output_dir: str | Path) -> Path:
    """保存运行清单到 JSON。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{manifest.run_id}.json"
    data = manifest.model_dump(mode="json", exclude_none=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_manifest(path: str | Path) -> RunManifest:
    """从 JSON 加载运行清单。"""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunManifest.model_validate(data)


def complete_manifest(
    manifest: RunManifest,
    *,
    status: str = "completed",
    errors: Optional[list[str]] = None,
    warnings: Optional[list[str]] = None,
) -> RunManifest:
    """标记运行为完成状态。"""
    manifest.status = status
    manifest.finished_at = datetime.now(timezone.utc)
    if errors:
        manifest.errors.extend(errors)
    if warnings:
        manifest.warnings.extend(warnings)
    return manifest


def hash_config(config_path: str | Path) -> Optional[str]:
    """计算配置文件的 SHA-256 哈希。"""
    config_path = Path(config_path)
    if not config_path.exists():
        return None
    content = config_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def find_latest_manifest(
    project_dir: str | Path,
    run_type: Optional[str] = None,
) -> Optional[RunManifest]:
    """查找项目目录下最新的运行清单。"""
    project_dir = Path(project_dir)
    if not project_dir.exists():
        return None

    manifests_dir = project_dir / "manifests"
    if not manifests_dir.exists():
        return None

    candidates = sorted(manifests_dir.glob("*.json"), reverse=True)
    for path in candidates:
        manifest = load_manifest(path)
        if run_type is None or manifest.run_type == run_type:
            return manifest
    return None
