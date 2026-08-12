# E3 Shiny reporter v0.10.1

This maintenance release improves readability and export completeness without
changing any scientific result or source value.

- Wide DataTables now provide horizontal scrolling, a bounded vertical body
  with a stationary header, compact numeric cells and deliberately wider
  identifier and narrative columns.
- The All results browser now offers both exact TSV and formatted Excel
  downloads for the bounded rows being viewed.
- The threshold explorer now opens the pre-structure and structural controls
  together and applies both sets by default. An optional selector adds post-hoc
  gates for compatible recorded aggregate scores; these extra gates are off by
  default and cannot rerun the scientific pipeline.
- Excel workbooks show gridlines and explicit cell borders, centre ordinary body
  values, and use left-aligned wrapped 10-point text with capped row heights for
  long narrative cells.
- The glossary now combines project-wide technical terminology with the full
  218-field final-candidate data dictionary and records definitions, units,
  rules, cautions and sources.
- Computational recommendations now documents every recorded score formula,
  default weight, tie-break and evolutionary-group consolidation step below the
  table. An expandable slider-based sensitivity explorer can produce a clearly
  non-authoritative alternative ordering with paired TSV and Excel downloads;
  it never rewrites official ranks or hard gates.

TSV values and numeric values stored in Excel remain exact. Rounding is display
formatting only.
