# ARIA plant E3 Shiny reporter v0.9.0

Version 0.9.0 adds a linked, read-only Visual explorer to the R Shiny
application while retaining the v0.8.1 source-loading compatibility repairs.

- The candidate landscape exposes selectable x, y, colour and size fields from
  the authoritative candidate relation. Clicking a point links the candidate
  summary and exact supporting-relation table.
- The expression heatmap compares no more than 25 candidate groups across one
  selected species/context scale and one explicit expression unit.
- The species/tissue tab links the selected group to every available
  tissue-annotated Expression Atlas context, faceted by species. DuckDB
  aggregates all matching contexts before the plotted-cell limit, so the
  separate exact-row preview/download limit cannot truncate the visual profile.
- Missing or unavailable expression evidence remains distinct from measured
  zero.
- Volcano plotting activates only when a loaded relation contains both a
  recognised differential-expression effect-size field and a recognised
  P-value, adjusted-P, FDR or Q-value field. Absolute expression is not treated
  as differential expression.
- All new DuckDB queries are quoted, exact, read-only and hard-bounded.

The complete R `testthat` suite and the all-source parse regression must be run
in the `e3_shiny_app` conda environment before the release is committed.
