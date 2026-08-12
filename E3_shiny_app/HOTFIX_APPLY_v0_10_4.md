# E3 Shiny v0.10.4 two-test hotfix

This archive is deliberately rooted inside `E3_shiny_app`. Extract it only
after changing into the active Shiny application directory containing
`DESCRIPTION`, `R/` and `tests/`.

```bash
HOTFIX_ARCHIVE="/path/to/E3_shiny_app_v0_10_4_two_test_hotfix_20260812.tar.gz"
cd "/path/to/E3_shiny_app"

test -f DESCRIPTION
test -d R
test -d tests/testthat

tar -xzf "${HOTFIX_ARCHIVE}"

grep '^Version:' DESCRIPTION
grep -n 'expect_s3_class(plot' \
  tests/testthat/test_druggability_visualisations.R
grep -n 'annotated$sensitivity_change <- as.character' \
  R/threshold_explorer.R

Rscript inst/scripts/run_tests.R
```

The verification output must include:

```text
Version: 0.10.4
expect_s3_class(plot, "plotly")
expect_s3_class(plot, "htmlwidget")
annotated$sensitivity_change <- as.character(ifelse(
```

If the test output still says that `plot` was expected to inherit from
`plotly_built`, R is running a different checkout. From the directory in which
the test was launched, locate nearby copies with:

```bash
find .. -maxdepth 3 -name DESCRIPTION -print
```

The two `test_script_utils.R` skips are expected when the R session has no
`--file` argument.
