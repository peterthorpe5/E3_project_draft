make_test_pocket_review <- function(parent = tempdir(), name = "pocket_review") {
  review_dir <- file.path(parent, name)
  dir.create(file.path(review_dir, "groups"), recursive = TRUE)
  dir.create(file.path(review_dir, "tables"), recursive = TRUE)
  dir.create(file.path(review_dir, "provenance"), recursive = TRUE)
  writeLines("<html>index</html>", file.path(review_dir, "index.html"))
  writeLines(
    "<html>matrix</html>",
    file.path(review_dir, "evidence_matrix.html")
  )
  writeLines(
    "<html><h2>Interactive 3D pocket location</h2></html>",
    file.path(review_dir, "groups", "rank_001__hog__N0.HOG1.html")
  )
  writeLines("{}", file.path(review_dir, "provenance", "run_manifest.json"))
  writeLines(
    c(
      paste(
        "review_rank",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "reference_accession",
        "protein_count",
        "alignment_sequence_count",
        "group_review_html",
        sep = "\t"
      ),
      paste(
        "1",
        "HIERARCHICAL_ORTHOGROUP",
        "N0.HOG1",
        "cluster_1",
        "P1",
        "2",
        "3",
        "groups/rank_001__hog__N0.HOG1.html",
        sep = "\t"
      )
    ),
    file.path(review_dir, "tables", "review_report_index.tsv")
  )
  writeLines(
    c(
      paste(
        "review_rank",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "fasta_identifier",
        "candidate_accession",
        "species_column",
        "is_reference",
        "has_ranked_pocket_evidence",
        "sequence_length",
        "alignment_length",
        sep = "\t"
      ),
      paste(
        "1",
        "HIERARCHICAL_ORTHOGROUP",
        "N0.HOG1",
        "cluster_1",
        "rank_001__P1",
        "P1",
        "Arabidopsis_thaliana",
        "TRUE",
        "TRUE",
        "100",
        "110",
        sep = "\t"
      ),
      paste(
        "1",
        "HIERARCHICAL_ORTHOGROUP",
        "N0.HOG1",
        "cluster_1",
        "rank_001__P2",
        "P2",
        "Zea_mays",
        "FALSE",
        "FALSE",
        "95",
        "110",
        sep = "\t"
      )
    ),
    file.path(review_dir, "tables", "prioritised_group_sequences.tsv")
  )
  writeLines(
    c(
      paste(
        "review_rank",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "candidate_accession",
        "species_column",
        "is_reference",
        "model_status",
        "model_sha256",
        "ca_atom_count",
        "mapped_pocket_ca_count",
        "retained_pocket_count",
        sep = "\t"
      ),
      paste(
        "1",
        "HIERARCHICAL_ORTHOGROUP",
        "N0.HOG1",
        "cluster_1",
        "P1",
        "Arabidopsis_thaliana",
        "TRUE",
        "MODEL_AVAILABLE",
        "abc",
        "100",
        "10",
        "5",
        sep = "\t"
      )
    ),
    file.path(review_dir, "tables", "protein_model_inventory.tsv")
  )
  review_dir
}

testthat::test_that("portable pocket-review bundle is validated and loaded", {
  parent <- tempfile("review_parent_")
  dir.create(parent)
  review_dir <- make_test_pocket_review(parent = parent)
  config <- prepare_pocket_review(explicit_dir = review_dir)

  testthat::expect_true(pocket_review_available(review_dir = review_dir))
  testthat::expect_true(config$available)
  testthat::expect_equal(nrow(config$index), 1L)
  testthat::expect_equal(nrow(config$sequences), 2L)
  testthat::expect_equal(nrow(config$models), 1L)
  testthat::expect_match(
    pocket_review_group_choices(index = config$index)[[1L]],
    "groups/rank_001"
  )
})

testthat::test_that("pocket-review discovery does not guess between bundles", {
  parent <- tempfile("review_discovery_")
  dir.create(parent)
  resource <- file.path(parent, "e3_integrated_resource.duckdb")
  writeLines("placeholder", resource)
  source <- resolve_resource_source(resource_duckdb_path = resource)
  first <- make_test_pocket_review(parent = parent, name = "pocket_review_top200")

  testthat::expect_equal(
    resolve_pocket_review_dir(resource_source = source),
    normalizePath(first, mustWork = TRUE)
  )
  make_test_pocket_review(parent = parent, name = "pocket_review_alternative")
  testthat::expect_equal(
    resolve_pocket_review_dir(resource_source = source),
    ""
  )
})

testthat::test_that("unsafe or incomplete pocket-review bundles fail closed", {
  parent <- tempfile("review_invalid_")
  dir.create(parent)
  review_dir <- make_test_pocket_review(parent = parent)
  index_path <- file.path(review_dir, "tables", "review_report_index.tsv")
  index <- readLines(index_path, warn = FALSE)
  index[[2L]] <- sub(
    "groups/rank_001__hog__N0.HOG1.html",
    "../outside.html",
    index[[2L]],
    fixed = TRUE
  )
  writeLines(index, index_path)

  testthat::expect_error(
    load_pocket_review_index(review_dir = review_dir),
    "unsafe group page"
  )
  unlink(file.path(review_dir, "evidence_matrix.html"))
  testthat::expect_false(pocket_review_available(review_dir = review_dir))
})

testthat::test_that("selected group tables retain model and sequence identifiers", {
  parent <- tempfile("review_members_")
  dir.create(parent)
  config <- prepare_pocket_review(
    explicit_dir = make_test_pocket_review(parent = parent)
  )
  page <- config$index$group_review_html[[1L]]
  row <- selected_pocket_review_row(
    review_config = config,
    group_page = page
  )
  sequences <- selected_pocket_review_members(
    review_config = config,
    review_rank = row$review_rank[[1L]],
    focus = "alignment"
  )
  models <- selected_pocket_review_members(
    review_config = config,
    review_rank = row$review_rank[[1L]],
    focus = "structure"
  )

  testthat::expect_equal(sequences$candidate_accession, c("P1", "P2"))
  testthat::expect_true("fasta_identifier" %in% names(sequences))
  testthat::expect_equal(models$model_status, "MODEL_AVAILABLE")
})

testthat::test_that("pocket-review UI and section focus are stable", {
  structure_ui <- paste(
    as.character(pocket_review_ui(id = "review", focus = "structure")),
    collapse = "\n"
  )
  alignment_ui <- paste(
    as.character(pocket_review_ui(id = "alignment", focus = "alignment")),
    collapse = "\n"
  )

  testthat::expect_match(structure_ui, "review-group_page", fixed = TRUE)
  testthat::expect_match(structure_ui, "review-review_frame", fixed = TRUE)
  testthat::expect_match(structure_ui, "review-member_table", fixed = TRUE)
  testthat::expect_match(alignment_ui, "OrthoFinder-group member", fixed = TRUE)
  testthat::expect_match(
    pocket_review_scroll_script(focus = "structure"),
    "Interactive 3D pocket location",
    fixed = TRUE
  )
  testthat::expect_match(
    pocket_review_scroll_script(focus = "alignment"),
    "Pocket-annotated MAFFT sequence alignment",
    fixed = TRUE
  )
})
