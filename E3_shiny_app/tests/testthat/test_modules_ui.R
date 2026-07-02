testthat::test_that("expression filter UI contains expected namespaced controls", {
  ui_text <- paste(as.character(expression_filters_ui("filters")), collapse = "\n")

  testthat::expect_match(ui_text, "filters-species_column", fixed = TRUE)
  testthat::expect_match(ui_text, "filters-expression_unit", fixed = TRUE)
  testthat::expect_match(ui_text, "filters-gene_search", fixed = TRUE)
  testthat::expect_match(ui_text, "filters-apply_filters", fixed = TRUE)
})

testthat::test_that("summary UI contains value boxes and metadata output", {
  ui_text <- paste(as.character(expression_summary_ui("summary")), collapse = "\n")

  testthat::expect_match(ui_text, "summary-row_count", fixed = TRUE)
  testthat::expect_match(ui_text, "summary-gene_count", fixed = TRUE)
  testthat::expect_match(ui_text, "summary-metadata_coverage", fixed = TRUE)
})

testthat::test_that("expression table UI contains the table output", {
  ui_text <- paste(as.character(expression_table_ui("table")), collapse = "\n")

  testthat::expect_match(ui_text, "table-expression_table", fixed = TRUE)
})

testthat::test_that("gene lookup UI contains query controls and table output", {
  ui_text <- paste(as.character(gene_lookup_ui("lookup")), collapse = "\n")

  testthat::expect_match(ui_text, "lookup-gene_query", fixed = TRUE)
  testthat::expect_match(ui_text, "lookup-unit", fixed = TRUE)
  testthat::expect_match(ui_text, "lookup-gene_table", fixed = TRUE)
})
