test_that("authoritative pre-structure HOG sources exclude cluster-only ranks", {
  sources <- list(
    final_evolutionary_candidate_prioritisation = c(
      "primary_group_id", "prestructure_evolutionary_group_rank"
    )
  )
  selected <- select_prestructure_hog_source(relation_columns = sources)
  expect_identical(
    selected$relation,
    "final_evolutionary_candidate_prioritisation"
  )
  expect_identical(
    selected$rank_column,
    "prestructure_evolutionary_group_rank"
  )
  expect_null(selected$pass_column)
  expect_null(select_prestructure_hog_source(
    relation_columns = list(
      prestructure_ranking = c("primary_group_id", "computational_rank")
    )
  ))
})

test_that("ranked HOG query validates its required fields and bounds", {
  columns <- c(
    "primary_group_id", "prestructure_evolutionary_group_rank",
    "candidate_accessions"
  )
  query <- build_prestructure_ranked_hog_query(
    relation = "ranking",
    available = columns,
    rank_column = "prestructure_evolutionary_group_rank",
    max_hogs = 200L
  )
  expect_match(query, "N0.HOG", fixed = TRUE)
  expect_match(query, "LIMIT 200", fixed = TRUE)
  expect_match(query, "human_hog_representatives", fixed = TRUE)
  expect_error(
    build_prestructure_ranked_hog_query(
      relation = "ranking",
      available = columns,
      rank_column = "prestructure_evolutionary_group_rank",
      max_hogs = 0L
    ),
    "between 1 and 10000"
  )
  expect_error(
    build_prestructure_ranked_hog_query(
      relation = "ranking",
      available = columns,
      rank_column = "prestructure_evolutionary_group_rank",
      passes_only = TRUE
    ),
    "pass field"
  )
})

test_that("top-N shortlist ranks pre-structure evidence only", {
  skip_if_not_installed("DBI")
  skip_if_not_installed("duckdb")
  skip_if_not_installed("duckplyr")
  path <- tempfile(fileext = ".duckdb")
  con <- DBI::dbConnect(duckdb::duckdb(), dbdir = path, read_only = FALSE)
  on.exit({
    try(DBI::dbDisconnect(con, shutdown = TRUE), silent = TRUE)
    unlink(path)
  }, add = TRUE)
  DBI::dbWriteTable(
    con,
    "ranking",
    data.frame(
      primary_group_id = c("N0.HOG3", "N0.HOG1", "N0.HOG2", "OG0001"),
      prestructure_evolutionary_group_rank = c(3L, 1L, 2L, 0L),
      grant_aligned_prestructure_pass = c(TRUE, FALSE, TRUE, TRUE),
      final_score = c(0.99, 0.10, 0.50, 0.80),
      selected_pocket_count = c(3L, 0L, 1L, 2L),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbWriteTable(
    con,
    "hierarchical_membership",
    data.frame(
      group_id = c("N0.HOG1", "N0.HOG1", "N0.HOG1", "N0.HOG1", "N0.HOG2"),
      species = c(
        "Homo_sapiens", "Arabidopsis_thaliana", "Oryza_sativa",
        "Hordeum_vulgare", "Homo_sapiens"
      ),
      raw_identifier = c("HUM1", "AT1", "OS1", "HV1", "HUM2"),
      parsed_accession = c("HUM1", "AT1", "OS1", "HV1", "HUM2"),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbDisconnect(con, shutdown = TRUE)
  con <- NULL
  result <- collect_resource_query(
    duckdb_path = path,
    query = build_prestructure_ranked_hog_query(
      relation = "ranking",
      available = c(
        "primary_group_id", "prestructure_evolutionary_group_rank",
        "grant_aligned_prestructure_pass", "final_score",
        "selected_pocket_count"
      ),
      rank_column = "prestructure_evolutionary_group_rank",
      max_hogs = 2L,
      membership_available = TRUE,
      membership_columns = c(
        "group_id", "species", "raw_identifier", "parsed_accession"
      )
    )
  )
  expect_identical(result$primary_group_id, c("N0.HOG1", "N0.HOG2"))
  expect_identical(result$grant_aligned_prestructure_pass, c(FALSE, TRUE))
  expect_false("final_score" %in% names(result))
  expect_false("selected_pocket_count" %in% names(result))
  expect_identical(result$human_hog_representatives, c("HUM1", "HUM2"))
  expect_identical(result$arabidopsis_hog_representatives, c("AT1", ""))
  expect_identical(result$rice_hog_representatives, c("OS1", ""))
  expect_identical(result$barley_hog_representatives, c("HV1", ""))

  passing <- collect_resource_query(
    duckdb_path = path,
    query = build_prestructure_ranked_hog_query(
      relation = "ranking",
      available = c(
        "primary_group_id", "prestructure_evolutionary_group_rank",
        "grant_aligned_prestructure_pass", "final_score"
      ),
      rank_column = "prestructure_evolutionary_group_rank",
      max_hogs = 2L,
      passes_only = TRUE,
      pass_column = "grant_aligned_prestructure_pass"
    )
  )
  expect_identical(passing$primary_group_id, c("N0.HOG2", "N0.HOG3"))
  expect_true(all(passing$grant_aligned_prestructure_pass))
})

test_that("review columns preserve rich evidence and remove structural fields", {
  selected <- prestructure_review_columns(c(
    "candidate_accessions", "final_score", "expression_score",
    "prestructure_evolutionary_group_rank", "primary_group_id",
    "three_dimensional_alignment_status", "sensitivity_alignment_status",
    "conservation_rescued_accession_count", "alphafold_model_path",
    "discovery_seed_protein_names"
  ))
  expect_identical(selected, c(
    "prestructure_evolutionary_group_rank", "primary_group_id",
    "candidate_accessions", "expression_score", "discovery_seed_protein_names"
  ))
})

test_that("ranked HOG filtering retains the original recorded ranks", {
  data <- data.frame(
    primary_group_id = c("N0.HOG1", "N0.HOG2"),
    prestructure_evolutionary_group_rank = c(1L, 2L),
    human_hog_representatives = c("HUM1", "HUM2"),
    stringsAsFactors = FALSE
  )
  selected <- filter_prestructure_ranked_hogs(data = data, query = "HUM2")
  expect_identical(selected$primary_group_id, "N0.HOG2")
  expect_identical(selected$prestructure_evolutionary_group_rank, 2L)
  expect_identical(
    filter_prestructure_ranked_hogs(data = data, query = character()),
    data
  )
})

test_that("ranked HOG summaries tolerate empty and unavailable rank values", {
  data <- data.frame(
    prestructure_evolutionary_group_rank = c(4L, 2L, NA_integer_)
  )
  summary <- summarise_prestructure_hog_ranks(
    data = data,
    rank_column = "prestructure_evolutionary_group_rank"
  )
  expect_identical(summary$returned_count, 3L)
  expect_identical(summary$best_rank, 2)
  expect_identical(summary$lowest_rank, 4)
  missing <- summarise_prestructure_hog_ranks(
    data = data.frame(error = character()),
    rank_column = "prestructure_evolutionary_group_rank"
  )
  expect_identical(missing$returned_count, 0L)
  expect_true(is.na(missing$best_rank))
})

test_that("ranked HOG UI exposes top-N and both download formats", {
  ui <- as.character(prestructure_hog_explorer_ui("ranked"))
  expect_match(ui, "ranked-top_n", fixed = TRUE)
  expect_match(ui, "ranked-pass_filter", fixed = TRUE)
  expect_match(ui, "max=\"500\"", fixed = TRUE)
  expect_match(ui, "ranked-download_tsv", fixed = TRUE)
  expect_match(ui, "ranked-download_excel", fixed = TRUE)
})
