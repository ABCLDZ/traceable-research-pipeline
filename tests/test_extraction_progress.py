"""Extraction CLI failure and progress-fingerprint regression tests."""

from __future__ import annotations

import hashlib
import json

from typer.testing import CliRunner

from research_pipeline.cli import app
from research_pipeline.models import (
    DocumentRecord,
    MimeType,
    ParseQuality,
    SourceTier,
    SourceType,
)
from research_pipeline.providers import LLMProvider, LLMRequest, LLMResponse
from research_pipeline.storage import Storage


CONFIG_TEXT = """\
project_id: progress_test
entity:
  name: Progress Test
  aliases: []
research_question: Does extraction retry failed documents?
time_range: {}
source_policy:
  allowed_domains: [example.com]
  blocked_domains: []
  source_types: [other]
  priority: [primary_sources]
seed_urls: []
analysis_modules: [retry]
"""


class StubDeepSeekProvider(LLMProvider):
    response = LLMResponse(content="[]", model="stub-model")
    calls = 0

    def __init__(self, model: str = "stub-model") -> None:
        self._model = model
        self.input_cost_per_m = 0.0
        self.output_cost_per_m = 0.0

    @property
    def provider_name(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return self._model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0

    def complete(self, request: LLMRequest) -> LLMResponse:
        type(self).calls += 1
        return type(self).response.model_copy()


def _write_config_and_document(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_TEXT, encoding="utf-8")
    text = "A valid source sentence."
    document = DocumentRecord(
        document_id="DOC-001",
        project_id="progress_test",
        entity_name="Progress Test",
        title="Progress source",
        source_url="https://example.com/source",
        source_type=SourceType.OTHER,
        source_tier=SourceTier.TIER_1,
        mime_type=MimeType.PLAIN_TEXT,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        parse_quality=ParseQuality.USABLE,
    )
    Storage(tmp_path / "data").save_document(document)
    return config_path, document


def _invoke_extract(tmp_path, config_path, *extra_args: str):
    return CliRunner().invoke(
        app,
        [
            "extract",
            str(config_path),
            "--data-dir",
            str(tmp_path / "data"),
            *extra_args,
        ],
    )


def test_failed_document_is_not_completed_and_is_retried(tmp_path, monkeypatch):
    config_path, _ = _write_config_and_document(tmp_path)
    monkeypatch.setattr("research_pipeline.cli.DeepSeekProvider", StubDeepSeekProvider)
    StubDeepSeekProvider.calls = 0
    StubDeepSeekProvider.response = LLMResponse(
        content="",
        model="stub-model",
        error="temporary provider failure",
    )

    failed = _invoke_extract(tmp_path, config_path)
    assert failed.exit_code == 1
    assert StubDeepSeekProvider.calls == 1
    progress_path = (
        tmp_path / "data" / "projects" / "progress_test" / "extract_progress.json"
    )
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert "DOC-001" not in progress["completed_documents"]
    assert "DOC-001" in progress["failed_documents"]

    StubDeepSeekProvider.response = LLMResponse(content="[]", model="stub-model")
    retried = _invoke_extract(tmp_path, config_path)
    assert retried.exit_code == 0, retried.output
    assert StubDeepSeekProvider.calls == 2
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert "DOC-001" in progress["completed_documents"]
    assert progress["failed_documents"] == {}


def test_progress_invalidates_on_document_model_and_prompt_changes(tmp_path, monkeypatch):
    config_path, document = _write_config_and_document(tmp_path)
    monkeypatch.setattr("research_pipeline.cli.DeepSeekProvider", StubDeepSeekProvider)
    StubDeepSeekProvider.calls = 0
    StubDeepSeekProvider.response = LLMResponse(content="[]", model="stub-model")

    assert _invoke_extract(tmp_path, config_path).exit_code == 0
    assert StubDeepSeekProvider.calls == 1
    assert _invoke_extract(tmp_path, config_path).exit_code == 0
    assert StubDeepSeekProvider.calls == 1

    assert _invoke_extract(tmp_path, config_path, "--model", "different-model").exit_code == 0
    assert StubDeepSeekProvider.calls == 2

    custom_prompt = tmp_path / "prompt.md"
    custom_prompt.write_text("custom extraction rules", encoding="utf-8")
    assert _invoke_extract(
        tmp_path,
        config_path,
        "--model",
        "different-model",
        "--prompt-path",
        str(custom_prompt),
    ).exit_code == 0
    assert StubDeepSeekProvider.calls == 3

    document.text = "A changed source sentence."
    Storage(tmp_path / "data").save_document(document)
    assert _invoke_extract(
        tmp_path,
        config_path,
        "--model",
        "different-model",
        "--prompt-path",
        str(custom_prompt),
    ).exit_code == 0
    assert StubDeepSeekProvider.calls == 4


def test_parse_failed_document_is_reported_as_failed_not_completed(
    tmp_path,
    monkeypatch,
):
    config_path, document = _write_config_and_document(tmp_path)
    document.parse_quality = ParseQuality.FAILED
    Storage(tmp_path / "data").save_document(document)
    monkeypatch.setattr("research_pipeline.cli.DeepSeekProvider", StubDeepSeekProvider)
    StubDeepSeekProvider.calls = 0

    result = _invoke_extract(tmp_path, config_path)

    assert result.exit_code == 1
    assert StubDeepSeekProvider.calls == 0
    progress_path = (
        tmp_path / "data" / "projects" / "progress_test" / "extract_progress.json"
    )
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert "DOC-001" not in progress["completed_documents"]
    assert "DOC-001" in progress["failed_documents"]
