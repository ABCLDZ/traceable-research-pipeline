---
name: traceable-research
description: Build traceable, human-reviewed research evidence packs from public web pages and PDFs with the research-flow CLI. Use for scoped source ingestion, exact-span EvidenceCard extraction, evidence admission review, approved-context compilation, release freezing, provenance checks, or frozen-release verification. Do not use as an autonomous truth engine, web-wide search agent, or substitute for expert report judgment.
---

# Traceable Research

Use the installed Python package to turn researcher-supplied source URLs into exact-source-bound candidate evidence, a human-reviewed evidence set, sparse analysis context, and a verifiable frozen release.

## Start safely

1. Resolve the directory containing this `SKILL.md` as `<skill-dir>`. Do not assume the skill directory is the current working directory.
2. Run the environment check with an available Python 3 launcher (`python` or
   `python3`):

   ```text
   python "<skill-dir>/scripts/check_environment.py"
   ```

3. Read `research_flow.command_prefix` from the JSON result. Use that exact
   argument list as `<research-command>` for every command in this skill. It is
   normally `["<python-executable>", "-m", "research_pipeline.cli"]`; do not
   replace it with a bare `research-flow` command.
4. If `research_flow.ready` is false, explain that the Python package is a
   separate dependency and ask before installing it. For the public release,
   use:

   ```text
   python -m pip install "git+https://github.com/ABCLDZ/traceable-research-pipeline.git@v0.1.0"
   ```

   If the user already has a local repository checkout and wants an editable
   development install, use `python -m pip install -e <repository-root>` instead.

5. Work in a user-designated project directory. Never store runtime source
   material inside the skill directory.

## Choose the operation

- For a new evidence project, follow the full workflow below.
- For an existing project, inspect its config, `data/projects/<project_id>/`, and current artifacts before choosing the next valid phase.
- For release verification only, run `<research-command> verify-release
  <release-dir>` without modifying the release.
- For object definitions or review decisions, read [references/review-contract.md](references/review-contract.md).
- For exact commands, paths, and recovery rules, read [references/workflow.md](references/workflow.md).
- For configuration fields and a neutral template, read [references/configuration.md](references/configuration.md).

## Full workflow

### 1. Confirm scope

Establish:

- research question;
- entity and aliases;
- date range;
- included and excluded topics;
- seed URLs;
- allowed or blocked domains;
- intended output.

Treat hypotheses as questions to test, not conclusions. Do not invent source URLs or silently broaden the research boundary.

This is human gate 1. Do not initialize or ingest until the user has supplied or approved the scope.

### 2. Initialize and ingest

Create or update a YAML config, then run:

```text
<research-command> init <config> --data-dir <data-dir>
<research-command> ingest <config> --data-dir <data-dir>
```

Report fetched, failed, duplicate, and parse-failed counts. Surface `manual_review_required`, degraded parsing, uncertain table preservation, and missing metadata. Do not hide partial ingestion.

### 3. Extract candidate evidence

Before a paid model call, state that selected parsed source chunks are sent to
the configured DeepSeek-compatible endpoint. Confirm that the material is
appropriate to send and that the API key is available. Run:

```text
<research-command> extract <config> --data-dir <data-dir>
```

The extractor may summarize a selected span, but only code-reconstructed source slices qualify as exact excerpts. Never claim that exact binding proves summary correctness, evidence recall, source truth, or research completeness.

### 4. Build the review pack

Run:

```text
<research-command> build-review-pack <config> --data-dir <data-dir>
```

Report the review-pack path, pending count, blockers, warnings, and parse-quality risks.

This is human gate 2. Stop before admission. Do not set decisions to `admit`, `reject`, `merge`, or `revise` on the reviewer’s behalf unless the user explicitly asks for review assistance. Assistance is not approval. Require explicit user approval of the completed batch before running `admit-evidence`.

### 5. Admit and compile

After approval, run:

```text
<research-command> admit-evidence <config> --reviewer <name> --data-dir <data-dir>
<research-command> compile-context <brief> <evidence-records> --output-dir <context-dir>
```

Compile only approved EvidenceRecords named in the ResearchBrief. Preserve limitations, prohibited extrapolations, counterevidence, open questions, source cutoff date, and unresolved parse risks.

### 6. Analyze with expert control

Use the compiled context as evidence input to a strong analysis prompt. Keep facts, forecasts, policy targets, management statements, and analyst inference distinct.

Do not reconstruct the retired Claim–Inference–ChangeSet system. The agent may draft analysis, but the expert owns the final judgment.

### 7. Freeze and verify

This is human gate 3. Require explicit confirmation that the report and evidence set are ready for release.

Run `<research-command> freeze-release` with the report, brief, admitted
evidence, compiled context, reviewer, and relevant config or prompt paths. Then
run:

```text
<research-command> verify-release <release-dir>
```

Report the manifest path and verification result. A passing verification checks
registered-file integrity and internal binding among the brief, admitted
evidence, source index, and compiled context. It does not authenticate a
publisher, establish source truth or evidence completeness, or prove the report
conclusion.

## Operating rules

- Prefer inspection before mutation when resuming an existing project.
- Never bypass automatic blockers without a reviewer-supplied reason.
- Never edit a frozen release in place.
- Never expose API keys or full sensitive prompt/output content in logs.
- Stop on failed parsing, unresolved pending review decisions, inventory mismatch, hash mismatch, or missing required artifacts.
- After each phase, report artifacts created, counts, warnings, and the next required human decision.
