# Extract Evidence Cards V3

For each sentence with an [S0001] tag, decide if it contains information worth extracting.

Extract BOTH:
- quantitative facts (numbers, financials, metrics)
- qualitative information (strategy, outlook, risks, competitive position, management commentary)

Return ONLY a JSON array. No markdown.

Each item:
- sentence_ids: list of [S0001] tags (required)
- evidence_type: one of:
  "quantitative" - achieved numbers, financial results, metrics
  "forecast" - future projections, guidance, outlook
  "qualitative" - non-numeric but substantive information
  "management_statement" - what management says about itself, strategy, or plans
  "policy_target" - goals, ambitions, or commitments
  "third_party_claim" - what others say about the subject
- claim: 1 sentence summary
- confidence: 0.0-1.0
- numeric_values: [{"value", "unit", "currency", "metric_name", "time_range"}] only if source has numbers
- tags: ["keyword1", "keyword2"]

Rules:
- Select sentence IDs exactly as provided and in source order.
- A multi-sentence span must use consecutive sentence IDs.
- DO extract strategy statements, outlook commentary, risk factors, and competitive positioning.
- DO extract management explanations of business trends and drivers.
- DO NOT skip a sentence merely because it has no numbers.
- Forecasts are not facts; management targets are not achieved results.
- Return [] only if there is truly nothing substantive.
- ABSOLUTELY NO markdown or explanation.
