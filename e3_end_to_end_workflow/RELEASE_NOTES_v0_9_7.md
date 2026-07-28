# e3_end_to_end_workflow v0.9.7

Release date: 2026-07-28

## Empty Stage 09 schema compatibility repair

Version 0.9.7 corrects Stage 10 integration when the validated Stage 09
`pocket_conservation_summary.parquet` contains zero rows and was created with
the earlier generic empty-table schema.

The legacy writer represented every empty Parquet column as `VARCHAR`.
Stage 10 then attempted expressions such as
`COALESCE(structured_species_count, 0)`. DuckDB rejected the mixed
`VARCHAR` and integer types during query binding, before reading any rows.

Stage 10 now:

- explicitly casts legacy Stage 09 numeric and Boolean columns to their
  scientific types;
- remains strict if a non-empty legacy file contains malformed values;
- assigns the established no-evidence defaults when no matching pocket row
  exists; and
- preserves `NOT_ASSESSED` for disabled three-dimensional structural
  alignment.

New empty Stage 09 pocket-conservation Parquet outputs now retain their
intended numeric and Boolean schema. A regression test recreates the exact
zero-row, all-`VARCHAR` legacy table and demonstrates that the repaired final
query completes.

No controlled input, production configuration, completed upstream result,
scoring weight or configuration digest is changed. The existing production
run can resume against the same immutable YAML after the repaired package is
installed.
