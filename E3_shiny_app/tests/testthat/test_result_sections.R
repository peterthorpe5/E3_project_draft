testthat::test_that("grant-facing relation classification is stable", {
  relations <- c(
    "candidate_master_results",
    "candidate_group_member_sequences",
    "domain_summary",
    "candidate_expression_summary",
    "selected_pockets",
    "pocket_conservation_summary",
    "structural_alignment_summary",
    "resource_metadata"
  )
  testthat::expect_equal(
    relations_for_result_section(relations, "orthology"),
    "candidate_group_member_sequences"
  )
  testthat::expect_equal(
    infer_result_section("candidate_expression_summary"),
    "expression"
  )
  testthat::expect_equal(infer_result_section("unclassified_table"), "other")
  testthat::expect_error(
    relations_for_result_section(relations, "missing"),
    "Unknown"
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

testthat::test_that("result-section UI exposes checkbox column controls", {
  ui <- paste(
    as.character(result_section_ui("candidate", "candidates")),
    collapse = "\n"
  )
  testthat::expect_match(ui, "Columns to display")
  testthat::expect_match(ui, "candidate-selected_columns")
  testthat::expect_match(ui, "Grant defaults")
  testthat::expect_error(
    result_section_ui("bad", "missing"),
    "Unknown"
  )
})

testthat::test_that("grant overview UI states both milestones and limitations", {
  ui <- paste(as.character(grant_overview_ui("grant")), collapse = "\n")
  testthat::expect_match(ui, "Milestone 1")
  testthat::expect_match(ui, "Milestone 2")
  testthat::expect_match(ui, "Interpretation boundary")
})
