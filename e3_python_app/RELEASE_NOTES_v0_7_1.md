# E3 Python reporter v0.7.1

This maintenance release improves readability and export completeness without
changing any scientific result or source value.

- Main navigation tabs wrap across multiple rows instead of hiding sections
  behind horizontal tab-scroll arrows.
- Wide result tables retain horizontal scrolling, use a bounded vertical
  viewport with a stationary header, allocate wider text columns and display
  ordinary decimal measures to three places.
- The All results browser now offers both exact TSV and formatted Excel
  downloads for the bounded rows being viewed.
- Excel workbooks show gridlines and explicit cell borders, centre ordinary body
  values, and use left-aligned wrapped 10-point text with capped row heights for
  long narrative cells.
- The glossary now combines project-wide technical terminology with the full
  218-field final-candidate data dictionary and records definitions, units,
  rules, cautions and sources.
- Computational recommendations now documents the complete recorded ranking
  formulas, default weights, tie-breaks and group consolidation below the main
  table. An expandable slider explorer creates a clearly non-authoritative
  alternative ordering with paired TSV and Excel downloads without changing
  official ranks, hard gates or source data.

TSV values and numeric values stored in Excel remain exact. Rounding is display
formatting only.
