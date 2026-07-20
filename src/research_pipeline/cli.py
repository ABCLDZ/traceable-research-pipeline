"""Command-line entry point for the traceable research evidence pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import typer

from research_pipeline.admission import admit_review_pack, build_review_pack
from research_pipeline.config import load_config
from research_pipeline.context import compile_context
from research_pipeline.extractor import ExtractionError, extract_evidence_v3, load_prompt
from research_pipeline.ingest import ingest_project
from research_pipeline.ids import validate_identifier
from research_pipeline.io_utils import write_json_atomic
from research_pipeline.models import ParseQuality, ResearchBrief
from research_pipeline.providers import CachedProvider, CallLogger, DeepSeekProvider, LLMCache
from research_pipeline.release import freeze_release, verify_release
from research_pipeline.storage import Storage

app = typer.Typer(
    name="research-flow",
    help="可追溯研究证据管线",
    no_args_is_help=True,
)


def _project_root(data_dir: Path, project_id: str) -> Path:
    safe_project_id = validate_identifier(project_id, field_name="project_id")
    return data_dir.resolve() / "projects" / safe_project_id


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extraction_signature(
    *,
    provider_name: str,
    model_name: str,
    system_prompt: str,
    user_prompt_template: str,
) -> dict[str, str]:
    return {
        "provider": provider_name,
        "model": model_name,
        "system_prompt_sha256": _sha256_text(system_prompt),
        "user_prompt_template_sha256": _sha256_text(user_prompt_template),
    }


def _document_extraction_fingerprint(
    *,
    document_id: str,
    document_text: str,
    source_content_hash: str,
    signature: dict[str, str],
) -> dict[str, str]:
    return {
        "document_id": document_id,
        "document_text_sha256": _sha256_text(document_text),
        "source_content_hash": source_content_hash,
        **signature,
    }


@app.command("init")
def init_project(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    data_dir: Path = typer.Option(Path("./data"), help="数据存储目录"),
) -> None:
    """Validate configuration and create a minimal project workspace."""
    config = load_config(config_path)
    base = _project_root(data_dir, config.project_id)
    for sub in [
        "raw",
        "parsed",
        "documents",
        "evidence",
        "review",
        "admitted",
        "context",
        "releases",
    ]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    brief_path = base / "research_brief.json"
    if not brief_path.exists():
        brief = ResearchBrief(
            project_id=config.project_id,
            research_question=config.research_question,
            scope=config.analysis_modules,
            output_requirements=[
                "Separate facts, forecasts, targets, and management statements.",
                "State material limitations and prohibited extrapolations.",
            ],
        )
        write_json_atomic(brief_path, brief.model_dump(mode="json", exclude_none=True))
    typer.echo(f"initialized: {base}")
    typer.echo(f"research brief: {brief_path}")


@app.command()
def ingest(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    data_dir: Path = typer.Option(Path("./data"), help="数据存储目录"),
) -> None:
    """Fetch, parse, quality-flag, deduplicate, and persist source documents."""
    documents, stats = ingest_project(config_path, data_dir)
    typer.echo(
        json.dumps(
            {
                "documents": len(documents),
                "fetched": stats.fetched,
                "failed": stats.failed,
                "parse_failed": stats.parse_failed,
                "duplicates_removed": stats.duplicates_removed,
                "duration_ms": stats.total_duration_ms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("extract")
def extract_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    data_dir: Path = typer.Option(Path("./data"), help="数据存储目录"),
    prompt_path: Path | None = typer.Option(
        None,
        exists=True,
        readable=True,
        help="Optional extraction prompt override; defaults to the packaged V3 prompt.",
    ),
    model: str | None = typer.Option(
        None,
        help="DeepSeek model override; defaults to DEEPSEEK_MODEL or deepseek-chat.",
    ),
    include_log_content: bool = typer.Option(
        False,
        help="显式保存完整提示词与输出；默认只记录哈希和用量",
    ),
) -> None:
    """Run V3 span-selection extraction over persisted documents."""
    config = load_config(config_path)
    storage = Storage(data_dir)
    documents = storage.list_documents(config.project_id)
    if not documents:
        raise typer.BadParameter("no persisted documents; run ingest first")

    system_prompt = load_prompt(prompt_path)
    user_template = (
        "Select evidence from the sentence-ID text below. "
        "Return only the JSON array defined by the system instructions.\n\n"
        "{{CHUNK_TEXT}}"
    )
    cache = LLMCache(data_dir / "llm_cache")
    deepseek = DeepSeekProvider(**({"model": model} if model else {}))
    provider = CachedProvider(deepseek, cache)
    logger = CallLogger(
        data_dir / "logs" / config.project_id,
        include_content=include_log_content,
        input_cost_per_m=deepseek.input_cost_per_m,
        output_cost_per_m=deepseek.output_cost_per_m,
    )
    signature = _extraction_signature(
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        system_prompt=system_prompt,
        user_prompt_template=user_template,
    )
    project_root = _project_root(data_dir, config.project_id)
    progress_path = project_root / "extract_progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    else:
        progress = {}
    completed_documents = progress.get("completed_documents")
    if not isinstance(completed_documents, dict):
        completed_documents = {}
    progress = {
        "schema_version": "0.2.0",
        "extraction_signature": signature,
        "completed_documents": completed_documents,
        "failed_documents": {},
    }

    total_cards = 0
    failures: list[dict[str, str]] = []
    for document in documents:
        fingerprint = _document_extraction_fingerprint(
            document_id=document.document_id,
            document_text=document.text,
            source_content_hash=document.content_hash,
            signature=signature,
        )
        if completed_documents.get(document.document_id) == fingerprint:
            typer.echo(f"skip completed: {document.document_id}")
            continue
        if document.parse_quality == ParseQuality.FAILED:
            error = "source parse quality is failed; repair or replace the document"
            typer.echo(f"extraction blocked: {document.document_id}: {error}", err=True)
            completed_documents.pop(document.document_id, None)
            progress["failed_documents"][document.document_id] = {
                "error": error,
                **fingerprint,
            }
            failures.append({"document_id": document.document_id, "error": error})
            write_json_atomic(progress_path, progress)
            continue
        typer.echo(f"extracting: {document.document_id}")
        try:
            cards = extract_evidence_v3(
                document,
                provider,
                system_prompt,
                user_template,
                storage,
                logger,
            )
        except ExtractionError as exc:
            error = str(exc)
            typer.echo(f"extraction failed: {document.document_id}: {error}", err=True)
            completed_documents.pop(document.document_id, None)
            progress["failed_documents"][document.document_id] = {
                "error": error,
                **fingerprint,
            }
            failures.append({"document_id": document.document_id, "error": error})
            write_json_atomic(progress_path, progress)
            continue
        total_cards += len(cards)
        completed_documents[document.document_id] = fingerprint
        progress["failed_documents"].pop(document.document_id, None)
        progress["prompt_path"] = (
            str(prompt_path)
            if prompt_path is not None
            else "package:research_pipeline.resources/extract_evidence_v3.md"
        )
        write_json_atomic(progress_path, progress)

    typer.echo(
        json.dumps(
            {
                "new_cards": total_cards,
                "total_cards": len(storage.list_evidence(config.project_id)),
                "failed_documents": failures,
                "llm": logger.summary(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failures:
        raise typer.Exit(1)


@app.command("build-review-pack")
def build_review_pack_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    data_dir: Path = typer.Option(Path("./data")),
    output_path: Path | None = typer.Option(None),
) -> None:
    """Build one editable batch-review file from all candidate evidence."""
    config = load_config(config_path)
    storage = Storage(data_dir)
    cards = storage.list_evidence(config.project_id)
    if not cards:
        raise typer.BadParameter("no EvidenceCards; run extract first")
    target = output_path or (
        _project_root(data_dir, config.project_id) / "review" / "review_pack.json"
    )
    build_review_pack(
        cards,
        project_id=config.project_id,
        research_question=config.research_question,
        output_path=target,
        documents=storage.list_documents(config.project_id),
    )
    typer.echo(f"review pack: {target}")
    typer.echo("edit every decision before running admit-evidence")


@app.command("admit-evidence")
def admit_evidence_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    reviewer: str = typer.Option(..., help="批量审核者"),
    data_dir: Path = typer.Option(Path("./data")),
    review_pack_path: Path | None = typer.Option(None),
    output_path: Path | None = typer.Option(None),
) -> None:
    """Apply a fully reviewed batch atomically and create EvidenceRecords."""
    config = load_config(config_path)
    storage = Storage(data_dir)
    base = _project_root(data_dir, config.project_id)
    review_pack = review_pack_path or base / "review" / "review_pack.json"
    target = output_path or base / "admitted" / "evidence_records.json"
    admit_review_pack(
        review_pack_path=review_pack,
        cards=storage.list_evidence(config.project_id),
        documents=storage.list_documents(config.project_id),
        expected_project_id=config.project_id,
        expected_research_question=config.research_question,
        output_path=target,
        reviewer=reviewer,
    )
    typer.echo(f"admitted evidence: {target}")


@app.command("compile-context")
def compile_context_command(
    brief_path: Path = typer.Argument(..., exists=True, readable=True),
    evidence_records_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(Path("./data/context")),
) -> None:
    """Compile only explicitly approved EvidenceRecords into model context."""
    json_path, markdown_path = compile_context(
        brief_path=brief_path,
        evidence_records_path=evidence_records_path,
        output_dir=output_dir,
    )
    typer.echo(f"context json: {json_path}")
    typer.echo(f"context markdown: {markdown_path}")


@app.command("freeze-release")
def freeze_release_command(
    release_dir: Path = typer.Argument(...),
    report_path: Path = typer.Option(..., exists=True, readable=True),
    brief_path: Path = typer.Option(..., exists=True, readable=True),
    evidence_records_path: Path = typer.Option(..., exists=True, readable=True),
    context_json_path: Path = typer.Option(..., exists=True, readable=True),
    context_markdown_path: Path = typer.Option(..., exists=True, readable=True),
    reviewed_by: str = typer.Option(...),
    config_path: Path | None = typer.Option(None),
    prompt_path: list[Path] = typer.Option([]),
) -> None:
    """Freeze an immutable, self-contained release after final human review."""
    package_root = Path(__file__).resolve().parent
    manifest = freeze_release(
        release_dir=release_dir,
        report_path=report_path,
        brief_path=brief_path,
        evidence_records_path=evidence_records_path,
        context_json_path=context_json_path,
        context_markdown_path=context_markdown_path,
        package_root=package_root,
        reviewed_by=reviewed_by,
        config_path=config_path,
        prompt_paths=prompt_path,
    )
    typer.echo(f"release manifest: {manifest}")


@app.command("verify-release")
def verify_release_command(
    release_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Verify all file sizes and SHA-256 hashes in a frozen release."""
    errors = verify_release(release_dir)
    if errors:
        for error in errors:
            typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(1)
    typer.echo("PASS: release files and hashes match")


@app.command()
def stats(
    project_id: str = typer.Argument(...),
    data_dir: Path = typer.Option(Path("./data")),
) -> None:
    storage = Storage(data_dir)
    documents = storage.list_documents(project_id)
    evidence = storage.list_evidence(project_id)
    typer.echo(
        json.dumps(
            {
                "project_id": project_id,
                "documents": len(documents),
                "candidate_evidence_cards": len(evidence),
                "parse_quality": {
                    quality.value: sum(1 for document in documents if document.parse_quality == quality)
                    for quality in ParseQuality
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
