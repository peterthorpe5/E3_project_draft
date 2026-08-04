test_that("retired R matrix parser fails loudly and directs users to Python", {
  expression_tsv <- tempfile(fileext = ".tsv")
  output_parquet <- tempfile(fileext = ".parquet")

  readr::write_tsv(
    x = tibble::tibble(
      gene_id = c("gene1", "gene2"),
      gene_name = c("A", "B"),
      g1 = c("1,1,1.2,1.3,1.4", "3,3,3.4,3.5,3.6"),
      g2 = c("0,0,0.1,0.2,0.3", "0,0,0.2,0.3,0.4")
    ),
    file = expression_tsv
  )

  expect_error(
    normalise_expression_to_parquet(
      expression_tsv = expression_tsv,
      output_parquet = output_parquet,
      experiment_accession = "E-TEST-1",
      species_column = "Arabidopsis_thaliana",
      expression_unit = "TPM",
      force = TRUE
    ),
    "R/DuckDB Atlas matrix parser is retired"
  )
  expect_false(file.exists(output_parquet))
})
