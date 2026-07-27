testthat::test_that("resource catalog paths point into derived qc directory", {
  paths <- resource_catalog_paths("/tmp/derived")

  testthat::expect_match(paths$source_manifest, "/tmp/derived/qc/source_file_manifest.tsv", fixed = TRUE)
  testthat::expect_match(paths$duckdb_view_catalog, "/tmp/derived/qc/duckdb_view_catalog.tsv", fixed = TRUE)
})

testthat::test_that("derived directory can be inferred from DuckDB path", {
  inferred <- infer_derived_dir("/project/derived/duckdb/e3_protac_resource.duckdb")
  testthat::expect_equal(inferred, "/project/derived")
})

testthat::test_that("manifest summary groups by top-level folder", {
  manifest <- tibble::tibble(
    relative_path = c(
      "curated_e3_database/tables/e3_ligases.csv",
      "curated_e3_database/tables/e3_ligase_sequences.fasta",
      "literature_reference_datasets/example.tsv"
    )
  )

  summary <- summarise_manifest_by_folder(manifest)
  testthat::expect_equal(sum(summary$files), 3L)
  testthat::expect_true("curated_e3_database" %in% summary$top_level_folder)
})

testthat::test_that("markdown table escapes pipe characters", {
  table <- tibble::tibble(name = "A|B", value = "ok")
  markdown <- dataframe_to_markdown_table(table)

  testthat::expect_true(any(grepl("A\\\\|B", markdown)))
})

testthat::test_that("data-source report is written from small fake catalogs", {
  derived_dir <- tempfile("derived")
  qc_dir <- file.path(derived_dir, "qc")
  dir.create(qc_dir, recursive = TRUE)

  writeLines(
    c(
      "relative_path\tsize_bytes\tsha256",
      "curated_e3_database/tables/e3_ligases.csv\t10\tabc"
    ),
    file.path(qc_dir, "source_file_manifest.tsv")
  )
  writeLines(
    c(
      "table_name\tsource_file\trows\tstatus",
      "e3_ligases\tcurated_e3_database/tables/e3_ligases.csv\t2\twritten"
    ),
    file.path(qc_dir, "tabular_table_catalog.tsv")
  )

  output_path <- file.path(derived_dir, "docs", "FILES_USED.md")
  write_data_sources_report(derived_dir = derived_dir, output_path = output_path)

  testthat::expect_true(file.exists(output_path))
  text <- paste(readLines(output_path), collapse = "\n")
  testthat::expect_match(text, "E3 PROTAC source files", fixed = TRUE)
  testthat::expect_match(text, "curated_e3_database", fixed = TRUE)
})
