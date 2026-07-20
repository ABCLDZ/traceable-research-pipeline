# Extract Evidence Cards V2

For each sentence with an [S001] tag, decide if it contains a factual claim worth extracting.

Return ONLY a JSON array. No markdown.

Each item:
- sentence_ids: list of [S001] tags (required)
- evidence_type: "quantitative"|"qualitative"|"forecast"|"policy_target"|"management_statement"|"third_party_claim"
- claim: 1 sentence summary
- confidence: 0.0-1.0
- numeric_values: [{"value", "unit", "currency", "metric_name", "time_range"}] only if source has numbers
- tags: ["keyword1", "keyword2"]

Rules:
- include ALL relevant sentence IDs, not just the first one
- if a sentence has no factual/numeric content, skip it
- forecasts != facts, management targets != achieved results
- empty [] if nothing extractable
- ABSOLUTELY NO markdown or explanation
