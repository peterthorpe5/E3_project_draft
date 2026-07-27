test_that("gene-name fields are split into aliases", {
  aliases <- split_gene_names(gene_names = c("GENE1 GENE2;GENE3", NA))

  expect_equal(aliases[[1L]], c("GENE1", "GENE2", "GENE3"))
  expect_equal(aliases[[2L]], character())
})

test_that("E3 identifier aliases are built from table fields", {
  e3_tbl <- tibble::tibble(
    entry = "Q9TEST",
    accession = "A0A000001",
    entry_name = "E3_TEST_ARATH",
    gene_names = "RGLG1 RING1",
    organism = "Arabidopsis thaliana"
  )

  alias_tbl <- build_e3_identifier_aliases(e3_tbl = e3_tbl)

  expect_true("protein_accession" %in% alias_tbl$identifier_type)
  expect_true("gene_name" %in% alias_tbl$identifier_type)
  expect_true("RGLG1" %in% alias_tbl$identifier_value)
  expect_true("Arabidopsis_thaliana" %in% alias_tbl$species_column)
})
