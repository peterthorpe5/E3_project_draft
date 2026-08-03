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
    "--pocket_review_dir=/tmp/pocket_review",
    "--host=0.0.0.0",
    "--port=3838"
  ))

  testthat::expect_equal(config$duckdb_path, "/tmp/example.duckdb")
  testthat::expect_equal(config$resource_source$mode, "duckdb")
  testthat::expect_equal(config$resource_duckdb_path, "/tmp/example.duckdb")
  testthat::expect_equal(config$resource_parquet_path, "")
  testthat::expect_equal(config$resource_run_dir, "")
  testthat::expect_equal(
    config$resource_source$path,
    normalizePath("/tmp/example.duckdb", mustWork = FALSE)
  )
  testthat::expect_equal(config$max_table_rows, 123L)
  testthat::expect_equal(config$default_expression_unit, "FPKM")
  testthat::expect_equal(config$pocket_review_dir, "/tmp/pocket_review")
  testthat::expect_equal(config$host, "0.0.0.0")
  testthat::expect_equal(config$port, 3838L)
})

testthat::test_that("app config accepts each flexible resource option", {
  parquet <- get_app_config(c(
    "--resource_parquet_path=/tmp/master.parquet",
    "--expression_duckdb_path=/tmp/expression.duckdb"
  ))
  testthat::expect_equal(parquet$resource_source$mode, "master_parquet")
  testthat::expect_equal(parquet$resource_derived_dir, "/tmp")
  run <- get_app_config(c("--resource_run_dir=/tmp/workflow_run"))
  testthat::expect_equal(run$resource_source$mode, "run_directory")
  testthat::expect_equal(
    run$resource_derived_dir,
    normalizePath("/tmp/workflow_run", mustWork = FALSE)
  )
  testthat::expect_error(
    get_app_config(c(
      "--resource_duckdb_path=/tmp/resource.duckdb",
      "--resource_parquet_path=/tmp/master.parquet"
    )),
    "exactly one"
  )
})

testthat::test_that("a command-line resource overrides resource environments", {
  old_value <- Sys.getenv("E3_RESOURCE_DUCKDB", unset = NA_character_)
  on.exit({
    if (is.na(old_value)) {
      Sys.unsetenv("E3_RESOURCE_DUCKDB")
    } else {
      Sys.setenv(E3_RESOURCE_DUCKDB = old_value)
    }
  }, add = TRUE)
  Sys.setenv(E3_RESOURCE_DUCKDB = "/tmp/environment.duckdb")
  config <- get_app_config(c(
    "--resource_parquet_path=/tmp/command_line.parquet"
  ))
  testthat::expect_equal(config$resource_source$mode, "master_parquet")
  testthat::expect_equal(config$resource_duckdb_path, "")
})

testthat::test_that("null coalescing operator returns primary or fallback", {
  testthat::expect_equal(NULL %||% "fallback", "fallback")
  testthat::expect_equal("value" %||% "fallback", "value")
})
