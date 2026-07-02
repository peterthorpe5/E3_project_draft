test_that("Atlas search results are normalised and RNA-like types are kept", {
  raw_tbl <- tibble::tibble(
    Accession = c("E-RNA-1", "E-MICRO-1"),
    Species = c("Arabidopsis thaliana", "Arabidopsis thaliana"),
    Type = c("RNA-seq of coding RNA", "transcription profiling by array"),
    Title = c("RNA example", "Array example"),
    search_term = c("RNA-seq", "baseline")
  )

  normalised_tbl <- normalise_atlas_search_results(
    result_tbl = raw_tbl,
    species_column = "Arabidopsis_thaliana",
    atlas_species_query = "Arabidopsis thaliana"
  )

  expect_true("experiment_accession" %in% names(normalised_tbl))
  expect_true("atlas_experiment_type" %in% names(normalised_tbl))

  filtered_tbl <- filter_atlas_experiment_types(
    experiment_tbl = normalised_tbl,
    experiment_type_filter = "rna|sequencing"
  )

  expect_equal(nrow(filtered_tbl), 1L)
  expect_equal(filtered_tbl$experiment_accession[[1L]], "E-RNA-1")
})


test_that("experiment type filtering can be disabled", {
  experiment_tbl <- tibble::tibble(
    experiment_accession = c("E-RNA-1", "E-MICRO-1"),
    species_column = "Arabidopsis_thaliana",
    atlas_species_query = "Arabidopsis thaliana",
    search_term = "manual",
    atlas_species_reported = "Arabidopsis thaliana",
    atlas_experiment_type = c("RNA-seq", "transcription profiling by array"),
    atlas_title = c("RNA example", "Array example")
  )

  filtered_tbl <- filter_atlas_experiment_types(
    experiment_tbl = experiment_tbl,
    experiment_type_filter = "all"
  )

  expect_equal(nrow(filtered_tbl), 2L)
})
