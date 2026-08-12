testthat::test_that("recorded ranking weights and relation choice are stable", {
  weights <- recorded_ranking_weights()
  testthat::expect_equal(sum(weights$prestructure), 1)
  testthat::expect_equal(sum(weights$ligandability), 1)
  testthat::expect_equal(sum(weights$structural), 1)
  testthat::expect_equal(sum(weights$final), 1)
  testthat::expect_equal(
    select_ranking_relation(c(
      "candidate_master_results",
      "final_evolutionary_candidate_prioritisation"
    )),
    "final_evolutionary_candidate_prioritisation"
  )
  testthat::expect_equal(select_ranking_relation("unrelated"), "")
})

testthat::test_that("ranking weight validation is defensive", {
  testthat::expect_equal(
    normalise_ranking_weights(c(a = 2 / 3, b = 1 / 3), c("a", "b")),
    c(a = 2 / 3, b = 1 / 3)
  )
  testthat::expect_error(
    normalise_ranking_weights(c(a = 1), c("a", "b")),
    "expected"
  )
  testthat::expect_error(
    normalise_ranking_weights(c(a = 0, b = 0), c("a", "b")),
    "positive"
  )
})

testthat::test_that("reweighting changes only the exploratory order", {
  source <- data.frame(
    final_evolutionary_rank = 1:2,
    evolutionary_group_key = c("HOG:A", "HOG:B"),
    primary_group_id = c("A", "B"),
    lead_cluster_id = c("cluster_a", "cluster_b"),
    lead_discovery_score = c(1, 0),
    lead_orthology_score = c(1, 0.8),
    lead_domain_score = c(0.2, 1),
    lead_expression_score = c(0.2, 1),
    minimum_druggability_score = c(0.4, 0.8),
    mean_pocket_plddt_fraction = c(0.8, 0.8),
    all_assessed_members_pass_mapping = c(TRUE, TRUE),
    predictor_agreement_fraction = c(1, 1),
    pocket_conservation_score = c(0.8, 0.7),
    three_dimensional_pocket_score = c(0.2, 0.9),
    three_dimensional_alignment_status = c(
      "CONSERVED_3D_POCKET_SUPPORTED",
      "CONSERVED_3D_POCKET_SUPPORTED"
    ),
    evidence_completeness_fraction = c(1, 1),
    grant_aligned_base_pass = c(TRUE, TRUE),
    grant_aligned_final_pass = c(TRUE, TRUE),
    prestructure_score = c(0.56, 0.83),
    ligandability_score = c(0.8, 0.9),
    structural_score = c(0.8, 0.81),
    final_score = c(0.656, 0.822)
  )
  original <- source
  ranked <- recompute_exploratory_ranking(data = source)
  testthat::expect_equal(ranked$evolutionary_group_key, c("HOG:B", "HOG:A"))
  testthat::expect_equal(
    ranked$exploratory_ligandability_score,
    c(0.9, 0.8),
    tolerance = 1e-12
  )
  testthat::expect_identical(source, original)

  weights <- recorded_ranking_weights()
  weights$prestructure <- c(
    discovery = 1,
    orthology = 0,
    domain = 0,
    expression = 0
  )
  weights$final <- c(prestructure = 1, structural = 0)
  discovery_only <- recompute_exploratory_ranking(
    data = source,
    weights = weights
  )
  testthat::expect_equal(
    discovery_only$evolutionary_group_key,
    c("HOG:A", "HOG:B")
  )
  source$three_dimensional_alignment_status[[1L]] <- NA_character_
  unavailable <- recompute_exploratory_ranking(
    data = source,
    three_dimensional_weight = 1,
    preserve_gate_tier = FALSE
  )
  unavailable_a <- unavailable[
    unavailable$evolutionary_group_key == "HOG:A",
    ,
    drop = FALSE
  ]
  testthat::expect_equal(
    unavailable_a$exploratory_structural_score,
    0.8,
    tolerance = 1e-12
  )
  testthat::expect_error(
    recompute_exploratory_ranking(
      data = source,
      three_dimensional_weight = 2
    ),
    "between 0 and 1"
  )
})
