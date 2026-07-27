test_that("expression matrix columns are detected", {
  expression_tsv <- tempfile(fileext = ".tsv")
  readr::write_tsv(
    x = tibble::tibble(
      gene_id = c("gene1", "gene2"),
      gene_name = c("A", "B"),
      leaf = c(1.2, 3.4),
      root = c(0.1, 0.2)
    ),
    file = expression_tsv
  )

  column_info <- detect_expression_columns(expression_tsv = expression_tsv)

  expect_equal(column_info$gene_id_column, "gene_id")
  expect_equal(column_info$gene_name_column, "gene_name")
  expect_equal(column_info$expression_columns, c("leaf", "root"))
})


test_that("very wide expression matrix headers are detected without vroom", {
  expression_tsv <- tempfile(fileext = ".tsv")
  expression_columns <- paste0("sample_", seq_len(20000L))
  header <- paste(c("gene_id", "gene_name", expression_columns), collapse = "\t")
  row <- paste(c("gene1", "A", rep("0", length(expression_columns))), collapse = "\t")
  writeLines(text = c(header, row), con = expression_tsv)

  column_info <- detect_expression_columns(expression_tsv = expression_tsv)

  expect_equal(column_info$gene_id_column, "gene_id")
  expect_equal(column_info$gene_name_column, "gene_name")
  expect_equal(length(column_info$expression_columns), 20000L)
})
