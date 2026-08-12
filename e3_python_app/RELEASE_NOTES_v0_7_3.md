# E3 Python reporter v0.7.3

This presentation-only patch keeps all scientific source values, recorded
ranks and primary-analysis gates unchanged.

- Every in-app data-grid column now receives an explicit pixel width.
- Numeric and logical fields remain compact, identifiers receive more space,
  and narrative interpretation fields receive the widest treatment.
- Wide results therefore use Streamlit's native horizontal scrollbar instead
  of compressing headings and identifiers into near-character-width columns.
- The bounded vertical viewport retains Streamlit's stationary header.

The same underlying data, selected columns, row limits and TSV/Excel downloads
are retained.
