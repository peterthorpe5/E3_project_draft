testthat::test_that("resource overview UI exposes catalog outputs", {
  ui_text <- paste(as.character(resource_overview_ui("res")), collapse = "\n")

  testthat::expect_match(ui_text, "res-view_count", fixed = TRUE)
  testthat::expect_match(ui_text, "res-view_catalog", fixed = TRUE)
  testthat::expect_match(ui_text, "res-status_summary", fixed = TRUE)
})

testthat::test_that("resource browser UI exposes bounded preview controls", {
  ui_text <- paste(as.character(resource_browser_ui("browser")), collapse = "\n")

  testthat::expect_match(ui_text, "browser-view_name", fixed = TRUE)
  testthat::expect_match(ui_text, "browser-max_rows", fixed = TRUE)
  testthat::expect_match(ui_text, "browser-preview_table", fixed = TRUE)
})

testthat::test_that("data sources UI exposes provenance outputs", {
  ui_text <- paste(as.character(data_sources_ui("sources")), collapse = "\n")

  testthat::expect_match(ui_text, "sources-source_manifest", fixed = TRUE)
  testthat::expect_match(ui_text, "sources-tabular_catalog", fixed = TRUE)
  testthat::expect_match(ui_text, "sources-inherited_parquet_catalog", fixed = TRUE)
})
