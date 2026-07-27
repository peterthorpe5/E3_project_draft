testthat::test_that("as_cli_logical handles common true, false, and default values", {
  testthat::expect_true(as_cli_logical("true"))
  testthat::expect_true(as_cli_logical("TRUE"))
  testthat::expect_true(as_cli_logical("1"))
  testthat::expect_true(as_cli_logical("yes"))
  testthat::expect_false(as_cli_logical("false"))
  testthat::expect_false(as_cli_logical("FALSE"))
  testthat::expect_false(as_cli_logical("0"))
  testthat::expect_false(as_cli_logical("no"))
  testthat::expect_true(as_cli_logical(NULL, default = TRUE))
  testthat::expect_false(as_cli_logical("", default = FALSE))
  testthat::expect_error(as_cli_logical("maybe"), "Could not convert")
})

testthat::test_that("SQL literal escaping handles apostrophes", {
  testthat::expect_equal(escape_sql_literal("Pete's file"), "Pete''s file")
  testthat::expect_equal(escape_sql_literal("plain"), "plain")
})

testthat::test_that("DuckDB identifiers are quoted safely", {
  testthat::expect_equal(
    quote_duckdb_identifier("atlas_expression_long"),
    '"atlas_expression_long"'
  )

  testthat::expect_equal(
    quote_duckdb_identifier('bad"name'),
    '"bad""name"'
  )
})

testthat::test_that("DuckDB aliases are sanitised", {
  testthat::expect_equal(sanitise_duckdb_alias("expr-app"), "expr_app")
  testthat::expect_equal(sanitise_duckdb_alias("123-app"), "db_123_app")
  testthat::expect_equal(sanitise_duckdb_alias("ok_name"), "ok_name")
})
