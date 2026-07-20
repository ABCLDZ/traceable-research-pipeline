"""Agent Skill packaging and cross-platform installer tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "traceable-research"
INSTALLER = ROOT / "scripts" / "install_agent_skill.py"
ENV_CHECK = SKILL / "scripts" / "check_environment.py"
OPEN_SOURCE_CHECK = ROOT / "scripts" / "check_open_source.py"


def _load_environment_check():
    spec = importlib.util.spec_from_file_location("skill_environment_check", ENV_CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_frontmatter_is_cross_platform_core():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert metadata["name"] == "traceable-research"
    assert "when" not in metadata
    assert set(metadata) == {"name", "description"}
    assert "human gate 2" in body.lower()
    assert "human gate 3" in body.lower()


def test_openai_metadata_mentions_skill():
    metadata = yaml.safe_load(
        (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert "$traceable-research" in metadata["interface"]["default_prompt"]
    assert metadata["policy"]["allow_implicit_invocation"] is True


def test_environment_check_returns_redacted_json():
    sentinel_secret = "sentinel-secret-must-not-appear"
    environment = os.environ.copy()
    environment["DEEPSEEK_API_KEY"] = sentinel_secret
    completed = subprocess.run(
        [sys.executable, str(ENV_CHECK)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    payload = json.loads(completed.stdout)
    assert payload["python"]["supported"]
    assert payload["research_flow"]["ready"]
    assert payload["research_flow"]["command_prefix"] == [
        sys.executable,
        "-m",
        "research_pipeline.cli",
    ]
    assert payload["provider"]["deepseek_api_key_configured"] is True
    assert sentinel_secret not in completed.stdout


def test_environment_ready_requires_supported_python():
    module = _load_environment_check()
    assert module._ready(True, ["python", "-m", "research_pipeline.cli"])
    assert not module._ready(False, ["python", "-m", "research_pipeline.cli"])
    assert not module._ready(True, None)


def test_installer_supports_both_project_skill_locations(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--agent",
            "all",
            "--scope",
            "project",
            "--project-root",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert {item["platform"] for item in payload["installations"]} == {
        "codex",
        "claude",
    }
    codex_skill = tmp_path / ".agents" / "skills" / "traceable-research"
    claude_skill = tmp_path / ".claude" / "skills" / "traceable-research"
    assert (codex_skill / "SKILL.md").is_file()
    assert (claude_skill / "SKILL.md").is_file()
    assert (codex_skill / "SKILL.md").read_bytes() == (
        claude_skill / "SKILL.md"
    ).read_bytes()


def test_installer_is_idempotent(tmp_path):
    command = [
        sys.executable,
        str(INSTALLER),
        "--agent",
        "codex",
        "--project-root",
        str(tmp_path),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    second = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(second.stdout)
    assert payload["installations"][0]["status"] == "current"


def test_installer_supports_user_scope(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--agent",
            "codex",
            "--scope",
            "user",
            "--home",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    installed = tmp_path / ".agents" / "skills" / "traceable-research"
    assert payload["installations"][0]["path"] == str(installed)
    assert (installed / "SKILL.md").is_file()


def test_installer_replace_preserves_backup(tmp_path):
    command = [
        sys.executable,
        str(INSTALLER),
        "--agent",
        "claude",
        "--project-root",
        str(tmp_path),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    installed = tmp_path / ".claude" / "skills" / "traceable-research"
    (installed / "SKILL.md").write_text("different", encoding="utf-8")

    replaced = subprocess.run(
        [*command, "--replace"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(replaced.stdout)
    backup = Path(payload["installations"][0]["backup"])
    assert backup.is_dir()
    assert backup.parent == tmp_path / ".agent-skill-backups" / "claude"
    assert tmp_path / ".claude" / "skills" not in backup.parents
    assert (backup / "SKILL.md").read_text(encoding="utf-8") == "different"
    assert (installed / "SKILL.md").read_bytes() == (SKILL / "SKILL.md").read_bytes()


def test_v3_prompt_has_one_canonical_source():
    canonical = (
        ROOT
        / "src"
        / "research_pipeline"
        / "resources"
        / "extract_evidence_v3.md"
    )
    assert canonical.is_file()
    assert "[S0001]" in canonical.read_text(encoding="utf-8")
    assert not (ROOT / "prompts" / "extract_evidence_v3.md").exists()


def test_open_source_release_audit_passes():
    completed = subprocess.run(
        [sys.executable, str(OPEN_SOURCE_CHECK)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["status"] == "pass"
    assert payload["findings"] == []
    assert payload["files_scanned"] > 0
