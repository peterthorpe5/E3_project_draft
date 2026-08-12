testthat::test_that("grant-facing relation classification is stable", {
  relations <- c(
    "top_computational_review_shortlist",
    "top_50_computational_review_shortlist",
    "top_20_computational_review_shortlist",
    "gate_sensitivity_summary",
    "candidate_master_results",
    "candidate_group_member_sequences",
    "domain_summary",
    "candidate_expression_context_summary",
    "candidate_expression_summary",
    "selected_pockets",
    "pocket_conservation_summary",
    "structural_alignment_summary",
    "resource_metadata"
  )
  testthat::expect_equal(
    relations_for_result_section(relations, "final_recommendations"),
    c(
      "top_computational_review_shortlist",
      "top_50_computational_review_shortlist",
      "top_20_computational_review_shortlist",
      "gate_sensitivity_summary"
    )
  )
  testthat::expect_equal(
    infer_result_section("grant_aligned_predicted_candidates"),
    "final_recommendations"
  )
  testthat::expect_equal(
    relations_for_result_section(relations, "orthology"),
    "candidate_group_member_sequences"
  )
  testthat::expect_equal(
    infer_result_section("candidate_expression_summary"),
    "expression"
  )
  testthat::expect_equal(
    relations_for_result_section(relations, "expression"),
    c(
      "candidate_expression_context_summary",
      "candidate_expression_summary"
    )
  )
  testthat::expect_equal(infer_result_section("unclassified_table"), "other")
  testthat::expect_error(
    relations_for_result_section(relations, "missing"),
    "Unknown"
  )
})

testthat::test_that("computational chemistry has a dedicated result section", {
  relations <- c("group_pharmacophore_summary", "threshold_sensitivity")
  testthat::expect_equal(
    infer_result_section("group_pharmacophore_summary"),
    "computational_chemistry"
  )
  testthat::expect_equal(
    relations_for_result_section(relations, "computational_chemistry"),
    relations
  )
})

testthat::test_that("each result section chooses only available default columns", {
  available <- c(
    "final_rank",
    "cluster_id",
    "final_score",
    "missing_evidence",
    "unexpected"
  )
  selected <- default_result_columns("candidates", available)
  testthat::expect_equal(
    selected,
    c("final_rank", "cluster_id", "final_score", "missing_evidence")
  )
  testthat::expect_equal(
    default_result_columns("domains", c("one", "two")),
    c("one", "two")
  )
  testthat::expect_equal(
    default_result_columns(
      "final_recommendations",
      c("final_evolutionary_rank", "boss_review_status", "other")
    ),
    c("final_evolutionary_rank", "boss_review_status")
  )
})

testthat::test_that("selected-result SQL quotes columns and remains bounded", {
  query <- build_selected_result_query(
    relation = "candidate_master_results",
    selected_columns = c("cluster_id", "final_score"),
    max_rows = 25
  )
  testthat::expect_match(query, '"cluster_id", "final_score"')
  testthat::expect_match(query, "LIMIT 25$")
  testthat::expect_error(
    build_selected_result_query("candidate_master_results", character()),
    "at least one"
  )
})

testthat::test_that("expression SQL supports context and threshold selection", {
  query <- build_filtered_expression_query(
    relation = "candidate_expression_context_summary",
    selected_columns = c(
      "cluster_id", "organism_part", "gene_id", "expression_positive"
    ),
    available_columns = c(
      "cluster_id", "primary_group_id", "member_accession",
      "species_column", "organism_part", "gene_id", "metadata_status",
      "expression_positive"
    ),
    species = "Zea_mays",
    tissue = "leaf",
    metadata_status = "MAPPED",
    expression_positive = "true",
    search = "N0.HOG0001",
    max_rows = 50
  )
  testthat::expect_match(query, '"species_column" AS VARCHAR\\) = \'Zea_mays\'')
  testthat::expect_match(query, '"organism_part" AS VARCHAR\\) = \'leaf\'')
  testthat::expect_match(query, '"metadata_status" AS VARCHAR\\) = \'MAPPED\'')
  testthat::expect_match(query, '"expression_positive" = TRUE', fixed = TRUE)
  testthat::expect_match(query, "ILIKE '%N0.HOG0001%'", fixed = TRUE)
  testthat::expect_match(query, "LIMIT 50$")
  testthat::expect_error(
    build_filtered_expression_query(
      relation = "candidate_expression_context_summary",
      selected_columns = "expression_positive",
      available_columns = "expression_positive",
      expression_positive = "maybe"
    ),
    "must be empty"
  )
})

testthat::test_that("grant-overview SQL adapts to available evidence fields", {
  query <- build_grant_overview_query(
    relation = "candidate_master_results",
    available = c(
      "grant_aligned_prestructure_pass",
      "grant_aligned_final_pass",
      "three_dimensional_alignment_status"
    )
  )
  testthat::expect_match(query, "prestructure_pass_count")
  testthat::expect_match(query, "structural_assessed_count")
  fallback <- build_grant_overview_query(
    relation = "candidate_evidence",
    available = "representative_id"
  )
  testthat::expect_match(fallback, "0 AS final_pass_count")
})

testthat::test_that("grant overview prefers evolutionary-group decisions", {
  relations <- c(
    "candidate_master_results",
    "final_evolutionary_candidate_prioritisation",
    "prestructure_ranking"
  )
  testthat::expect_equal(
    select_grant_overview_relation(relation_names = relations),
    "final_evolutionary_candidate_prioritisation"
  )
  fallback_query <- build_grant_overview_query(
    relation = "candidate_master_results",
    available = c(
      "final_rank",
      "cluster_id",
      "primary_group_type",
      "primary_group_id",
      "grant_aligned_prestructure_pass",
      "grant_aligned_final_pass"
    )
  )
  testthat::expect_match(fallback_query, "PARTITION BY primary_group_type")
  testthat::expect_match(fallback_query, "_e3_group_row = 1")
})

testthat::test_that("result-section UI exposes checkbox column controls", {
  ui <- paste(
    as.character(result_section_ui("candidate", "candidates")),
    collapse = "\n"
  )
  testthat::expect_match(ui, "Columns to display")
  testthat::expect_match(ui, "candidate-selected_columns")
  testthat::expect_match(ui, "Grant defaults")
  testthat::expect_match(ui, "candidate-download_tsv")
  testthat::expect_match(ui, "candidate-download_excel")
  testthat::expect_match(ui, "Download displayed rows as Excel")
  testthat::expect_error(
    result_section_ui("bad", "missing"),
    "Unknown"
  )
  expression_ui <- paste(
    as.character(result_section_ui("expression", "expression")),
    collapse = "\n"
  )
  testthat::expect_match(expression_ui, "Tissue / organism part", fixed = TRUE)
  testthat::expect_match(expression_ui, "expression-expression_tissue")
  testthat::expect_match(expression_ui, "not measured zero", fixed = TRUE)
  testthat::expect_match(expression_ui, "Median TPM threshold", fixed = TRUE)
  testthat::expect_match(expression_ui, "At least 0.5 TPM", fixed = TRUE)
})

testthat::test_that("recommendation UI documents formulas and weight sensitivity", {
  ui <- paste(
    as.character(result_section_ui("recommendation", "final_recommendations")),
    collapse = "\n"
  )
  testthat::expect_match(
    ui,
    "See the complete ranking formulas",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "How the recorded computational ranking was calculated",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "F = 0.60P + 0.40S",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-ranking_weight_prestructure_discovery",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-ranking_weight_three_dimensional",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-ranking_download_excel",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "non-authoritative",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "does not mean that the underlying biological criterion passed",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "P2Rank 2.5.1 used fpocket-rescore",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "F = 0.06D + 0.21O + 0.12A + 0.21E + 0.22L + 0.18C",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "0% in the recorded production profile",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "Alternative-pocket rescue remained distinct",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "How to interpret the resulting rank",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "Sensitivity analysis: final all-members druggability gate",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-final_druggability_threshold",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-final_druggability_boxplot",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-final_druggability_plot_notice",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "greater than or equal to",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recorded production threshold is 0.50",
    fixed = TRUE
  )
  testthat::expect_match(
    ui,
    "recommendation-final_druggability_download_excel",
    fixed = TRUE
  )
})

testthat::test_that("grant overview UI states both milestones and limitations", {
  ui <- paste(as.character(grant_overview_ui("grant")), collapse = "\n")
  testthat::expect_match(ui, "Milestone 1")
  testthat::expect_match(ui, "Milestone 2")
  testthat::expect_match(ui, "Interpretation boundary")
  testthat::expect_match(ui, "Evolutionary groups assessed")
})
