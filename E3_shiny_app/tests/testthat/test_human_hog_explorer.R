test_that("human-HOG view and ranking choices validate defensively", {
  expect_identical(validate_human_hog_view("human"), "human")
  expect_identical(
    validate_human_hog_view("plant_and_human"),
    "plant_and_human"
  )
  expect_error(validate_human_hog_view("cluster"), "Unsupported")
  columns <- list(
    candidate_master_results = c("primary_group_id", "final_rank")
  )
  expect_identical(
    select_human_hog_ranking_relation(columns),
    "candidate_master_results"
  )
  expect_length(human_hog_target_plants(), 12L)
})

test_that("human-HOG UIs distinguish all human and plant-human views", {
  human_ui <- as.character(human_hog_explorer_ui("human", FALSE))
  plant_ui <- as.character(human_hog_explorer_ui("plant", TRUE))
  expect_match(human_ui, "Human-containing HOGs", fixed = TRUE)
  expect_match(human_ui, "human-load_view", fixed = TRUE)
  expect_match(human_ui, "human-download_all_tsv", fixed = TRUE)
  expect_match(plant_ui, "Plant and human HOGs", fixed = TRUE)
  expect_match(plant_ui, "12 curated", fixed = TRUE)
})

test_that("HOG filtering retains every co-member of matched groups", {
  summary <- data.frame(
    hog_id = c("N0.HOG1", "N0.HOG2"),
    human_hog_representatives = c("HUM1", "HUM2"),
    arabidopsis_hog_representatives = c("AT1", ""),
    human_accessions = c("HUM1", "HUM2"),
    stringsAsFactors = FALSE
  )
  human <- data.frame(
    hog_id = c("N0.HOG1", "N0.HOG2"),
    parsed_accession = c("HUM1", "HUM2"),
    stringsAsFactors = FALSE
  )
  members <- data.frame(
    hog_id = c("N0.HOG1", "N0.HOG1", "N0.HOG2"),
    raw_identifier = c("human one", "plant one", "human two"),
    stringsAsFactors = FALSE
  )
  selected <- filter_human_hog_results(summary, human, members, "HUM1")
  expect_identical(selected$summary$hog_id, "N0.HOG1")
  expect_identical(selected$human_members$hog_id, "N0.HOG1")
  expect_identical(
    selected$all_members$hog_id,
    c("N0.HOG1", "N0.HOG1")
  )
  selected_by_arabidopsis <- filter_human_hog_results(
    summary,
    human,
    members,
    "AT1"
  )
  expect_identical(selected_by_arabidopsis$summary$hog_id, "N0.HOG1")
})

test_that("human and plant-human HOG queries execute on representative data", {
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
    "hierarchical_membership",
    data.frame(
      group_id = c(
        "N0.HOG1", "N0.HOG1", "N0.HOG1", "N0.HOG1", "N0.HOG1", "N0.HOG2"
      ),
      species = c(
        "Homo_sapiens", "Homo_sapiens", "Arabidopsis_thaliana",
        "Oryza_sativa", "Hordeum_vulgare", "Homo_sapiens"
      ),
      raw_identifier = c(
        "sp|HUM1|ONE_HUMAN", "sp|HUM1B|ONE_HUMAN_B",
        "sp|AT1|ONE_ARATH", "sp|OS1|ONE_RICE", "sp|HV1|ONE_BARLEY", "HUM2"
      ),
      parsed_accession = c("HUM1", "HUM1B", "AT1", "OS1", "HV1", "HUM2"),
      parsed_entry = c(
        "ONE_HUMAN", "ONE_HUMAN_B", "ONE_ARATH", "ONE_RICE", "ONE_BARLEY",
        "TWO_HUMAN"
      ),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbWriteTable(
    con,
    "candidate_master_results",
    data.frame(
      primary_group_id = "N0.HOG1",
      final_rank = 7L,
      recommendation_status = "PRIORITY",
      cluster_id = "cluster_1",
      candidate_accessions = "AT1",
      final_score = 0.9,
      grant_aligned_prestructure_pass = TRUE,
      grant_aligned_final_pass = TRUE,
      stringsAsFactors = FALSE
    )
  )
  DBI::dbDisconnect(con, shutdown = TRUE)
  con <- NULL
  membership_columns <- c(
    "group_id", "species", "raw_identifier", "parsed_accession", "parsed_entry"
  )
  ranking_columns <- c(
    "primary_group_id", "final_rank", "recommendation_status", "cluster_id",
    "candidate_accessions", "final_score", "grant_aligned_prestructure_pass",
    "grant_aligned_final_pass"
  )
  human <- collect_resource_query(
    path,
    build_human_hog_summary_query(
      "human",
      membership_columns,
      "candidate_master_results",
      ranking_columns
    )
  )
  plant_human <- collect_resource_query(
    path,
    build_human_hog_summary_query(
      "plant_and_human",
      membership_columns,
      "candidate_master_results",
      ranking_columns
    )
  )
  plant_human_members <- collect_resource_query(
    path,
    build_human_hog_member_query(
      "plant_and_human",
      "all",
      membership_columns,
      "candidate_master_results",
      ranking_columns
    )
  )
  expect_identical(human$hog_id, c("N0.HOG1", "N0.HOG2"))
  expect_identical(
    human$human_hog_representatives,
    c("HUM1;HUM1B", "HUM2")
  )
  expect_identical(human$arabidopsis_hog_representatives, c("AT1", ""))
  expect_identical(human$rice_hog_representatives, c("OS1", ""))
  expect_identical(human$barley_hog_representatives, c("HV1", ""))
  expect_identical(plant_human$hog_id, "N0.HOG1")
  expect_identical(as.integer(plant_human$ranking_position), 7L)
  expect_identical(
    unique(plant_human_members$human_hog_representatives),
    "HUM1;HUM1B"
  )
  expect_identical(
    unique(plant_human_members$arabidopsis_hog_representatives),
    "AT1"
  )
  expect_identical(unique(plant_human_members$rice_hog_representatives), "OS1")
  expect_identical(
    unique(plant_human_members$barley_hog_representatives),
    "HV1"
  )
})
