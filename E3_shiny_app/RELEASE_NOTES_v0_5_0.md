# ARIA plant E3 Shiny reporter v0.5.0

## Correctness fixes

- Returns the resolved `resource_source`, Parquet path and run-directory path
  from `get_app_config()`.
- Makes derived-directory inference accept DuckDB, master-Parquet and completed
  run-directory sources without passing unsupported arguments.
- Restores the deterministic unknown-Parquet relation naming expected by the
  test suite. Numeric stage prefixes remain safe because relation identifiers
  are always quoted in generated SQL.
- Removes the candidate master relation from unrelated specialist sections,
  avoiding duplicate candidate-level displays in orthology, domain, expression,
  ligandability and structural tabs.
- Uses `final_evolutionary_candidate_prioritisation` for headline counts. If
  only a cluster-level compatibility source exists, the app deterministically
  retains one lead row per OrthoFinder evolutionary group before counting.

## Threshold explorer

- Adds separate pre-structure and structurally informed views.
- Pairs sliders with manual numeric inputs and provides a one-click reset to the
  current grant-aligned defaults.
- Supports target, mandatory, domain, expression, structural-coverage and
  minimum-druggability thresholds plus categorical evidence requirements.
- Labels results as `PASS`, `NEAR_MISS`, `FAIL` or
  `NOT_STRUCTURALLY_ASSESSED`.
- Uses minimum member druggability as the dynamic all-member gate while
  retaining the original fixed-threshold all-member decision as an audit field.
- Downloads tab-separated custom lists with the active numeric thresholds
  repeated in every row.
- Exposes a substantially expanded evidence table with column visibility,
  filtering and horizontal scrolling.

## Interpretation boundary

The explorer filters completed evidence. It does not rerun pocket detection,
sequence alignment or 3D comparison. Its lists are sensitivity analyses and do
not alter the primary recorded analysis.
