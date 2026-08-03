# E3 Python app v0.3.0

Released 3 August 2026.

## Scientific corrections

- Headline metrics now use the evolutionary group as their decision unit.
- `final_evolutionary_candidate_prioritisation` is the authoritative source
  when available.
- Compatibility sources are deterministically deduplicated by evolutionary
  group before counts or threshold decisions.
- Groups outside the current structural top 200 are labelled
  `NOT_STRUCTURALLY_ASSESSED`, never as structural failures.

## Interactive threshold explorer

- Preserves the completed grant-aligned defaults: target species 0.90,
  mandatory species 1.00, domain support 0.80, expression support 0.80,
  structural support 0.75 and minimum member druggability 0.50.
- Provides paired sliders and exact numeric inputs.
- Separates pre-structure from structurally informed prioritisation.
- Reports pass, one-gate near-miss, fail and structurally unassessed states.
- Exports expanded evidence fields and all active thresholds as TSV.
- Reuses stored evidence and does not rerun scientific calculations.

## Portable visual review

- Adds `--pocket-review-dir` and `E3_POCKET_REVIEW_DIR`.
- Auto-discovers exactly one valid sibling `pocket_review*` bundle.
- Adds **3D structures & pockets** and **Pocket-aligned sequences** tabs.
- Embeds the self-contained selected-group viewer and MAFFT alignment.
- Returns model and OrthoFinder-group member sequence identifiers as tables and
  TSV downloads.
- Supports search by review rank, evolutionary group, lead DeepClust cluster
  and reference accession.

## Engineering

- Continues to open DuckDB read-only through the native Python `duckdb` client.
- Keeps SQL execution and filtering in DuckDB and collects only bounded results
  into pandas for Streamlit display.
- Adds defensive bundle schema/path validation, unit tests, headless application
  tests, PEP8 validation and Google-style documentation checks.
