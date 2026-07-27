# E3_shiny_app v0.4.0

- Replaces the generic-only scaffold with grant-focused candidate, orthology,
  domain, expression, ligandability, pocket-conservation and 3D-alignment views.
- Adds independent checkbox column controls to every scientific section and the
  all-results browser.
- Supports three interchangeable read-only sources: integrated DuckDB, one
  candidate master Parquet, or all current non-superseded workflow Parquets.
- Adds a Milestone 1/Milestone 2 overview and explicit interpretation boundaries.
- Preserves the raw Expression Atlas summary, table, lookup and plotting modules.
- Adds unit/integration tests for source discovery, lazy Parquet registration,
  section routing, selected-column SQL and UI contracts.
