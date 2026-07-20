#!/usr/bin/env python3
"""Report whether the traceable research CLI can run without exposing secrets."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys


def _ready(python_ok: bool, command_prefix: list[str] | None) -> bool:
    return python_ok and command_prefix is not None


def main() -> int:
    python_ok = sys.version_info >= (3, 11)
    module_available = importlib.util.find_spec("research_pipeline") is not None
    cli_path = shutil.which("research-flow")
    if module_available:
        command_prefix = [sys.executable, "-m", "research_pipeline.cli"]
    elif cli_path:
        command_prefix = [cli_path]
    else:
        command_prefix = None
    api_key_configured = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    warnings: list[str] = []
    if not python_ok:
        warnings.append("Python 3.11 or newer is required.")
    if not module_available and not cli_path:
        warnings.append(
            "Install the Python package from "
            "https://github.com/ABCLDZ/traceable-research-pipeline."
        )
    if not api_key_configured:
        warnings.append(
            "DEEPSEEK_API_KEY is not configured; live extraction will be unavailable."
        )

    payload = {
        "python": {
            "executable": sys.executable,
            "version": ".".join(map(str, sys.version_info[:3])),
            "supported": python_ok,
        },
        "research_flow": {
            "command_path": cli_path,
            "module_available": module_available,
            "ready": _ready(python_ok, command_prefix),
            "command_prefix": command_prefix,
        },
        "provider": {
            "deepseek_api_key_configured": api_key_configured,
            "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        },
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if _ready(python_ok, command_prefix) else 1


if __name__ == "__main__":
    raise SystemExit(main())
