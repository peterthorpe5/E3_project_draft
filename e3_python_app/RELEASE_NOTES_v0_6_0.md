# ARIA plant E3 Python reporter v0.6.0

Version 0.6.0 adds a linked, read-only Visual explorer to the Streamlit
application.

- The candidate landscape exposes user-selectable x, y, colour and size fields
  from the authoritative candidate relation. Point selection links to the exact
  candidate row and any compatible supporting relation.
- The expression heatmap compares up to 25 candidate groups across a selected
  species/context scale while keeping expression units separate.
- The species/tissue view shows every available tissue-annotated context for a
  candidate, faceted by species. DuckDB aggregates all matching contexts before
  the plotted-cell limit, so the separate exact-row preview/download limit
  cannot truncate the visual profile.
- Missing or unavailable expression evidence is never converted to measured
  zero.
- Volcano plotting is capability-gated. The current absolute Expression Atlas
  release does not contain differential effect sizes plus significance values,
  so the tab explains the scientific limitation instead of fabricating a plot.
- Plotly point selection is linked through Streamlit session state; every data
  query is exact, read-only and bounded.

Validation: 48 tests passed with 95% branch-aware coverage, including the new
data-query, visual-preparation, Plotly and headless Streamlit contracts.
