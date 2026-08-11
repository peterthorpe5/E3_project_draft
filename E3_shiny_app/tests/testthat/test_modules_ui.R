testthat::test_that("application omits the retired raw-expression interface", {
  app_text <- paste(readLines(file.path(repo_dir, "app.R")), collapse = "\n")

  testthat::expect_false(grepl("Raw Expression Atlas filters", app_text, fixed = TRUE))
  testthat::expect_false(grepl("expression_filters_ui", app_text, fixed = TRUE))
  testthat::expect_false(grepl("expression_filters_server", app_text, fixed = TRUE))
  testthat::expect_false(grepl('"Expression summary"', app_text, fixed = TRUE))
  testthat::expect_false(grepl('"Expression table"', app_text, fixed = TRUE))
  testthat::expect_false(grepl('"Visualise expression"', app_text, fixed = TRUE))
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
