# Workflow reference

## Contents

- Environment
- Project layout
- Command sequence
- Human gates
- Recovery rules

## Environment

Requirements:

- Python 3.11 or newer;
- installed `traceable-research-pipeline` package;
- `DEEPSEEK_API_KEY` only for live extraction;
- network access only for ingestion and live extraction.

Run `python "<skill-dir>/scripts/check_environment.py"` before starting. Read
the returned `research_flow.command_prefix` and use that exact argument list as
`<research-command>` below. Do not assume a bare `research-flow` executable is
on `PATH`.

## Project layout

For `--data-dir data` and project ID `example`:

```text
data/
├── llm_cache/
├── logs/
└── projects/
    └── example/
        ├── raw/
        ├── parsed/
        ├── documents/
        ├── evidence/
        ├── review/
        │   └── review_pack.json
        ├── admitted/
        │   └── evidence_records.json
        ├── context/
        ├── releases/
        ├── research_brief.json
        └── extract_progress.json
```

Runtime source material belongs under the chosen data directory and should normally stay out of version control.

## Command sequence

```text
<research-command> init CONFIG --data-dir DATA
<research-command> ingest CONFIG --data-dir DATA
<research-command> extract CONFIG --data-dir DATA
<research-command> build-review-pack CONFIG --data-dir DATA
<research-command> admit-evidence CONFIG --reviewer NAME --data-dir DATA
<research-command> compile-context BRIEF EVIDENCE_RECORDS --output-dir CONTEXT
<research-command> freeze-release RELEASE_DIR [required options]
<research-command> verify-release RELEASE_DIR
<research-command> stats PROJECT_ID --data-dir DATA
```

Use `<research-command> <command> --help` before constructing an unfamiliar
command, especially `freeze-release`.

The default extraction prompt is packaged with the Python distribution. Pass `--prompt-path` only for an intentional override and retain that prompt in the release inputs.

## Human gates

| Gate | Required decision | Prohibited autonomous action |
|---|---|---|
| Scope | Approve question, boundary, and seed sources | Expanding the research object or inventing URLs |
| Admission | Approve the completed review batch | Applying pending or agent-approved decisions |
| Release | Approve final report and evidence set | Freezing or publishing without confirmation |

## Recovery rules

- If ingestion is partial, report failed URLs and parse-quality risks before proceeding.
- If extraction stops, inspect `extract_progress.json` and the command's error
  result before rerunning. Do not treat a provider or response-parse failure as
  evidence that a document contains no useful evidence.
- If a review pack has pending decisions, do not run admission.
- If admission reports an inventory mismatch, rebuild the review pack or reconcile the exact card inventory; do not delete mismatches silently.
- If exact-span verification fails, reject the candidate instead of weakening the check.
- If release verification fails, treat the release as invalid and rebuild from reviewed source artifacts.
- Never modify files inside an already frozen release to make verification pass.
