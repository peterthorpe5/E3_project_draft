# e3_python_app v0.2.0

- Adds grant-focused candidate, orthology, domain, expression, ligandability,
  pocket-conservation and 3D-alignment sections.
- Adds independent column selection and TSV downloads for every section.
- Supports an integrated DuckDB, one candidate master Parquet or all current-run
  Parquets through one read-only query layer.
- Adds semicolon-aware exact accession search and a grant progress overview.
- Adds source-layout, selected-column, section, error-path and headless UI tests.
- All 22 tests pass at 98% branch-aware coverage.
