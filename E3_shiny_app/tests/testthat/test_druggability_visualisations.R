testthat::test_that("final-gate member distributions retain ranked eligible groups", {
  eligible <- tibble::tibble(
    final_evolutionary_rank = c(2L, 1L, 3L),
    primary_group_id = c("N0.HOG2", "N0.HOG1", "N0.HOG3"),
    lead_cluster_id = c("cluster_2", "cluster_1", "cluster_3")
  )
  scores <- tibble::tibble(
    cluster_id = c("cluster_1", "cluster_1", "cluster_2", "ignored"),
    member_accession = c("P1", "P2", "P3", "P4"),
    species = c("A", "B", "A", "C"),
    pocket_number = c(1L, 1L, 2L, 1L),
    druggability_score = c(0.7, 0.5, 0.325, 0.9)
  )
  prepared <- prepare_final_gate_druggability_data(
    scores = scores,
    eligible_groups = eligible,
    max_groups = 2L
  )
  testthat::expect_true(prepared$truncated)
  testthat::expect_identical(
    prepared$data$eligible_cluster_id,
    c("cluster_1", "cluster_1", "cluster_2")
  )
  testthat::expect_identical(
    unique(prepared$data$group_label),
    c("N0.HOG1 · cluster_1", "N0.HOG2 · cluster_2")
  )
})

testthat::test_that("final-gate box plot includes the selected threshold line", {
  prepared <- tibble::tibble(
    group_label = c("N0.HOG1 · cluster_1", "N0.HOG1 · cluster_1"),
    member_accession = c("P1", "P2"),
    species = c("A", "B"),
    pocket_number = c(1L, 1L),
    druggability_score = c(0.7, 0.5)
  )
  plot <- build_final_gate_druggability_plot(data = prepared, threshold = 0.5)
  testthat::expect_s3_class(plot, "plotly_built")
  testthat::expect_equal(plot$x$layout$shapes[[1L]]$x0, 0.5)
  testthat::expect_error(
    build_final_gate_druggability_plot(data = prepared, threshold = 1.1),
    "from 0 to 1"
  )
})
