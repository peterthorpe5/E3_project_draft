test_that("Expression Atlas FTP manifest has expected files", {
  manifest_tbl <- build_atlas_ftp_manifest(
    experiment_accession = "E-MTAB-5915",
    species_column = "Zea_mays"
  )

  expect_equal(nrow(manifest_tbl), 6L)
  expect_true("tpms" %in% manifest_tbl$file_type)
  expect_true("fpkms" %in% manifest_tbl$file_type)
  expect_true("sample_metadata" %in% manifest_tbl$file_type)
  expect_true(any(grepl(pattern = "E-MTAB-5915-tpms.tsv", x = manifest_tbl$file_name)))
})


test_that("remote manifest checks keep one URL column", {
  mock_remote_checker <- function(url) {
    tibble::tibble(
      url = url,
      remote_exists = TRUE,
      remote_non_empty = TRUE,
      status_code = 200L,
      remote_bytes = 10,
      check_method = "mock"
    )
  }

  manifest_tbl <- tibble::tibble(
    experiment_accession = "E-TEST-1",
    species_column = "Arabidopsis_thaliana",
    file_type = "tpms",
    file_name = "E-TEST-1-tpms.tsv",
    url = "https://example.org/E-TEST-1-tpms.tsv",
    local_path = tempfile(fileext = ".tsv")
  )

  checked_tbl <- check_manifest_remotes(
    manifest_tbl = manifest_tbl,
    remote_checker = mock_remote_checker
  )

  expect_equal(sum(names(checked_tbl) == "url"), 1L)
  expect_true("remote_exists" %in% names(checked_tbl))
  expect_true(checked_tbl$remote_exists[[1L]])
})


test_that("checked manifest can be restricted to experiments with expression matrices", {
  checked_tbl <- tibble::tibble(
    experiment_accession = c("E-RNA-1", "E-RNA-1", "E-MICRO-1"),
    species_column = c(
      "Arabidopsis_thaliana",
      "Arabidopsis_thaliana",
      "Arabidopsis_thaliana"
    ),
    file_type = c("tpms", "sample_metadata", "sample_metadata"),
    file_name = c(
      "E-RNA-1-tpms.tsv",
      "E-RNA-1.condensed-sdrf.tsv",
      "E-MICRO-1.condensed-sdrf.tsv"
    ),
    url = c("url1", "url2", "url3"),
    local_path = c("path1", "path2", "path3"),
    remote_exists = c(TRUE, TRUE, TRUE),
    remote_non_empty = c(TRUE, TRUE, TRUE)
  )

  filtered_tbl <- filter_checked_manifest_to_expression_experiments(
    checked_manifest_tbl = checked_tbl,
    expression_file_types = c("tpms", "fpkms"),
    require_expression_matrix = TRUE
  )

  expect_equal(unique(filtered_tbl$experiment_accession), "E-RNA-1")
  expect_true("sample_metadata" %in% filtered_tbl$file_type)
  expect_false("E-MICRO-1" %in% filtered_tbl$experiment_accession)
})


test_that("expression matrix availability is summarised", {
  checked_tbl <- tibble::tibble(
    experiment_accession = c("E-RNA-1", "E-RNA-1", "E-MICRO-1"),
    species_column = c("Zea_mays", "Zea_mays", "Zea_mays"),
    file_type = c("tpms", "fpkms", "sample_metadata"),
    remote_exists = c(TRUE, TRUE, TRUE),
    remote_non_empty = c(TRUE, TRUE, TRUE)
  )

  summary_tbl <- summary_expression_matrix_availability(
    checked_manifest_tbl = checked_tbl,
    expression_file_types = "tpms,fpkms"
  )

  expect_equal(nrow(summary_tbl), 1L)
  expect_equal(summary_tbl$experiment_accession[[1L]], "E-RNA-1")
  expect_equal(summary_tbl$available_expression_file_types[[1L]], "fpkms,tpms")
})
