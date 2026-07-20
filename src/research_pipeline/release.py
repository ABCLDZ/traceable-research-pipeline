"""Freeze and verify a self-contained, internally consistent research release."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from research_pipeline.admission import (
    EvidenceRecordCollection,
    load_evidence_records,
)
from research_pipeline.config import load_config
from research_pipeline.context import load_brief, validate_compiled_context
from research_pipeline.io_utils import write_json_atomic
from research_pipeline.models import EvidenceSourceReference, ResearchBrief


class ReleaseFileEntry(BaseModel):
    path: str
    sha256: str
    bytes: int


class ReleaseManifest(BaseModel):
    schema_version: str = "0.2.0"
    release_status: str = "frozen"
    project_id: str
    research_question: str
    as_of_date: str | None = None
    frozen_at: str
    human_final_review: dict[str, object]
    approved_evidence_record_ids: list[str]
    unresolved_questions: list[str]
    code: dict[str, str]
    files: list[ReleaseFileEntry]
    statement: str


class ReleaseSourceEntry(EvidenceSourceReference):
    evidence_record_id: str


class ReleaseSourceIndex(BaseModel):
    schema_version: str = "0.1.0"
    project_id: str
    research_question: str
    sources: list[ReleaseSourceEntry]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_tree_hash(package_root: str | Path) -> str:
    """Hash all shipped package files, including prompts and other resources."""
    root = Path(package_root)
    digest = hashlib.sha256()
    paths = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _copy_asset(source: Path, target_dir: Path, target_name: str) -> dict[str, object]:
    if not source.is_file():
        raise FileNotFoundError(f"release input is not a file: {source}")
    target = target_dir / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {
        "path": target_name.replace("\\", "/"),
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
    }


def _approved_records(
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
):
    records_by_id = {
        record.evidence_record_id: record for record in collection.records
    }
    if len(records_by_id) != len(collection.records):
        raise ValueError("evidence record collection contains duplicate IDs")
    missing = sorted(set(brief.approved_evidence_ids) - set(records_by_id))
    if missing:
        raise ValueError(f"brief references missing evidence records: {missing}")
    return [records_by_id[record_id] for record_id in brief.approved_evidence_ids]


def _validate_brief_and_records(
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
) -> None:
    if brief.project_id != collection.project_id:
        raise ValueError("brief and evidence records belong to different projects")
    if brief.research_question != collection.research_question:
        raise ValueError("brief and evidence records have different research questions")
    if not brief.approved_evidence_ids:
        raise ValueError("brief has no approved evidence records")
    if len(brief.approved_evidence_ids) != len(set(brief.approved_evidence_ids)):
        raise ValueError("brief contains duplicate approved evidence record IDs")
    for record in _approved_records(brief, collection):
        if not record.source_references:
            raise ValueError(
                f"evidence record {record.evidence_record_id} has no source references"
            )


def _source_index_payload(
    brief: ResearchBrief,
    collection: EvidenceRecordCollection,
) -> dict[str, object]:
    entries: list[ReleaseSourceEntry] = []
    for record in _approved_records(brief, collection):
        for source in record.source_references:
            entries.append(
                ReleaseSourceEntry(
                    **source.model_dump(mode="python"),
                    evidence_record_id=record.evidence_record_id,
                )
            )
    return ReleaseSourceIndex(
        project_id=brief.project_id,
        research_question=brief.research_question,
        sources=entries,
    ).model_dump(mode="json", exclude_none=True)


def _default_prompt_path(package_root: Path) -> Path | None:
    candidate = package_root / "resources" / "extract_evidence_v3.md"
    return candidate if candidate.is_file() else None


def freeze_release(
    *,
    release_dir: str | Path,
    report_path: str | Path,
    brief_path: str | Path,
    evidence_records_path: str | Path,
    context_json_path: str | Path,
    context_markdown_path: str | Path,
    package_root: str | Path,
    reviewed_by: str,
    config_path: str | Path | None = None,
    prompt_paths: Iterable[str | Path] = (),
) -> Path:
    if not reviewed_by.strip():
        raise ValueError("reviewed_by is required")
    release = Path(release_dir)
    if release.exists():
        raise FileExistsError(f"release directory already exists: {release}")

    brief = load_brief(brief_path)
    records = load_evidence_records(evidence_records_path)
    _validate_brief_and_records(brief, records)
    validate_compiled_context(
        brief=brief,
        collection=records,
        context_json_path=context_json_path,
        context_markdown_path=context_markdown_path,
    )
    if config_path is not None:
        config = load_config(config_path)
        if config.project_id != brief.project_id:
            raise ValueError("config and brief belong to different projects")
        if config.research_question != brief.research_question:
            raise ValueError("config and brief have different research questions")

    package = Path(package_root)
    all_prompt_paths = [Path(path) for path in prompt_paths]
    default_prompt = _default_prompt_path(package)
    if default_prompt is not None and all(
        path.resolve() != default_prompt.resolve() for path in all_prompt_paths
    ):
        all_prompt_paths.insert(0, default_prompt)

    release.parent.mkdir(parents=True, exist_ok=True)
    temporary = release.parent / f".{release.name}.staging-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        files: list[dict[str, object]] = []
        report = Path(report_path)
        files.append(_copy_asset(report, temporary, "report" + report.suffix))
        files.append(_copy_asset(Path(brief_path), temporary, "research_brief.json"))
        files.append(
            _copy_asset(Path(evidence_records_path), temporary, "evidence_records.json")
        )
        files.append(_copy_asset(Path(context_json_path), temporary, "compiled_context.json"))
        files.append(
            _copy_asset(Path(context_markdown_path), temporary, "compiled_context.md")
        )
        source_index_path = write_json_atomic(
            temporary / "source_index.json",
            _source_index_payload(brief, records),
        )
        files.append(
            {
                "path": "source_index.json",
                "sha256": sha256_file(source_index_path),
                "bytes": source_index_path.stat().st_size,
            }
        )
        if config_path:
            config = Path(config_path)
            files.append(_copy_asset(config, temporary, "config" + config.suffix))
        for index, prompt in enumerate(all_prompt_paths, 1):
            files.append(
                _copy_asset(
                    prompt,
                    temporary,
                    f"prompts/{index:02d}_{prompt.name}",
                )
            )

        manifest = ReleaseManifest(
            project_id=brief.project_id,
            research_question=brief.research_question,
            as_of_date=brief.as_of_date,
            frozen_at=datetime.now(timezone.utc).isoformat(),
            human_final_review={
                "completed": True,
                "reviewed_by": reviewed_by,
            },
            approved_evidence_record_ids=brief.approved_evidence_ids,
            unresolved_questions=brief.open_questions,
            code={
                "package_tree_sha256": package_tree_hash(package),
                "note": (
                    "Hash covers all shipped package files under package_root; "
                    "it does not certify research conclusions."
                ),
            },
            files=[ReleaseFileEntry.model_validate(item) for item in files],
            statement=(
                "This manifest binds the frozen files to one internally consistent "
                "brief, admitted evidence set, compiled context, and source index. "
                "It does not authenticate publishers or prove research conclusions."
            ),
        )
        manifest_path = temporary / "release_manifest.json"
        manifest_path.write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, release)
        return release / "release_manifest.json"
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _verify_internal_consistency(
    release: Path,
    manifest: ReleaseManifest,
) -> list[str]:
    errors: list[str] = []
    try:
        brief = load_brief(release / "research_brief.json")
        collection = load_evidence_records(release / "evidence_records.json")
        _validate_brief_and_records(brief, collection)
        validate_compiled_context(
            brief=brief,
            collection=collection,
            context_json_path=release / "compiled_context.json",
            context_markdown_path=release / "compiled_context.md",
        )
        source_index = json.loads(
            (release / "source_index.json").read_text(encoding="utf-8")
        )
        if source_index != _source_index_payload(brief, collection):
            errors.append("source_index.json does not match approved evidence records")
        if manifest.project_id != brief.project_id:
            errors.append("manifest project_id does not match research brief")
        if manifest.research_question != brief.research_question:
            errors.append("manifest research_question does not match research brief")
        if manifest.as_of_date != brief.as_of_date:
            errors.append("manifest as_of_date does not match research brief")
        if manifest.approved_evidence_record_ids != brief.approved_evidence_ids:
            errors.append(
                "manifest approved evidence IDs do not match research brief"
            )
        if manifest.unresolved_questions != brief.open_questions:
            errors.append("manifest unresolved questions do not match research brief")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"release semantic validation failed: {exc}")
    return errors


def verify_release(release_dir: str | Path) -> list[str]:
    release = Path(release_dir)
    manifest_path = release / "release_manifest.json"
    if not manifest_path.exists():
        return ["missing release_manifest.json"]
    try:
        manifest = ReleaseManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return [f"invalid release manifest: {exc}"]

    errors: list[str] = []
    expected_paths: set[str] = set()
    for item in manifest.files:
        relative = item.path
        if relative in expected_paths:
            errors.append(f"duplicate manifest path: {relative}")
            continue
        expected_paths.add(relative)
        target = (release / relative).resolve()
        try:
            target.relative_to(release.resolve())
        except ValueError:
            errors.append(f"manifest path escapes release directory: {relative}")
            continue
        if not target.is_file():
            errors.append(f"missing file: {relative}")
            continue
        if target.stat().st_size != item.bytes:
            errors.append(f"byte mismatch: {relative}")
        if sha256_file(target) != item.sha256:
            errors.append(f"hash mismatch: {relative}")

    actual_paths = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file() and path.name != "release_manifest.json"
    }
    for extra in sorted(actual_paths - expected_paths):
        errors.append(f"unmanifested file: {extra}")
    for missing in sorted(expected_paths - actual_paths):
        if f"missing file: {missing}" not in errors:
            errors.append(f"missing file: {missing}")

    if not errors:
        errors.extend(_verify_internal_consistency(release, manifest))
    return errors
