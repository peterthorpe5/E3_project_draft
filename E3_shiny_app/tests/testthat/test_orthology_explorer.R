testthat::test_that("OrthoFinder grouping levels resolve explicitly", {
  testthat::expect_identical(
    orthology_relation_name("hierarchical_orthogroup"),
    "hierarchical_membership"
  )
  testthat::expect_identical(
    orthology_relation_name("orthogroup"),
    "orthogroup_membership"
  )
  testthat::expect_identical(
    orthology_record_type("hierarchical_orthogroup"),
    "HIERARCHICAL_ORTHOGROUP"
  )
  testthat::expect_error(orthology_relation_name("cluster"), "Unsupported")
})

testthat::test_that("orthology metric and distribution queries stay bounded", {
  metrics <- build_orthology_metrics_query(
    relation = "hierarchical_membership",
    seed_relation_available = TRUE
  )
  testthat::expect_match(metrics, "COUNT(DISTINCT species)", fixed = TRUE)
  testthat::expect_match(metrics, "seeded_group_count", fixed = TRUE)
  testthat::expect_match(metrics, "all_species_group_count", fixed = TRUE)
  testthat::expect_match(metrics, "largest_group_size", fixed = TRUE)

  distribution <- build_orthology_size_distribution_query(
    relation = "orthogroup_membership"
  )
  testthat::expect_match(distribution, "One species only", fixed = TRUE)
  testthat::expect_match(distribution, "All input species", fixed = TRUE)
  testthat::expect_match(distribution, "group_count", fixed = TRUE)
})

testthat::test_that("group summary requires all selected species safely", {
  query <- build_orthology_group_summary_query(
    relation = "hierarchical_membership",
    required_species = c("species_a", "O'Brien_species"),
    taxonomy_species = "species_a",
    breadth = "all_species",
    seeded_only = TRUE,
    max_rows = 77L
  )
  testthat::expect_match(query, "matched_required_species = 2", fixed = TRUE)
  testthat::expect_match(query, "O''Brien_species", fixed = TRUE)
  testthat::expect_match(query, "species_count = input_species", fixed = TRUE)
  testthat::expect_match(query, "contains_e3_seed_evidence", fixed = TRUE)
  testthat::expect_match(query, "LIMIT 77", fixed = TRUE)
})

testthat::test_that("multi-seed query distinguishes any and all matching", {
  any_query <- build_seed_group_members_query(
    seed_identifiers = c("SEED_A", "SEED_B"),
    group_type = "hierarchical_orthogroup",
    match_mode = "any"
  )
  all_query <- build_seed_group_members_query(
    seed_identifiers = c("SEED_A", "SEED_B"),
    group_type = "hierarchical_orthogroup",
    match_mode = "all",
    species = "species_a"
  )
  testthat::expect_match(any_query, "COUNT(DISTINCT seed_id) >= 1", fixed = TRUE)
  testthat::expect_match(all_query, "COUNT(DISTINCT seed_id) = 2", fixed = TRUE)
  testthat::expect_match(all_query, "members.species IN ('species_a')", fixed = TRUE)
  testthat::expect_match(all_query, "protein_sequence", fixed = TRUE)
  testthat::expect_error(
    build_seed_group_members_query(seed_identifiers = character()),
    "Select at least one"
  )
})

testthat::test_that("seed member summaries retain group and species breadth", {
  members <- tibble::tibble(
    primary_group_type = c("HIERARCHICAL_ORTHOGROUP", "HIERARCHICAL_ORTHOGROUP"),
    primary_group_id = c("HOG1", "HOG1"),
    matched_seed_identifiers = c("SEED_A", "SEED_A"),
    species = c("species_b", "species_a"),
    raw_identifier = c("B1", "A1")
  )
  observed <- summarise_seed_group_members(members)
  testthat::expect_identical(observed$member_count, 2L)
  testthat::expect_identical(observed$species_count, 2L)
  testthat::expect_identical(observed$species_present, "species_a;species_b")
})

testthat::test_that("expanded orthology UIs expose requested controls", {
  orthology_ui <- as.character(orthology_explorer_ui("orthology"))
  seed_ui <- as.character(seed_group_explorer_ui("seed"))
  testthat::expect_match(orthology_ui, "orthology-required_species", fixed = TRUE)
  testthat::expect_match(orthology_ui, "orthology-taxonomy_roles", fixed = TRUE)
  testthat::expect_match(orthology_ui, "orthology-taxonomy_taxa", fixed = TRUE)
  testthat::expect_match(
    orthology_ui,
    "orthology-download_size_distribution_pdf",
    fixed = TRUE
  )
  testthat::expect_match(seed_ui, "seed-seeds", fixed = TRUE)
  testthat::expect_match(seed_ui, "seed-species", fixed = TRUE)
  testthat::expect_match(seed_ui, "seed-download_members_fasta", fixed = TRUE)
})
