# ARIA plant E3 Python reporter v0.4.0

- Adds a searchable, downloadable glossary covering seeds, grouping units,
  gates, strict predictions, assessed denominators, primary thresholds and
  result labels.
- Adds plain-language help directly beneath every manual threshold control.
- Defines the domain-support denominator as species with usable domain
  annotations; unassessed species are neither passes nor failures.
- Adds species, tissue/organism-part and identifier filtering for workflow
  v0.12.0 `candidate_expression_context_summary` resources.
- Warns that legacy zero count fields on `NOT_MAPPED` rows mean missing mapping,
  not measured biological zero expression.
- Retains every v0.3.0 tab and the immutable primary recommendation results.

