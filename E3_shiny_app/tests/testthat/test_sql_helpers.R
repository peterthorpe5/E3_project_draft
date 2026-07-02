testthat::test_that("SQL literal escaping handles apostrophes", {
  testthat::expect_equal(escape_sql_literal("Pete's file"), "Pete''s file")
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

testthat::test_that("attached view SQL uses main schema", {
  query <- build_attached_view_query(
    table_name = "atlas_expression_long",
    alias = "expr-app"
  )

  testthat::expect_equal(
    query,
    'SELECT * FROM expr_app.main."atlas_expression_long"'
  )
})
