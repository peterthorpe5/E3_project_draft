testthat::test_that("enriched HOG fields include representatives and both ranks", {
  relation_columns <- list(
    hierarchical_membership = c(
      "group_id", "species", "raw_identifier", "parsed_accession"
    ),
    final_evolutionary_candidate_prioritisation = c(
      "primary_group_id", "prestructure_evolutionary_group_rank",
      "final_evolutionary_rank", "lead_cluster_id", "domain_species_fraction",
      "hog_species_count"
    )
  )
  capability <- enriched_hog_capability(relation_columns = relation_columns)
  columns <- enriched_hog_columns(
    result = enriched_hog_overview_key(),
    capability = capability
  )
  testthat::expect_true(capability$available)
  testthat::expect_true(capability$membership_available)
  testthat::expect_true(all(c(
    "hog_prestructure_rank",
    "hog_poststructure_rank",
    "human_hog_representatives",
    "arabidopsis_hog_representatives",
    "human_hog_raw_identifiers",
    "arabidopsis_hog_entries",
    "hog_mapping_statuses",
    "prestructure_evolutionary_group_rank",
    "final_evolutionary_rank",
    "domain_species_fraction",
    "ranking_hog_species_count"
  ) %in% columns))
  member_columns <- enriched_hog_columns(
    result = enriched_hog_members_key(),
    capability = capability
  )
  testthat::expect_true("member_species" %in% member_columns)
  testthat::expect_true("member_raw_identifier" %in% member_columns)
})

testthat::test_that("enriched HOG validation rejects unsupported requests", {
  testthat::expect_error(
    validate_enriched_hog_result(result = "cluster"),
    "Unsupported"
  )
  unavailable <- enriched_hog_capability(relation_columns = list())
  testthat::expect_false(unavailable$available)
  testthat::expect_error(
    enriched_hog_columns(
      result = enriched_hog_overview_key(),
      capability = unavailable
    ),
    "No root-HOG"
  )
})

testthat::test_that("enriched HOG queries join complete auditable context", {
  testthat::skip_if_not_installed("DBI")
  testthat::skip_if_not_installed("duckdb")
  testthat::skip_if_not_installed("duckplyr")
  path <- tempfile(fileext = ".duckdb")
  connection <- DBI::dbConnect(
    drv = duckdb::duckdb(),
    dbdir = path,
    read_only = FALSE
  )
  on.exit({
    try(DBI::dbDisconnect(connection, shutdown = TRUE), silent = TRUE)
    unlink(path)
  }, add = TRUE)
  DBI::dbWriteTable(
    conn = connection,
    name = "hierarchical_membership",
    value = data.frame(
      group_id = c("N0.HOG1", "N0.HOG1", "N0.HOG2"),
      species = c("Homo_sapiens", "Arabidopsis_thaliana", "Zea_mays"),
      raw_identifier = c("sp|HUM1|HUMAN_ONE", "sp|AT1|ARATH_ONE", "MAIZE1"),
      parsed_accession = c("HUM1", "AT1", "MAIZE1"),
      parsed_entry = c("HUMAN_ONE", "ARATH_ONE", ""),
      orthogroup_id = c("OG1", "OG1", "OG2"),
      gene_tree_parent_clade = c("clade1", "clade1", "clade2"),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbWriteTable(
    conn = connection,
    name = "final_evolutionary_candidate_prioritisation",
    value = data.frame(
      primary_group_id = c("N0.HOG1", "N0.HOG1", "N0.HOG3"),
      prestructure_evolutionary_group_rank = c(3L, 4L, 2L),
      final_evolutionary_rank = c(1L, 2L, 5L),
      lead_cluster_id = c("cluster_1", "cluster_1b", "cluster_3"),
      candidate_accessions = c("HUM1;AT1", "HUM1", "OTHER1"),
      domain_species_fraction = c(0.8, 0.7, 0.6),
      recommendation_status = c("PASS", "FAIL", "PASS"),
      hog_species_count = c(99L, 98L, 97L),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbDisconnect(connection, shutdown = TRUE)
  connection <- NULL

  relation_columns <- list(
    hierarchical_membership = c(
      "group_id", "species", "raw_identifier", "parsed_accession",
      "parsed_entry", "orthogroup_id", "gene_tree_parent_clade"
    ),
    final_evolutionary_candidate_prioritisation = c(
      "primary_group_id", "prestructure_evolutionary_group_rank",
      "final_evolutionary_rank", "lead_cluster_id", "candidate_accessions",
      "domain_species_fraction", "recommendation_status", "hog_species_count"
    )
  )
  capability <- enriched_hog_capability(relation_columns = relation_columns)
  overview_columns <- enriched_hog_columns(
    result = enriched_hog_overview_key(),
    capability = capability
  )
  overview <- collect_resource_query(
    duckdb_path = path,
    query = build_enriched_hog_query(
      result = enriched_hog_overview_key(),
      selected_columns = overview_columns,
      capability = capability,
      max_rows = 100L
    )
  )
  testthat::expect_identical(
    overview$hog_id,
    c("N0.HOG1", "N0.HOG3", "N0.HOG2")
  )
  hog1 <- overview[overview$hog_id == "N0.HOG1", , drop = FALSE]
  testthat::expect_identical(hog1$human_hog_representatives, "HUM1")
  testthat::expect_identical(hog1$arabidopsis_hog_representatives, "AT1")
  testthat::expect_identical(hog1$human_hog_entries, "HUMAN_ONE")
  testthat::expect_identical(
    hog1$arabidopsis_hog_raw_identifiers,
    "sp|AT1|ARATH_ONE"
  )
  testthat::expect_identical(as.integer(hog1$hog_prestructure_rank), 3L)
  testthat::expect_identical(as.integer(hog1$hog_poststructure_rank), 1L)
  testthat::expect_identical(
    as.integer(hog1$hog_ranking_source_row_count),
    2L
  )
  testthat::expect_identical(hog1$lead_cluster_id, "cluster_1")
  testthat::expect_identical(as.integer(hog1$ranking_hog_species_count), 99L)

  member_fields <- c(
    "hog_id", "hog_prestructure_rank", "hog_poststructure_rank",
    "human_hog_representatives", "arabidopsis_hog_representatives",
    "member_species", "member_raw_identifier"
  )
  members <- collect_resource_query(
    duckdb_path = path,
    query = build_enriched_hog_query(
      result = enriched_hog_members_key(),
      selected_columns = member_fields,
      capability = capability,
      max_rows = 100L
    )
  )
  hog1_members <- members[members$hog_id == "N0.HOG1", , drop = FALSE]
  testthat::expect_identical(
    hog1_members$member_species,
    c("Arabidopsis_thaliana", "Homo_sapiens")
  )
  testthat::expect_identical(
    unique(as.integer(hog1_members$hog_poststructure_rank)),
    1L
  )
})

testthat::test_that("enriched HOG query bounds and columns are defensive", {
  capability <- list(
    available = TRUE,
    membership_available = FALSE,
    membership_columns = character(),
    ranking_relation = "candidate_master_results",
    ranking_columns = c("primary_group_id", "final_rank")
  )
  testthat::expect_error(
    build_enriched_hog_query(
      result = enriched_hog_overview_key(),
      selected_columns = character(),
      capability = capability
    ),
    "Select at least one"
  )
  testthat::expect_error(
    build_enriched_hog_query(
      result = enriched_hog_overview_key(),
      selected_columns = "not_a_field",
      capability = capability
    ),
    "Unknown"
  )
  testthat::expect_error(
    build_enriched_hog_query(
      result = enriched_hog_overview_key(),
      selected_columns = "hog_id",
      capability = capability,
      max_rows = 0L
    ),
    "between 1 and 100000"
  )
})

testthat::test_that("enriched HOG capability accepts one available source", {
  ranking_only <- enriched_hog_capability(relation_columns = list(
    candidate_master_results = c("primary_group_id", "final_rank")
  ))
  testthat::expect_true(ranking_only$available)
  testthat::expect_false(ranking_only$membership_available)
  testthat::expect_identical(
    ranking_only$ranking_relation,
    "candidate_master_results"
  )
  membership_only <- enriched_hog_capability(relation_columns = list(
    hierarchical_membership = c("group_id", "species", "raw_identifier")
  ))
  testthat::expect_true(membership_only$available)
  testthat::expect_true(membership_only$membership_available)
  testthat::expect_null(membership_only$ranking_relation)
})
