# e3_end_to_end_workflow v0.12.0

## Expression evidence-state correction

- `NOT_MAPPED` candidate members now retain null measurement and support fields
  instead of potentially misleading numerical zeroes.
- A uniquely mapped gene with no imported Atlas measurements is reported as
  `NO_EXPRESSION_RECORDS` and excluded from the assessed-expression denominator.
- Genuine measured limited or zero expression remains distinct from missing or
  unmapped evidence.
- `candidate_expression_context_summary` retains experiment, unit, sample,
  organism part (tissue), developmental stage, genotype, cultivar, treatment,
  condition and bounded expression summaries for every uniquely mapped gene.
- The integrated DuckDB publishes this normalised context relation for app-side
  species, tissue and candidate filtering.
- The primary top-200 result remains immutable; these rules apply to new or
  explicitly rerun Stage 07 and downstream releases.
