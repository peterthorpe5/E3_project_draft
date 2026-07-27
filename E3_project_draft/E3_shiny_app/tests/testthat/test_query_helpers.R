testthat::test_that("expression filters apply species, unit, metadata and expression thresholds", {
  expr <- make_test_expression_tbl()

  filtered <- apply_expression_filters(
    expr_table = expr,
    filters = list(
      species_column = "Zea_mays",
      expression_unit = "TPM",
      experiment_accession = "All",
      organism_part = "leaf",
      developmental_stage = "All",
      condition = "All",
      minimum_expression = 2,
      gene_search = "Zm"
    )
  )

  testthat::expect_equal(nrow(filtered), 1L)
  testthat::expect_equal(filtered$expression_unit, "TPM")
  testthat::expect_equal(filtered$organism_part, "leaf")
})

testthat::test_that("expression filters allow All values to pass through", {
  expr <- make_test_expression_tbl()

  filtered <- apply_expression_filters(
    expr_table = expr,
    filters = list(
      species_column = "All",
      expression_unit = "All",
      experiment_accession = "All",
      organism_part = "All",
      developmental_stage = "All",
      condition = "All",
      minimum_expression = NA_real_,
      gene_search = ""
    )
  )

  testthat::expect_equal(nrow(filtered), nrow(expr))
})

testthat::test_that("gene search matches gene IDs and gene names", {
  expr <- make_test_expression_tbl()

  by_id <- apply_expression_filters(
    expr_table = expr,
    filters = list(gene_search = "Zm00002")
  )

  by_name <- apply_expression_filters(
    expr_table = expr,
    filters = list(gene_search = "NAC")
  )

  testthat::expect_equal(by_id$gene_id, "Zm00002")
  testthat::expect_equal(by_name$gene_name, "NAC001")
})

testthat::test_that("expression selection summary counts rows, genes, experiments and groups", {
  summary <- summarise_expression_selection(make_test_expression_tbl())

  testthat::expect_equal(summary$rows, 4L)
  testthat::expect_equal(summary$genes, 3L)
  testthat::expect_equal(summary$experiments, 3L)
  testthat::expect_equal(summary$groups, 2L)
})

testthat::test_that("display collection keeps expected columns and limits rows", {
  display <- collect_expression_display(
    filtered_table = make_test_expression_tbl(),
    max_rows = 2L
  )

  testthat::expect_equal(nrow(display), 2L)
  testthat::expect_true("species_column" %in% names(display))
  testthat::expect_true("expression_value" %in% names(display))
})

testthat::test_that("metadata coverage summary counts non-missing metadata", {
  coverage <- summarise_metadata_coverage(make_test_expression_tbl())

  testthat::expect_equal(coverage$rows, 4L)
  testthat::expect_equal(coverage$rows_with_organism_part, 3)
  testthat::expect_equal(coverage$rows_with_developmental_stage, 3)
  testthat::expect_equal(coverage$rows_with_condition, 3)
})

testthat::test_that("inactive filter detection handles placeholders and empty values", {
  testthat::expect_true(is_inactive_filter_value(NULL))
  testthat::expect_true(is_inactive_filter_value(character()))
  testthat::expect_true(is_inactive_filter_value(NA_character_))
  testthat::expect_true(is_inactive_filter_value(""))
  testthat::expect_true(is_inactive_filter_value("All"))
  testthat::expect_true(is_inactive_filter_value("Loading..."))
  testthat::expect_false(is_inactive_filter_value("Zea_mays"))
})

testthat::test_that("expression SQL WHERE clauses include active filters only", {
  where_clause <- build_expression_where_clause(list(
    species_column = "Zea_mays",
    expression_unit = "TPM",
    experiment_accession = "All",
    organism_part = "leaf",
    developmental_stage = "",
    condition = NA_character_,
    minimum_expression = 2,
    gene_search = "Zm00001"
  ))

  testthat::expect_match(where_clause, '"species_column" = \'Zea_mays\'')
  testthat::expect_match(where_clause, '"expression_unit" = \'TPM\'')
  testthat::expect_match(where_clause, '"organism_part" = \'leaf\'')
  testthat::expect_match(where_clause, "expression_value >= 2")
  testthat::expect_match(where_clause, "instr\\(lower")
  testthat::expect_false(grepl("ESCAPE", where_clause, fixed = TRUE))
  testthat::expect_false(grepl("experiment_accession", where_clause))
})

testthat::test_that("summary, coverage and display SQL target the metadata-aware view", {
  filters <- list(species_column = "Zea_mays", expression_unit = "TPM")

  summary_query <- build_expression_summary_query(filters = filters)
  coverage_query <- build_metadata_coverage_query(filters = filters)
  display_query <- build_expression_display_query(filters = filters, max_rows = 25L)

  testthat::expect_match(summary_query, "atlas_expression_with_sample_metadata")
  testthat::expect_match(summary_query, "COUNT\\(DISTINCT gene_id\\)")
  testthat::expect_match(coverage_query, "rows_with_organism_part")
  testthat::expect_match(display_query, "LIMIT 25")
})

testthat::test_that("direct DuckDB summary helpers return expected values", {
  duckdb_path <- make_test_duckdb()

  summary <- collect_expression_summary(
    duckdb_path = duckdb_path,
    filters = list(species_column = "Zea_mays", expression_unit = "TPM")
  )

  coverage <- collect_metadata_coverage(
    duckdb_path = duckdb_path,
    filters = list(species_column = "Zea_mays", expression_unit = "TPM")
  )

  display <- collect_expression_display_sql(
    duckdb_path = duckdb_path,
    filters = list(species_column = "Zea_mays", expression_unit = "TPM"),
    max_rows = 10L
  )

  testthat::expect_equal(summary$rows, 2)
  testthat::expect_equal(summary$genes, 2)
  testthat::expect_equal(coverage$rows_with_organism_part, 1)
  testthat::expect_equal(nrow(display), 2L)
})

testthat::test_that("gene lookup SQL is bounded and uses literal instr search", {
  query <- build_gene_lookup_query(
    gene_query = "AT1G_%",
    expression_unit = "TPM",
    max_rows = 50L
  )

  testthat::expect_match(query, "LIMIT 50")
  testthat::expect_match(query, "instr\\(lower")
  testthat::expect_false(grepl("ESCAPE", query, fixed = TRUE))
  testthat::expect_match(query, "expression_unit = '")
  testthat::expect_false(grepl("' TPM '", query, fixed = TRUE))
  testthat::expect_match(query, "expression_unit = 'TPM'")
})
