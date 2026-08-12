testthat::test_that("structural alignment columns resolve across granularities", {
  summary_columns <- c(
    "cluster_id",
    "primary_group_id",
    "alignment_status",
    "mean_minimum_tm_score",
    "mean_pocket_overlap_fraction",
    "median_centroid_distance_angstrom"
  )
  resolved <- resolve_structural_alignment_columns(available = summary_columns)
  testthat::expect_identical(
    unname(resolved[["tm_score"]]),
    "mean_minimum_tm_score"
  )
  testthat::expect_true(all(c(
    "mean_minimum_tm_score",
    "mean_pocket_overlap_fraction"
  ) %in% structural_alignment_plot_columns(available = summary_columns)))
  testthat::expect_identical(
    structural_alignment_plot_columns(available = "minimum_tm_score"),
    character()
  )
  testthat::expect_error(
    resolve_structural_alignment_columns(
      available = c("score", NA_character_)
    ),
    "non-missing"
  )
})

testthat::test_that("structural alignment data and plot retain thresholds", {
  data <- data.frame(
    cluster_id = c("cluster_1", "cluster_2"),
    primary_group_id = c("N0.HOG1", "N0.HOG2"),
    alignment_status = c("SUPPORTED", "NOT_SUPPORTED"),
    mean_minimum_tm_score = c(0.9, 0.4),
    mean_pocket_overlap_fraction = c(0.8, 0.3),
    median_centroid_distance_angstrom = c(1.2, 12),
    stringsAsFactors = FALSE
  )
  prepared <- prepare_structural_alignment_plot_data(data = data)
  testthat::expect_equal(prepared$plot_tm_score, c(0.9, 0.4))
  testthat::expect_identical(
    prepared$plot_alignment_identifier,
    c("N0.HOG1", "N0.HOG2")
  )
  testthat::skip_if_not_installed("plotly")
  plot <- build_structural_alignment_plot(data = data)
  testthat::expect_s3_class(plot, "plotly")
  testthat::expect_length(plot$x$layout$shapes, 2L)
  testthat::expect_error(
    prepare_structural_alignment_plot_data(data = data.frame(score = 1)),
    "paired TM-score"
  )
})
