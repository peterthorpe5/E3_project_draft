testthat::test_that("current thresholds match the completed grant-aligned run", {
  defaults <- current_threshold_defaults()
  testthat::expect_equal(defaults$target_species_fraction, 0.90)
  testthat::expect_equal(defaults$mandatory_species_fraction, 1.00)
  testthat::expect_equal(defaults$domain_species_fraction, 0.80)
  testthat::expect_equal(defaults$expression_species_fraction, 0.80)
  testthat::expect_equal(defaults$structural_species_fraction, 0.75)
  testthat::expect_equal(defaults$minimum_druggability_score, 0.50)
  testthat::expect_equal(RECORDED_MINIMUM_DRUGGABILITY_SCORE, 0.50)
  testthat::expect_true(defaults$require_strict_3d)
  testthat::expect_equal(defaults$mode, "structural")
  testthat::expect_identical(defaults$additional_thresholds, character())
  testthat::expect_equal(
    defaults$minimum_mean_pocket_plddt_fraction,
    0.70
  )
})

testthat::test_that("paired explorer settings differ only by evaluation mode", {
  paired <- paired_threshold_settings(list(
    target_species_fraction = 0.75,
    minimum_druggability_score = 0.35,
    result_scope = "pass_near"
  ))
  testthat::expect_identical(names(paired), c("prestructure", "structural"))
  testthat::expect_identical(paired$prestructure$mode, "prestructure")
  testthat::expect_identical(paired$structural$mode, "structural")
  differing <- names(paired$prestructure)[vapply(
    names(paired$prestructure),
    function(field) {
      !identical(paired$prestructure[[field]], paired$structural[[field]])
    },
    logical(1)
  )]
  testthat::expect_identical(differing, "mode")
  testthat::expect_equal(paired$prestructure$target_species_fraction, 0.75)
  testthat::expect_equal(paired$structural$minimum_druggability_score, 0.35)
})

testthat::test_that("focused final-gate settings change only druggability", {
  recorded <- final_druggability_settings(
    minimum_druggability_score = RECORDED_MINIMUM_DRUGGABILITY_SCORE
  )
  relaxed <- final_druggability_settings(minimum_druggability_score = 0.325)
  differing <- names(recorded)[vapply(names(recorded), function(field) {
    !identical(recorded[[field]], relaxed[[field]])
  }, logical(1))]
  testthat::expect_identical(differing, "minimum_druggability_score")
  testthat::expect_identical(recorded$mode, "structural")
  testthat::expect_identical(recorded$result_scope, "passing")
})

testthat::test_that("focused final-gate source validation is defensive", {
  complete <- c(
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    "all_assessed_members_pass_mapping",
    "conservation_status",
    "three_dimensional_alignment_status",
    "domain_assessed_species_count",
    "expression_evidence_row_count"
  )
  testthat::expect_length(
    final_druggability_source_missing_columns(complete),
    0L
  )
  missing <- final_druggability_source_missing_columns("primary_group_id")
  testthat::expect_true("minimum_druggability_score" %in% missing)
  testthat::expect_true(
    "domain_assessed_species_count or domain_evidence_row_count" %in% missing
  )
})

testthat::test_that("member druggability query retains selected rank-one pockets", {
  testthat::expect_identical(
    select_member_druggability_relation(c(
      "ranked_member_pockets",
      "selected_pockets"
    )),
    "selected_pockets"
  )
  query <- build_member_druggability_query(
    relation = "selected_pockets",
    available = c(
      "cluster_id",
      "candidate_accession",
      "species_column",
      "pocket_number",
      "druggability_score"
    ),
    cluster_ids = c("cluster_1", "cluster_2", "cluster_1"),
    max_rows = 25L
  )
  testthat::expect_match(query, 'FROM "selected_pockets"', fixed = TRUE)
  testthat::expect_match(query, "cluster_1", fixed = TRUE)
  testthat::expect_match(query, "LIMIT 25", fixed = TRUE)
  ranked <- build_member_druggability_query(
    relation = "ranked_member_pockets",
    available = c(
      "cluster_id",
      "member_accession",
      "druggability_score",
      "selection_rank"
    ),
    cluster_ids = "cluster_1"
  )
  testthat::expect_match(
    ranked,
    "TRY_CAST(selection_rank AS INTEGER) = 1",
    fixed = TRUE
  )
  testthat::expect_error(
    build_member_druggability_query(
      relation = "ranked_member_pockets",
      available = c(
        "cluster_id",
        "member_accession",
        "druggability_score"
      ),
      cluster_ids = "cluster_1"
    ),
    "safe rank-one"
  )
})

testthat::test_that("focused final-gate comparison labels entrants and leavers", {
  recorded <- tibble::tibble(
    primary_group_type = c("HOG", "HOG"),
    primary_group_id = c("G1", "G2"),
    minimum_druggability_score = c(0.7, 0.6),
    final_score = c(0.9, 0.8)
  )
  selected <- tibble::tibble(
    primary_group_type = c("HOG", "HOG"),
    primary_group_id = c("G1", "G3"),
    minimum_druggability_score = c(0.7, 0.3),
    final_score = c(0.9, 0.75)
  )
  comparison <- compare_final_druggability_passes(recorded, selected)
  testthat::expect_equal(
    comparison$selected$sensitivity_change,
    c("RECORDED_PASS", "ENTERS_AT_SELECTED_THRESHOLD")
  )
  testthat::expect_setequal(
    comparison$changes$sensitivity_change,
    c("ENTERS_AT_SELECTED_THRESHOLD", "LEAVES_AT_SELECTED_THRESHOLD")
  )
  testthat::expect_setequal(
    comparison$changes$primary_group_id,
    c("G2", "G3")
  )

  empty_recorded <- recorded[0, ]
  entering_only <- compare_final_druggability_passes(
    empty_recorded,
    selected[2, ]
  )
  testthat::expect_identical(
    entering_only$selected$sensitivity_change,
    "ENTERS_AT_SELECTED_THRESHOLD"
  )
  testthat::expect_identical(
    entering_only$changes$primary_group_id,
    "G3"
  )

  empty_result <- compare_final_druggability_passes(
    empty_recorded,
    selected[0, ]
  )
  testthat::expect_equal(nrow(empty_result$selected), 0L)
  testthat::expect_equal(nrow(empty_result$changes), 0L)
  testthat::expect_type(
    empty_result$selected$sensitivity_change,
    "character"
  )
  testthat::expect_type(
    empty_result$changes$sensitivity_change,
    "character"
  )
  testthat::expect_error(
    compare_final_druggability_passes(
      data.frame(score = 1),
      data.frame(score = 1)
    ),
    "stable candidate identity"
  )
})

testthat::test_that("threshold settings are validated defensively", {
  values <- normalise_threshold_settings(settings = list(
    mode = "structural",
    minimum_druggability_score = 0.325,
    result_scope = "pass_near"
  ))
  testthat::expect_equal(values$minimum_druggability_score, 0.325)
  testthat::expect_equal(values$mode, "structural")
  testthat::expect_error(
    normalise_threshold_settings(settings = list(target_species_fraction = 1.1)),
    "0 to 1"
  )
  testthat::expect_error(
    normalise_threshold_settings(settings = list(mode = "unknown")),
    "prestructure"
  )
  testthat::expect_error(
    normalise_threshold_settings(settings = "bad"),
    "named list"
  )
  testthat::expect_error(
    normalise_threshold_settings(settings = list(
      additional_thresholds = "not_a_recorded_score"
    )),
    "unsupported score field"
  )
})

testthat::test_that("optional score thresholds are explicit and mode-aware", {
  specifications <- additional_threshold_specs()
  testthat::expect_gte(length(specifications), 6L)
  testthat::expect_true(all(vapply(
    specifications,
    function(value) value$section %in% c("prestructure", "structural"),
    logical(1)
  )))
  combined <- normalise_threshold_settings(settings = list(
    mode = "structural",
    additional_thresholds = c(
      "evidence_completeness_fraction",
      "mean_pocket_plddt_fraction"
    )
  ))
  testthat::expect_length(active_additional_thresholds(combined), 2L)
  prestructure <- normalise_threshold_settings(settings = list(
    mode = "prestructure",
    additional_thresholds = c(
      "evidence_completeness_fraction",
      "mean_pocket_plddt_fraction"
    )
  ))
  testthat::expect_identical(
    active_additional_thresholds(prestructure),
    "evidence_completeness_fraction"
  )
})

testthat::test_that("threshold relation selection prefers evolutionary groups", {
  testthat::expect_equal(
    select_threshold_relation(relation_names = c(
      "candidate_master_results",
      "final_evolutionary_candidate_prioritisation"
    )),
    "final_evolutionary_candidate_prioritisation"
  )
  testthat::expect_equal(select_threshold_relation("unrelated"), "")
})

testthat::test_that("threshold SQL is bounded and records its settings", {
  available <- c(
    "final_evolutionary_rank",
    "primary_group_id",
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_assessed_species_count",
    "domain_species_fraction",
    "expression_assessed_species_count",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    "all_assessed_members_pass_druggability",
    "all_assessed_members_pass_mapping",
    "conservation_status",
    "three_dimensional_alignment_status",
    "prestructure_score",
    "final_score"
  )
  query <- build_threshold_result_query(
    relation = "final_evolutionary_candidate_prioritisation",
    available = available,
    settings = list(mode = "structural", minimum_druggability_score = 0.30),
    max_rows = 25
  )
  testthat::expect_match(query, "custom_status")
  testthat::expect_match(query, "threshold_minimum_druggability_score")
  testthat::expect_match(query, "0.3 AS threshold_minimum_druggability_score")
  testthat::expect_match(query, "LIMIT 25$")
  testthat::expect_error(
    build_threshold_result_query(
      relation = "final_evolutionary_candidate_prioritisation",
      available = available,
      max_rows = 10001
    ),
    "between 1 and 10000"
  )
})

testthat::test_that("selected optional score gates enter SQL and exports", {
  available <- c(
    "primary_group_id",
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_assessed_species_count",
    "domain_species_fraction",
    "expression_assessed_species_count",
    "expression_species_fraction",
    "three_dimensional_alignment_status",
    "structural_species_fraction",
    "minimum_druggability_score",
    "conservation_status",
    "all_assessed_members_pass_druggability",
    "all_assessed_members_pass_mapping",
    "mean_pocket_plddt_fraction"
  )
  query <- build_threshold_result_query(
    relation = "final_evolutionary_candidate_prioritisation",
    available = available,
    settings = list(
      mode = "structural",
      additional_thresholds = "mean_pocket_plddt_fraction",
      minimum_mean_pocket_plddt_fraction = 0.85
    ),
    max_rows = 25
  )
  testthat::expect_match(
    query,
    "custom_additional_mean_pocket_plddt_fraction_pass",
    fixed = TRUE
  )
  testthat::expect_match(
    query,
    "0.85 AS threshold_minimum_mean_pocket_plddt_fraction",
    fixed = TRUE
  )
  testthat::expect_match(
    query,
    "mean_pocket_plddt_fraction' AS threshold_additional_fields",
    fixed = TRUE
  )
})

testthat::test_that("threshold results retain rich pre-structure evidence", {
  selected <- threshold_result_columns(
    available = c(
      "prestructure_evolutionary_group_rank", "stringent_rank",
      "discovery_seed_protein_names", "domain_unavailable_species",
      "expression_supported_species", "missing_evidence", "final_score"
    ),
    mode = "prestructure"
  )
  testthat::expect_identical(selected, c(
    "prestructure_evolutionary_group_rank", "stringent_rank",
    "domain_unavailable_species", "expression_supported_species",
    "discovery_seed_protein_names", "missing_evidence"
  ))
})

testthat::test_that("threshold explorer reclassifies a druggability near-miss", {
  testthat::skip_if_not_installed("DBI")
  testthat::skip_if_not_installed("duckdb")
  testthat::skip_if_not_installed("duckplyr")

  duckdb_path <- tempfile(fileext = ".duckdb")
  connection <- DBI::dbConnect(
    drv = duckdb::duckdb(),
    dbdir = duckdb_path,
    read_only = FALSE
  )
  candidates <- tibble::tibble(
    final_evolutionary_rank = 1:4,
    primary_group_type = rep("HIERARCHICAL_ORTHOGROUP", 4),
    primary_group_id = paste0("N0.HOG000", 1:4),
    lead_cluster_id = paste0("cluster_", 1:4),
    target_species_fraction = c(1, 1, 1, 1),
    mandatory_species_fraction = c(1, 1, 1, 1),
    domain_assessed_species_count = c(12, 12, 12, 12),
    domain_species_fraction = c(1, 1, 1, 1),
    expression_assessed_species_count = c(10, 10, 10, 10),
    expression_species_fraction = c(1, 1, 0.6, 1),
    structural_species_fraction = c(1, 1, 0, 0),
    minimum_druggability_score = c(0.7, 0.325, 0, 0),
    all_assessed_members_pass_druggability = c(TRUE, FALSE, FALSE, FALSE),
    all_assessed_members_pass_mapping = c(TRUE, TRUE, FALSE, FALSE),
    conservation_status = c(
      "CONSERVED_REGION_SUPPORTED",
      "CONSERVED_REGION_SUPPORTED",
      "NO_STRUCTURAL_EVIDENCE",
      "NO_STRUCTURAL_EVIDENCE"
    ),
    three_dimensional_alignment_status = c(
      "CONSERVED_3D_POCKET_SUPPORTED",
      "CONSERVED_3D_POCKET_SUPPORTED",
      "NOT_ASSESSED",
      "NOT_ASSESSED"
    ),
    prestructure_score = c(0.9, 0.85, 0.8, 0.75),
    final_score = c(0.9, 0.8, 0.6, 0.5)
  )
  DBI::dbWriteTable(
    conn = connection,
    name = "final_evolutionary_candidate_prioritisation",
    value = candidates
  )
  DBI::dbWriteTable(
    conn = connection,
    name = "hierarchical_membership",
    value = data.frame(
      group_id = c("N0.HOG0001", "N0.HOG0001", "N0.HOG0002"),
      species = c(
        "Homo_sapiens", "Arabidopsis_thaliana", "Hordeum_vulgare"
      ),
      raw_identifier = c("HUM1", "AT1", "BARLEY1"),
      parsed_accession = c("H1", "A1", "B1"),
      parsed_entry = c("HUMAN_ONE", "ARATH_ONE", ""),
      orthogroup_id = c("OG1", "OG1", "OG2"),
      gene_tree_parent_clade = c("N1", "N1", "N2"),
      review_status = c("reviewed", "reviewed", "unreviewed"),
      mapping_status = c("mapped", "mapped", "mapped"),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbDisconnect(conn = connection, shutdown = TRUE)
  source <- resolve_resource_source(resource_duckdb_path = duckdb_path)
  available <- names(candidates)

  prestructure <- collect_threshold_summary(
    resource_source = source,
    relation = "final_evolutionary_candidate_prioritisation",
    available = available,
    settings = list(mode = "prestructure")
  )
  testthat::expect_equal(prestructure$pass_count[[1L]], 3)
  testthat::expect_equal(prestructure$near_miss_count[[1L]], 1)

  strict <- collect_threshold_results(
    resource_source = source,
    relation = "final_evolutionary_candidate_prioritisation",
    available = available,
    settings = list(mode = "structural", result_scope = "pass_near"),
    max_rows = 10
  )
  testthat::expect_equal(strict$custom_status, c("PASS", "NEAR_MISS"))
  testthat::expect_equal(
    strict$primary_group_id,
    c("N0.HOG0001", "N0.HOG0002")
  )
  testthat::expect_identical(strict$human_hog_representatives, c("H1", ""))
  testthat::expect_identical(
    strict$arabidopsis_hog_representatives,
    c("A1", "")
  )
  testthat::expect_equal(strict$hog_member_count, c(2, 1))
  testthat::expect_equal(strict$hog_species_count, c(2, 1))

  relaxed <- collect_threshold_results(
    resource_source = source,
    relation = "final_evolutionary_candidate_prioritisation",
    available = available,
    settings = list(
      mode = "structural",
      result_scope = "passing",
      minimum_druggability_score = 0.30
    ),
    max_rows = 10
  )
  testthat::expect_equal(
    relaxed$primary_group_id,
    c("N0.HOG0001", "N0.HOG0002")
  )

  boundary <- collect_threshold_results(
    resource_source = source,
    relation = "final_evolutionary_candidate_prioritisation",
    available = available,
    settings = final_druggability_settings(
      minimum_druggability_score = 0.325
    ),
    max_rows = 10
  )
  testthat::expect_equal(
    boundary$primary_group_id,
    c("N0.HOG0001", "N0.HOG0002")
  )
})

testthat::test_that("threshold explorer UI exposes two clearly labelled tables", {
  ui <- paste(
    as.character(threshold_explorer_ui(id = "explorer")),
    collapse = "\n"
  )
  testthat::expect_match(ui, "explorer-target_species_fraction_slider")
  testthat::expect_match(ui, "explorer-target_species_fraction")
  testthat::expect_match(ui, "explorer-minimum_druggability_score_slider")
  testthat::expect_match(ui, "explorer-additional_thresholds")
  testthat::expect_match(ui, "Two matched result sets", fixed = TRUE)
  testthat::expect_match(ui, "explorer-additional_prestructure_thresholds")
  testthat::expect_match(ui, "explorer-additional_structural_thresholds")
  testthat::expect_match(ui, "Pre-structure candidate list", fixed = TRUE)
  testthat::expect_match(ui, "Structurally informed candidate list", fixed = TRUE)
  testthat::expect_match(ui, "explorer-prestructure_candidate_table")
  testthat::expect_match(ui, "explorer-structural_candidate_table")
  testthat::expect_match(ui, "explorer-prestructure_download_tsv")
  testthat::expect_match(ui, "explorer-prestructure_download_excel")
  testthat::expect_match(ui, "explorer-structural_download_tsv")
  testthat::expect_match(ui, "explorer-structural_download_excel")
  testthat::expect_false(grepl("explorer-mode", ui, fixed = TRUE))
  testthat::expect_match(ui, "NOT_STRUCTURALLY_ASSESSED")
})

testthat::test_that("the new explorer retains every existing application tab", {
  app_text <- paste(
    readLines(file.path(repo_dir, "app.R"), warn = FALSE),
    collapse = "\n"
  )
  expected_tabs <- c(
    "Grant overview",
    "Glossary",
    "Computational recommendations",
    "Threshold explorer",
    "Visual explorer",
    "Candidates",
    "Orthology",
    "Seed & HOG explorer",
    "E3 seed catalogue",
    "Domains",
    "Expression evidence",
    "Ligandability",
    "Pocket conservation",
    "3D structures & pockets",
    "Pocket-aligned sequences",
    "3D alignment",
    "Computational chemistry",
    "All results",
    "Provenance and QC",
    "Files used",
    "About"
  )
  for (tab in expected_tabs) {
    testthat::expect_match(app_text, tab, fixed = TRUE)
  }
})
