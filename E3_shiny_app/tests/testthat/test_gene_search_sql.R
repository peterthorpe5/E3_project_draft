testthat::test_that("gene literal gene-search SQL handles quotes and wildcards literally", {
  condition <- build_gene_instr_condition("AT1G_%O'Brien")

  testthat::expect_match(condition, "instr\\(lower")
  testthat::expect_match(condition, "AT1G", ignore.case = TRUE)
  testthat::expect_match(condition, "o''brien")
  testthat::expect_false(grepl("ESCAPE", condition, fixed = TRUE))
})

testthat::test_that("direct DuckDB gene instr search works without ESCAPE", {
  duckdb_path <- make_test_duckdb()

  display <- collect_expression_display_sql(
    duckdb_path = duckdb_path,
    filters = list(
      species_column = "Zea_mays",
      expression_unit = "TPM",
      gene_search = "Zm"
    ),
    max_rows = 10L
  )

  lookup <- collect_duckdb_query(
    duckdb_path = duckdb_path,
    query = build_gene_lookup_query(
      gene_query = "Zm",
      expression_unit = "TPM",
      max_rows = 10L
    )
  )

  testthat::expect_true(nrow(display) > 0L)
  testthat::expect_true(nrow(lookup) > 0L)
  testthat::expect_true(all(display$species_column == "Zea_mays"))
})
