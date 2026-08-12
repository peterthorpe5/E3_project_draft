# E3 Python reporter v0.7.5

This presentation and consistency release makes the two threshold-explorer
result sets explicit without changing the source data, recorded analysis or
scientific gate definitions.

- The explorer now shows a **Pre-structure candidate list** and a
  **Structurally informed candidate list** at the same time.
- Both lists share the same biological threshold controls and row scope. The
  structural controls affect only the structurally informed list.
- Summary metrics distinguish pre-structure passes, structurally assessed
  groups and structurally informed passes.
- Each list has its own bounded table and paired TSV/formatted Excel downloads.
- The former mode selector is removed, so the R and Python apps present the
  same two scientific populations rather than starting on different views.
- A defensive paired-settings helper guarantees that the two evaluations
  differ only by their pre-structure/structural evaluation mode.
- The complete Python gate passes 93 tests with 95% branch-aware coverage.
