"""文件存储模块。

管理原始文件、解析后文本、证据卡和项目数据的本地存储。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from research_pipeline.ids import validate_identifier
from research_pipeline.models import DocumentRecord, EvidenceCard, FetchStatus, MimeType, ParseStatus


class Storage:
    """本地文件存储管理器。"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base = Path(base_dir).resolve()

    # ── 路径辅助 ──

    def _project_dir(self, project_id: str) -> Path:
        safe_project_id = validate_identifier(project_id, field_name="project_id")
        projects_dir = (self.base / "projects").resolve()
        p = projects_dir / safe_project_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _raw_dir(self, project_id: str) -> Path:
        p = self._project_dir(project_id) / "raw"
        p.mkdir(exist_ok=True)
        return p

    def _documents_dir(self, project_id: str) -> Path:
        p = self._project_dir(project_id) / "documents"
        p.mkdir(exist_ok=True)
        return p

    def _parsed_dir(self, project_id: str) -> Path:
        p = self._project_dir(project_id) / "parsed"
        p.mkdir(exist_ok=True)
        return p

    def _evidence_dir(self, project_id: str) -> Path:
        p = self._project_dir(project_id) / "evidence"
        p.mkdir(exist_ok=True)
        return p

    # ── 哈希 ──

    @staticmethod
    def hash_content(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ── 原始文件保存 ──

    def save_raw(
        self,
        project_id: str,
        document_id: str,
        content: bytes,
        mime_type_str: str,
    ) -> Path:
        """保存原始内容，返回保存路径。"""
        ext = ".html"
        if "pdf" in mime_type_str:
            ext = ".pdf"
        elif "json" in mime_type_str:
            ext = ".json"
        elif "plain" in mime_type_str or "text" in mime_type_str:
            ext = ".txt"

        safe_document_id = validate_identifier(document_id, field_name="document_id")
        path = self._raw_dir(project_id) / f"{safe_document_id}{ext}"
        path.write_bytes(content)
        return path

    def save_parsed_text(self, project_id: str, document_id: str, text: str) -> Path:
        """保存解析后的纯文本。"""
        safe_document_id = validate_identifier(document_id, field_name="document_id")
        path = self._parsed_dir(project_id) / f"{safe_document_id}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def save_document(self, document: DocumentRecord) -> Path:
        safe_document_id = validate_identifier(document.document_id, field_name="document_id")
        path = self._documents_dir(document.project_id) / f"{safe_document_id}.json"
        data = document.model_dump(mode="json", exclude_none=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_document(self, project_id: str, document_id: str) -> Optional[DocumentRecord]:
        safe_document_id = validate_identifier(document_id, field_name="document_id")
        path = self._documents_dir(project_id) / f"{safe_document_id}.json"
        if not path.exists():
            return None
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_documents(self, project_id: str) -> list[DocumentRecord]:
        documents: list[DocumentRecord] = []
        for path in sorted(self._documents_dir(project_id).glob("*.json")):
            documents.append(DocumentRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return documents

    # ── 证据卡 ──

    def save_evidence(self, project_id: str, card: EvidenceCard) -> Path:
        """保存单张证据卡为 JSON。"""
        safe_evidence_id = validate_identifier(card.evidence_id, field_name="evidence_id")
        path = self._evidence_dir(project_id) / f"{safe_evidence_id}.json"
        data = card.model_dump(mode="json", exclude_none=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_evidence(self, project_id: str, evidence_id: str) -> Optional[EvidenceCard]:
        safe_evidence_id = validate_identifier(evidence_id, field_name="evidence_id")
        path = self._evidence_dir(project_id) / f"{safe_evidence_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return EvidenceCard.model_validate(data)

    def list_evidence(self, project_id: str) -> list[EvidenceCard]:
        cards = []
        for path in sorted(self._evidence_dir(project_id).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            cards.append(EvidenceCard.model_validate(data))
        return cards

    # ── 项目 inventory ──

    def list_raw_files(self, project_id: str) -> list[Path]:
        return sorted(self._raw_dir(project_id).iterdir())

    def list_parsed_files(self, project_id: str) -> list[Path]:
        return sorted(self._parsed_dir(project_id).iterdir())
