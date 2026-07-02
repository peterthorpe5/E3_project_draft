testthat::test_that("command-line parser handles named values, separated values and flags", {
  args <- parse_cli_args(c(
    "--duckdb_path=/tmp/test.duckdb",
    "--host", "0.0.0.0",
    "--flag"
  ))

  testthat::expect_equal(args$duckdb_path, "/tmp/test.duckdb")
  testthat::expect_equal(args$host, "0.0.0.0")
  testthat::expect_true(args$flag)
})

testthat::test_that("command-line parser rejects positional arguments", {
  testthat::expect_error(
    parse_cli_args(c("unexpected")),
    "Unexpected positional argument"
  )
})

testthat::test_that("app config uses command-line values", {
  config <- get_app_config(c(
    "--duckdb_path=/tmp/example.duckdb",
    "--max_table_rows=123",
    "--default_expression_unit=FPKM",
    "--host=0.0.0.0",
    "--port=3838"
  ))

  testthat::expect_equal(config$duckdb_path, "/tmp/example.duckdb")
  testthat::expect_equal(config$max_table_rows, 123L)
  testthat::expect_equal(config$default_expression_unit, "FPKM")
  testthat::expect_equal(config$host, "0.0.0.0")
  testthat::expect_equal(config$port, 3838L)
})

testthat::test_that("null coalescing operator returns primary or fallback", {
  testthat::expect_equal(NULL %||% "fallback", "fallback")
  testthat::expect_equal("value" %||% "fallback", "value")
})
