testthat::test_that("resource database availability is strict", {
  missing_path <- tempfile(fileext = ".duckdb")
  existing_path <- tempfile(fileext = ".duckdb")
  writeLines("placeholder", existing_path)

  testthat::expect_false(resource_database_available(NULL))
  testthat::expect_false(resource_database_available(""))
  testthat::expect_false(resource_database_available(missing_path))
  testthat::expect_true(resource_database_available(existing_path))
})

testthat::test_that("resource query builders quote view names and limit rows", {
  query <- build_resource_preview_query(
    view_name = "source tables weird/name",
    max_rows = 25,
    alias = "e3-resource"
  )

  testthat::expect_match(query, "e3_resource.main", fixed = TRUE)
  testthat::expect_match(query, '"source tables weird/name"', fixed = TRUE)
  testthat::expect_match(query, "LIMIT 25", fixed = TRUE)
})

testthat::test_that("resource catalog summary counts statuses", {
  catalog <- tibble::tibble(
    view_name = c("a", "b", "c"),
    status = c("created", "created", "failed")
  )

  summary <- summarise_resource_catalog_status(catalog)
  testthat::expect_equal(sum(summary$n), 3L)
  testthat::expect_true("created" %in% summary$status)
  testthat::expect_true("failed" %in% summary$status)
})

testthat::test_that("resource helpers collect catalog from a small DuckDB database", {
  duckdb_path <- make_test_resource_duckdb()
  catalog <- collect_resource_view_catalog(duckdb_path = duckdb_path)

  testthat::expect_true("view_name" %in% names(catalog))
  testthat::expect_equal(catalog$view_name[[1]], "proteins__proteins")

  names <- collect_resource_view_names(duckdb_path = duckdb_path)
  testthat::expect_equal(names, "proteins__proteins")

  preview <- collect_resource_preview(
    duckdb_path = duckdb_path,
    view_name = "proteins__proteins",
    max_rows = 1L
  )
  testthat::expect_equal(nrow(preview), 1L)
})
