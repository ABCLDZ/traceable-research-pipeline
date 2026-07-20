"""Export the public JSON Schemas used by the pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from research_pipeline.admission import EvidenceRecordCollection, ReviewPack
from research_pipeline.models import (
    DocumentRecord,
    EvidenceCard,
    EvidenceRecord,
    ResearchBrief,
)
from research_pipeline.release import ReleaseManifest, ReleaseSourceIndex


MODELS = {
    "document_record.schema.json": DocumentRecord,
    "evidence_card.schema.json": EvidenceCard,
    "evidence_record.schema.json": EvidenceRecord,
    "evidence_record_collection.schema.json": EvidenceRecordCollection,
    "research_brief.schema.json": ResearchBrief,
    "review_pack.schema.json": ReviewPack,
    "release_manifest.schema.json": ReleaseManifest,
    "release_source_index.schema.json": ReleaseSourceIndex,
}


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "schemas"
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS.items():
        path = output / filename
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(path)


if __name__ == "__main__":
    main()
