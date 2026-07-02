testthat::test_that("validate_duckdb_path accepts existing files and rejects missing files", {
  existing_file <- tempfile(fileext = ".duckdb")
  missing_file <- tempfile(fileext = ".duckdb")
  writeLines("placeholder", existing_file)

  testthat::expect_true(validate_duckdb_path(existing_file))
  testthat::expect_error(validate_duckdb_path(missing_file), "DuckDB database was not found")
})

testthat::test_that("attached view SQL uses a sanitised alias and main schema", {
  query <- build_attached_view_query(
    table_name = "atlas_expression_long",
    alias = "expr-app"
  )

  testthat::expect_equal(
    query,
    'SELECT * FROM expr_app.main."atlas_expression_long"'
  )
})

testthat::test_that("filter WHERE clauses ignore All, empty, NULL and NA values", {
  where_clause <- build_filter_where_clause(list(
    species_column = "Zea_mays",
    expression_unit = "All",
    organism_part = "",
    condition = NA_character_,
    ignored = NULL
  ))

  testthat::expect_equal(where_clause, 'WHERE "species_column" = \'Zea_mays\'')
  testthat::expect_equal(build_filter_where_clause(list()), "")
})

testthat::test_that("filter-choice SQL targets attached views and excludes blank values", {
  query <- build_filter_choice_query(
    view_name = "atlas_expression_long",
    column_name = "experiment_accession",
    filters = list(species_column = "Zea_mays"),
    alias = "expr-app",
    limit = 25L
  )

  testthat::expect_match(query, "expr_app.main")
  testthat::expect_match(query, "atlas_expression_long")
  testthat::expect_match(query, "experiment_accession")
  testthat::expect_match(query, "species_column")
  testthat::expect_match(query, "LIMIT 25")
})

testthat::test_that("collect_distinct_values returns sorted non-missing values", {
  values <- collect_distinct_values(
    table = tibble::tibble(
      species_column = c("Zea_mays", NA, "Arabidopsis_thaliana", "Zea_mays")
    ),
    column_name = "species_column"
  )

  testthat::expect_equal(values, c("Arabidopsis_thaliana", "Zea_mays"))
})

testthat::test_that("DuckDB reader wrappers query expected views", {
  duckdb_path <- make_test_duckdb()

  expr <- get_expression_long(duckdb_path = duckdb_path) |>
    dplyr::collect()
  expr_meta <- get_expression_with_metadata(duckdb_path = duckdb_path) |>
    dplyr::collect()
  meta <- get_sample_metadata(duckdb_path = duckdb_path) |>
    dplyr::collect()

  testthat::expect_true(nrow(expr) > 0L)
  testthat::expect_true(nrow(expr_meta) > 0L)
  testthat::expect_true(nrow(meta) > 0L)
})

testthat::test_that("filter choices can be collected directly from DuckDB", {
  duckdb_path <- make_test_duckdb()

  species <- collect_filter_values(
    duckdb_path = duckdb_path,
    view_name = "atlas_expression_long",
    column_name = "species_column"
  )

  experiments <- collect_filter_values(
    duckdb_path = duckdb_path,
    view_name = "atlas_expression_long",
    column_name = "experiment_accession",
    filters = list(species_column = "Zea_mays")
  )

  testthat::expect_equal(species, c("Arabidopsis_thaliana", "Zea_mays"))
  testthat::expect_true(all(experiments %in% c("E1", "E2")))
})

testthat::test_that("initial and context filter helpers return named choice lists", {
  duckdb_path <- make_test_duckdb()

  initial_choices <- collect_initial_filter_choices(duckdb_path = duckdb_path)
  context_choices <- collect_context_filter_choices(
    duckdb_path = duckdb_path,
    species_column = "Zea_mays",
    expression_unit = "TPM"
  )

  testthat::expect_named(initial_choices, c("species", "expression_units"))
  testthat::expect_named(
    context_choices,
    c("experiments", "organism_parts", "developmental_stages", "conditions")
  )
  testthat::expect_true("Zea_mays" %in% initial_choices$species)
  testthat::expect_true("leaf" %in% context_choices$organism_parts)
})
