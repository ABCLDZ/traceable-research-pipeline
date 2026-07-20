# Configuration reference

Use a YAML project config with this shape:

```yaml
project_id: example_project
entity:
  name: Example Entity
  aliases:
    - Example Alias
research_question: What bounded question should the evidence address?
time_range:
  start: "2024-01-01"
  end: "2026-12-31"
source_policy:
  allowed_domains:
    - example.gov
  blocked_domains: []
  source_types:
    - government_report
    - regulatory_filing
  priority:
    - primary_sources
seed_urls:
  - https://example.gov/report.pdf
analysis_modules:
  - demand
  - regional_risk
```

Rules:

- Use an ASCII `project_id` containing letters, numbers, dots, underscores, or hyphens.
- Keep `seed_urls` researcher-supplied and limited to HTTP/HTTPS.
- Use `allowed_domains` when the source set should be tightly bounded.
- Define exclusions and hypotheses in the generated `research_brief.json`, not as hidden assumptions.
- Treat `analysis_modules` as scope labels, not conclusions.
