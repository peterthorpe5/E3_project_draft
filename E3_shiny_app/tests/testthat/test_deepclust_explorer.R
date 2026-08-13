testthat::test_that("DeepClust seed parser accepts pasted identifiers", {
  testthat::expect_identical(
    parse_deepclust_seed_queries("Q1, Q2;Q1\nQ3"),
    c("Q1", "Q2", "Q3")
  )
})

testthat::test_that("DeepClust queries preserve scientific labels and filters", {
  metrics <- build_deepclust_metrics_query()
  distribution <- build_deepclust_distribution_query()
  summary <- build_deepclust_summary_query(
    available_columns = deepclust_required_columns(),
    seed_queries = c("Q1", "Q2"),
    match_mode = "all",
    onekp_mode = "strict",
    minimum_strict_onekp_species = 2,
    cluster_query = "onekp_dataset",
    max_rows = 25
  )
  testthat::expect_match(metrics, "strict_onekp_cluster_species_links", fixed = TRUE)
  testthat::expect_match(distribution, "strict_onekp_species_count", fixed = TRUE)
  testthat::expect_match(summary, "strict_onekp_sample_count", fixed = TRUE)
  testthat::expect_match(summary, "list_contains", fixed = TRUE)
  testthat::expect_match(summary, " AND ", fixed = TRUE)
  testthat::expect_match(summary, "LIMIT 25", fixed = TRUE)
})

testthat::test_that("DeepClust UI includes logs, PDF and tabular downloads", {
  ui <- as.character(deepclust_onekp_ui("deepclust"))
  for (identifier in c(
    "deepclust-log_onekp_species_axis",
    "deepclust-log_neighbourhood_count_axis",
    "deepclust-download_coverage_pdf",
    "deepclust-download_summary",
    "deepclust-download_summary_excel"
  )) {
    testthat::expect_match(ui, identifier, fixed = TRUE)
  }
  testthat::expect_match(ui, "does not call them OrthoFinder orthologues", fixed = TRUE)
})
