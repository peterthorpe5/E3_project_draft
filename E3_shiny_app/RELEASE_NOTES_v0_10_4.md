# E3 Shiny reporter v0.10.4

This compatibility patch corrects two R test failures discovered in the
v0.10.3 final-gate visualisation release. It does not change scientific values,
thresholds, gate decisions, rankings or output data.

- Empty recorded and selected sensitivity lists now retain a character-typed
  `sensitivity_change` column. This prevents `dplyr::bind_rows()` from trying to
  combine a zero-length logical column with a character column.
- The empty-result regression test now checks the column type explicitly.
- The Plotly regression test now checks the stable public widget classes,
  `plotly` and `htmlwidget`, rather than the version-dependent internal class
  `plotly_built`.
- The threshold-line assertion remains in place, so the selected slider value
  must still be materialised in the Plotly layout.

The two skipped `test_script_utils.R` tests remain expected when the R session
does not provide a `--file` argument.
