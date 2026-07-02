testthat::test_that("expression filter server returns applied filter values", {
  testthat::skip_if_not_installed("shiny")

  duckdb_path <- make_test_duckdb()

  shiny::testServer(
    app = expression_filters_server,
    args = list(
      duckdb_path = duckdb_path,
      default_expression_unit = "TPM"
    ),
    {
      session$setInputs(
        species_column = "Zea_mays",
        expression_unit = "TPM",
        experiment_accession = "E1",
        organism_part = "leaf",
        developmental_stage = "9 day",
        condition = "leaf section 1",
        gene_search = "Zm",
        minimum_expression = 2,
        apply_filters = 1
      )

      testthat::expect_equal(filters()$species_column, "Zea_mays")
      testthat::expect_equal(filters()$expression_unit, "TPM")
      testthat::expect_equal(filters()$minimum_expression, 2)
    }
  )
})

testthat::test_that("update_filter_select handles empty and non-empty choices", {
  testthat::skip_if_not_installed("shiny")

  shiny::testServer(
    app = function(id) {
      shiny::moduleServer(id, function(input, output, session) {
        non_empty <- update_filter_select(
          session = session,
          input_id = "dummy",
          choices = c("b", "a", "a"),
          include_all = TRUE,
          selected = "b"
        )
        empty <- update_filter_select(
          session = session,
          input_id = "dummy",
          choices = character(),
          include_all = FALSE
        )
        list(non_empty = non_empty, empty = empty)
      })
    },
    {
      testthat::expect_equal(non_empty, c("All", "a", "b"))
      testthat::expect_equal(empty, "All")
    }
  )
})

testthat::test_that("safely_collect_choices returns values and converts errors to NULL", {
  testthat::skip_if_not_installed("shiny")

  shiny::testServer(
    app = function(id) {
      shiny::moduleServer(id, function(input, output, session) {
        ok <- safely_collect_choices(1 + 1, session, "failed")
        bad <- safely_collect_choices(stop("boom"), session, "failed")
        list(ok = ok, bad = bad)
      })
    },
    {
      testthat::expect_equal(ok, 2)
      testthat::expect_null(bad)
    }
  )
})

testthat::test_that("format_summary_count handles good and missing values", {
  testthat::expect_equal(format_summary_count(1000), "1,000")
  testthat::expect_equal(format_summary_count(NA_real_), "0")
  testthat::expect_equal(format_summary_count(NULL), "0")
})

testthat::test_that("expression summary server renders numeric summaries from DuckDB", {
  testthat::skip_if_not_installed("shiny")

  duckdb_path <- make_test_duckdb()

  shiny::testServer(
    app = expression_summary_server,
    args = list(
      duckdb_path = duckdb_path,
      filters = shiny::reactive(list(species_column = "Zea_mays", expression_unit = "TPM"))
    ),
    {
      testthat::expect_equal(output$row_count, "2")
      testthat::expect_equal(output$gene_count, "2")
      testthat::expect_equal(output$experiment_count, "2")
      testthat::expect_equal(output$group_count, "2")
    }
  )
})

testthat::test_that("expression table server renders a DT object from DuckDB", {
  testthat::skip_if_not_installed("shiny")
  testthat::skip_if_not_installed("DT")

  duckdb_path <- make_test_duckdb()

  shiny::testServer(
    app = expression_table_server,
    args = list(
      duckdb_path = duckdb_path,
      filters = shiny::reactive(list(species_column = "Zea_mays", expression_unit = "TPM")),
      max_rows = 2L
    ),
    {
      testthat::expect_error(output$expression_table, NA)
    }
  )
})

testthat::test_that("gene lookup server renders matching gene rows from DuckDB", {
  testthat::skip_if_not_installed("shiny")
  testthat::skip_if_not_installed("DT")

  duckdb_path <- make_test_duckdb()

  shiny::testServer(
    app = gene_lookup_server,
    args = list(
      duckdb_path = duckdb_path,
      max_rows = 10L
    ),
    {
      session$setInputs(gene_query = "NAC", unit = "TPM", lookup = 1)
      testthat::expect_error(output$gene_table, NA)
    }
  )
})
