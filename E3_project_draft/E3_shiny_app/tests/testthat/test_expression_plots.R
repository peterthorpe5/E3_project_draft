testthat::test_that("plot choice helpers return expected identifiers", {
  group_choices <- get_expression_plot_group_choices()
  plot_choices <- get_expression_plot_type_choices()

  testthat::expect_true("sample_or_condition" %in% unname(group_choices))
  testthat::expect_true("organism_part" %in% unname(group_choices))
  testthat::expect_true("profile" %in% unname(plot_choices))
  testthat::expect_true("heatmap" %in% unname(plot_choices))
})

testthat::test_that("plot row limits are safely normalised", {
  testthat::expect_equal(normalise_plot_max_rows(NA), 5000L)
  testthat::expect_equal(normalise_plot_max_rows(1), 100L)
  testthat::expect_equal(normalise_plot_max_rows(100000), 50000L)
  testthat::expect_equal(normalise_plot_max_rows(2500), 2500L)
})

testthat::test_that("plot grouping falls back when a column is unavailable", {
  expr <- make_test_expression_tbl()

  testthat::expect_equal(
    choose_plot_group_column(expr, "organism_part"),
    "organism_part"
  )
  testthat::expect_equal(
    choose_plot_group_column(expr, "missing_column"),
    "sample_or_condition"
  )
})

testthat::test_that("plot group preparation handles missing and blank metadata", {
  expr <- make_test_expression_tbl()
  expr$organism_part[[1L]] <- ""
  expr$organism_part[[2L]] <- NA_character_

  plot_tbl <- add_plot_group(
    expression_tbl = expr,
    group_column = "organism_part"
  )

  testthat::expect_true("plot_group" %in% names(plot_tbl))
  testthat::expect_true("Unknown" %in% plot_tbl$plot_group)
})

testthat::test_that("expression plot summaries aggregate by gene and group", {
  summary_tbl <- prepare_expression_plot_summary(
    expression_tbl = make_test_expression_tbl(),
    group_column = "sample_or_condition"
  )

  testthat::expect_true("mean_expression" %in% names(summary_tbl))
  testthat::expect_true("median_expression" %in% names(summary_tbl))
  testthat::expect_true("n_values" %in% names(summary_tbl))
  testthat::expect_true(nrow(summary_tbl) > 0L)
})

testthat::test_that("plot query requires a gene search and includes a limit", {
  testthat::expect_error(
    build_expression_plot_query(filters = list(gene_search = "")),
    "gene ID or gene-name search"
  )

  query <- build_expression_plot_query(
    filters = list(
      species_column = "Zea_mays",
      expression_unit = "TPM",
      gene_search = "Zm00001"
    ),
    max_rows = 123L
  )

  testthat::expect_match(query, "atlas_expression_with_sample_metadata")
  testthat::expect_match(query, "instr\\(lower")
  testthat::expect_false(grepl("ESCAPE", query, fixed = TRUE))
  testthat::expect_match(query, "LIMIT 123")
})

testthat::test_that("direct DuckDB plot-data helper returns bounded rows", {
  duckdb_path <- make_test_duckdb()

  plot_tbl <- collect_expression_plot_data(
    duckdb_path = duckdb_path,
    filters = list(
      species_column = "Zea_mays",
      expression_unit = "TPM",
      gene_search = "Zm"
    ),
    max_rows = 2L
  )

  testthat::expect_lte(nrow(plot_tbl), 2L)
  testthat::expect_true(all(plot_tbl$species_column == "Zea_mays"))
})

testthat::test_that("plot builders return ggplot objects", {
  testthat::skip_if_not_installed("ggplot2")

  expr <- make_test_expression_tbl()
  summary_tbl <- prepare_expression_plot_summary(expr, "sample_or_condition")

  profile_plot <- build_expression_profile_plot(summary_tbl)
  distribution_plot <- build_expression_distribution_plot(expr, "sample_or_condition")
  heatmap_plot <- build_expression_heatmap_plot(summary_tbl)
  dispatcher_plot <- build_expression_plot(expr, "sample_or_condition", "profile")
  empty_plot <- make_empty_expression_plot("No data")

  testthat::expect_s3_class(profile_plot, "ggplot")
  testthat::expect_s3_class(distribution_plot, "ggplot")
  testthat::expect_s3_class(heatmap_plot, "ggplot")
  testthat::expect_s3_class(dispatcher_plot, "ggplot")
  testthat::expect_s3_class(empty_plot, "ggplot")
})

testthat::test_that("expression plot UI creates expected controls", {
  testthat::skip_if_not_installed("shiny")

  ui <- expression_plot_ui("plot")
  ui_text <- paste(as.character(ui), collapse = "\n")

  testthat::expect_match(ui_text, "Gene ID or gene name contains")
  testthat::expect_match(ui_text, "Plot selected expression")
  testthat::expect_match(ui_text, "plot_data_table")
})

testthat::test_that("expression plot server renders plot and table outputs", {
  testthat::skip_if_not_installed("shiny")
  testthat::skip_if_not_installed("plotly")
  testthat::skip_if_not_installed("DT")

  duckdb_path <- make_test_duckdb()

  shiny::testServer(
    app = expression_plot_server,
    args = list(
      duckdb_path = duckdb_path,
      filters = shiny::reactive(list(
        species_column = "Zea_mays",
        expression_unit = "TPM"
      )),
      default_max_rows = 10L
    ),
    {
      session$setInputs(
        gene_query = "Zm",
        group_column = "sample_or_condition",
        plot_type = "profile",
        max_rows = 10,
        plot_expression = 1
      )

      testthat::expect_error(output$expression_plot, NA)
      testthat::expect_error(output$plot_data_table, NA)
    }
  )
})
