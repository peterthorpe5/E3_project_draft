# e3_source_to_parquet_seed v0.4.1

This assurance patch corrects two partial/empty-source behaviours:

- GO evidence sources are included and counted only when they contain actual
  GO, ubiquitin or exclusion evidence fields;
- typed empty protein and ligandability relations expose the full downstream
  schema when a catalogue is absent;
- Excel source workbooks are explicitly closed after every-sheet ingestion.
- Logging reconfiguration closes only package-owned handlers and leaves
  third-party root handlers intact.

A seven-source integration fixture now asserts exact known answers, and a
separate absent-catalogue fixture verifies typed empty relations. Validation:
96 tests passed with 91% branch-aware coverage.
