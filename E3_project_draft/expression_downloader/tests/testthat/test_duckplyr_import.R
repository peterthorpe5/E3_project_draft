test_that("wide expression TSV can be normalised to long Parquet", {
  skip_if_not_installed("duckplyr")

  expression_tsv <- tempfile(fileext = ".tsv")
  output_parquet <- tempfile(fileext = ".parquet")

  readr::write_tsv(
    x = tibble::tibble(
      gene_id = c("gene1", "gene2"),
      gene_name = c("A", "B"),
      leaf = c(1.2, 3.4),
      root = c(0.1, 0.2)
    ),
    file = expression_tsv
  )

  import_tbl <- normalise_expression_to_parquet(
    expression_tsv = expression_tsv,
    output_parquet = output_parquet,
    experiment_accession = "E-TEST-1",
    species_column = "Arabidopsis_thaliana",
    expression_unit = "TPM",
    force = TRUE
  )

  expect_true(import_tbl$success[[1L]])
  expect_true(local_file_is_usable(file_path = output_parquet))

  expression_tbl <- duckplyr::read_parquet_duckdb(
    path = output_parquet,
    prudence = "stingy"
  ) |>
    dplyr::collect()

  expect_equal(nrow(expression_tbl), 4L)
  expect_true(all(c("leaf", "root") %in% expression_tbl$sample_or_condition))
})
