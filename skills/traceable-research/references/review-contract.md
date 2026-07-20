# Evidence review contract

## Object meanings

- `DocumentRecord`: fetched source, parsed text, provenance metadata, parse status, and quality signals.
- `EvidenceCard`: model-selected candidate evidence. It is not admitted evidence.
- `EvidenceRecord`: one or more reviewed cards admitted for a specific research
  question, with source references retained for release indexing.
- `ResearchBrief`: approved scope, hypotheses, counterevidence, open questions, limitations, cutoff date, and selected EvidenceRecords.
- `ReleaseManifest`: immutable inventory and hashes for a reviewed release.
  Verification also checks internal binding among the brief, admitted evidence,
  source index, and compiled context; it does not authenticate the publisher or
  certify the conclusion.

## Evidence categories

Keep these semantically distinct:

- `quantitative`: achieved or observed numbers;
- `forecast`: projected future values or scenarios;
- `policy_target`: goals or commitments;
- `management_statement`: a party’s description of itself, plans, or drivers;
- `third_party_claim`: a claim made by another party;
- `qualitative`: substantive non-numeric evidence.

Do not convert a forecast, target, scenario, or management statement into an achieved fact.

## Review decisions

- `admit`: accept one card as an EvidenceRecord.
- `reject`: exclude the card from admitted evidence.
- `merge`: combine at least two related cards sharing a `merge_group`.
- `revise`: admit the source evidence with a reviewer-written corrected summary.

Every item must leave `pending` before admission. A card with an automatic blocker requires a human-authored `manual_override_reason`.

Review at least:

- exact excerpt and source location;
- claim fidelity to the excerpt;
- fact versus forecast/target/statement;
- date, geography, industry, unit, denominator, and scenario;
- parsing or table-preservation risk;
- applicability to the research question;
- prohibited extrapolations;
- conflicting or missing evidence.

## Integrity limits

Exact-span verification means the excerpt is an exact slice of the parsed source text. It does not establish:

- that the source is true;
- that parsing preserved every table or footnote;
- that the model summary is correct;
- that all material evidence was found;
- that the final conclusion is correct.

Preserve these limits in analysis and release notes.
