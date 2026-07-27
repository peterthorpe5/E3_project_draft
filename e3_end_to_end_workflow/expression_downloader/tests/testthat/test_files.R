test_that("local file usability checks empty and non-empty files", {
  missing_file <- tempfile()
  empty_file <- tempfile()
  non_empty_file <- tempfile()

  file.create(empty_file)
  writeLines(text = "content", con = non_empty_file)

  expect_false(local_file_is_usable(file_path = missing_file))
  expect_false(local_file_is_usable(file_path = empty_file))
  expect_true(local_file_is_usable(file_path = non_empty_file))
})

test_that("SQL escaping and identifier quoting are safe", {
  expect_equal(escape_sql_literal(value = "Pete's file"), "Pete''s file")
  expect_equal(quote_duckdb_identifier(identifier = "gene id"), "\"gene id\"")
  expect_equal(quote_duckdb_identifier(identifier = "a\"b"), "\"a\"\"b\"")
})
