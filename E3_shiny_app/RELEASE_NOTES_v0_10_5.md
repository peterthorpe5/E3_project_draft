# E3 Shiny reporter v0.10.5

This presentation and consistency release makes the two threshold-explorer
result sets explicit without changing the source data, recorded analysis or
scientific gate definitions.

- The explorer now shows a **Pre-structure candidate list** and a
  **Structurally informed candidate list** at the same time.
- Both lists share the same biological threshold controls and row scope. The
  structural controls affect only the structurally informed list.
- The summary boxes distinguish pre-structure passes, structurally assessed
  groups and structurally informed passes.
- Each list has its own bounded table and paired TSV/formatted Excel downloads.
- The former mode selector is removed, eliminating the confusing difference
  between the R app's structural default and the Python app's pre-structure
  default.
- The candidate-landscape Plotly widget now explicitly registers
  `plotly_click`, removing the Shiny event warning while retaining the exact
  point-to-candidate linkage.
- Regression tests cover matched paired settings, both table/download UI
  contracts and Plotly click registration.

The DuckDB temporary-extension directory message remains informational: it
describes session-local extension caching and does not affect the candidate
results.
