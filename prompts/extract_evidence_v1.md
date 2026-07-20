# Extract Evidence Cards

You are extracting structured evidence cards from a document chunk for research analysis.

## Rules

1. Extract ONLY factual claims, numeric data, and explicit statements that are **directly present in the provided text**.
2. Do NOT infer, summarize, or combine information from different parts.
3. For each evidence card:
   - `claim`: A concise summary of what the source says (your words)
   - `original_excerpt`: The EXACT verbatim text from the source (must be a direct quote)
   - `evidence_type`: one of `quantitative`, `qualitative`, `numeric_table`, `forecast`, `policy_target`, `management_statement`, `third_party_claim`
   - `topic`: the research topic this evidence relates to
   - `numeric_values`: ONLY if the excerpt contains numbers — extract each number with its unit, currency, time range, and metric name
   - `confidence`: your confidence that this is an accurate extraction (0.0-1.0)

4. Distinguish carefully:
   - VERIFIED FACT vs. FORECAST (future projections)
   - MANAGEMENT STATEMENT (company claims about itself) vs. THIRD_PARTY_CLAIM (what others say)
   - POLICY TARGET (goals/ambitions) vs. QUANTITATIVE (actual achieved numbers)

5. If a paragraph contains no factual claim, numeric data, or substantive statement, skip it.

6. Output ONLY valid JSON array. No markdown, no explanation.

## Output format

```json
[
  {
    "evidence_id": "auto_001",
    "topic": "revenue",
    "evidence_type": "quantitative",
    "claim": "Company X reported revenue of $Y billion in 2024",
    "original_excerpt": "the exact quoted text from source",
    "page_number": null,
    "section": null,
    "confidence": 0.95,
    "numeric_values": [
      {
        "value": "308.9",
        "unit": "billion CNY",
        "currency": "CNY",
        "time_range": "2024",
        "metric_name": "total revenue",
        "scope": null,
        "notes": null
      }
    ],
    "tags": ["financial", "annual"]
  }
]
```

Return an empty array `[]` if nothing extractable is found.
