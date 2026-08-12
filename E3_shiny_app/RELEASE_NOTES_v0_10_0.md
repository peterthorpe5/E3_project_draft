# E3 Shiny app v0.10.0

- Removes the obsolete raw Expression Atlas sidebar and its four dependent
  legacy tabs. Integrated candidate expression remains available in the main
  evidence interface.
- Replaces the permanent sidebar layout with a full-width navigation layout.
- Adds a dedicated computational-chemistry section over the same integrated
  DuckDB relations used by the Python app.
- Retains read-only, bounded queries and TSV downloads.
- Adds a neighbouring formatted Excel download wherever the app exposes a TSV
  table download. Excel tables have frozen headers, filter controls, banded
  rows, readable bounded widths, wrapped long text and semantic numeric formats.
