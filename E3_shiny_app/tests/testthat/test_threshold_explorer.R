testthat::test_that("current thresholds match the completed grant-aligned run", {
  defaults <- current_threshold_defaults()
  testthat::expect_equal(defaults$target_species_fraction, 0.90)
  testthat::expect_equal(defaults$mandatory_species_fraction, 1.00)
  testthat::expect_equal(defaults$domain_species_fraction, 0.80)
  testthat::expect_equal(defaults$expression_species_fraction, 0.80)
  testthat::expect_equal(defaults$structural_species_fraction, 0.75)
  testthat::expect_equal(defaults$minimum_druggability_score, 0.50)
  testthat::expect_true(defaults$require_strict_3d)
  testthat::expect_equal(defaults$mode, "structural")
  testthat::expect_identical(defaults$additional_thresholds, character())
  testthat::expect_equal(
    defaults$minimum_mean_pocket_plddt_fraction,
    0.70
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
})

testthat::test_that("threshold explorer UI exposes sliders, typed values and TSV", {
  ui <- paste(
    as.character(threshold_explorer_ui(id = "explorer")),
    collapse = "\n"
  )
  testthat::expect_match(ui, "explorer-target_species_fraction_slider")
  testthat::expect_match(ui, "explorer-target_species_fraction")
  testthat::expect_match(ui, "explorer-minimum_druggability_score_slider")
  testthat::expect_match(ui, "explorer-additional_thresholds")
  testthat::expect_match(
    ui,
    "Pre-structure + structural thresholds",
    fixed = TRUE
  )
  testthat::expect_match(ui, "explorer-additional_prestructure_thresholds")
  testthat::expect_match(ui, "explorer-additional_structural_thresholds")
  testthat::expect_match(ui, "explorer-download_tsv")
  testthat::expect_match(ui, "explorer-download_excel")
  testthat::expect_match(ui, "Download custom candidate list as Excel")
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
