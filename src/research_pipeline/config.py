"""YAML 配置加载模块。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from research_pipeline.models import ProjectConfig


def load_config(path: str | Path) -> ProjectConfig:
    """加载 YAML 配置文件，返回 ProjectConfig。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ProjectConfig.model_validate(raw)


def dump_config(config: ProjectConfig, path: str | Path) -> None:
    """将配置写入 YAML 文件。"""
    path = Path(path)
    raw = config.model_dump(mode="json", exclude_none=True)
    path.write_text(yaml.dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
