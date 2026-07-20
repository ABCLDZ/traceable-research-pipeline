# Project status

Status date: 2026-07-21

## Implemented

- Unified Python package and `research-flow` CLI.
- Public HTTP/HTTPS ingestion with domain policy and streamed 50 MiB response limit.
- HTML/PDF parsing with conservative quality signals.
- V3 span-selection extraction as the only production extractor.
- Deterministic EvidenceCard and EvidenceRecord identifiers.
- Cache keys covering system prompt, user prompt, model, token limit and metadata.
- Redacted LLM logs by default; cost estimation only when explicit rates are configured.
- Persistent DocumentRecord and EvidenceCard storage.
- Atomic batch review pack application.
- EvidenceCard aggregation into admitted EvidenceRecords.
- EvidenceRecord source references and frozen source-index generation.
- ResearchBrief-driven sparse context compilation.
- Human-reviewed release freezing with semantic context checks, closed inventory,
  and SHA-256 verification.
- JSON Schema export for public workflow objects.
- Offline synthetic end-to-end demo.
- Argument-governance negative experiment retained as a non-runtime archive.
- Canonical open Agent Skill with Codex and Claude Code installation support.
- Apache-2.0 licensing and public release notice.
- GitHub Actions coverage for Python 3.11-3.13, package building and the offline workflow.
- Synthetic public examples plus an automated open-source residue audit.

## Verification

- The full local test suite passes; CI reruns it on Python 3.11-3.13.
- Python bytecode compilation passes.
- The editable package exposes the CLI; Agent Skills use the environment check's
  explicit command prefix rather than assuming the entry point is on `PATH`.
- Offline demo produces and independently verifies a frozen release.
- `pip check` reports no broken dependencies.
- The open-source audit reports no company-specific markers, private paths or common
  secret formats in the public source set.
- No API call or live web ingestion was required for integration verification.

## Evidence inherited from earlier experiments

- V1 direct-quotation extraction exposed low exact-text fidelity.
- V3 span-selection demonstrated exact source-text reconstruction on tested materials.
- The heavy argument-governance branch failed its terminal comparative test and is not
  a production dependency.

These historical results are evidence about prior experiments, not a new validation
of retrieval recall or research correctness.

## Known limits

- Seed URLs are still supplied by a researcher; web-wide source discovery is out of scope.
- Exact-text binding does not prove that a summary is correct or that important evidence
  was not missed.
- Evidence precision and recall need a manually labeled gold set.
- PDF table preservation remains uncertain unless a source-specific parser is used.
- Domain and obvious private-address checks reduce accidental unsafe fetching but are not
  a full hostile-network sandbox.
- Evidence admission and final release remain human decisions.
- The new integrated CLI has not yet been rerun against paid live API sources.
- GitHub Actions is configured locally, including a clean-wheel smoke test outside
  the checkout, but has not run on GitHub before the first push.

## Deliberate non-goals

- Fully autonomous report generation.
- Automatic semantic propagation across Claim and Inference graphs.
- A database, web frontend, or multi-agent orchestration platform.
- Claims that provenance guarantees conclusion correctness.
