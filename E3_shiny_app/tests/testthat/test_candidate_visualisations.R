testthat::test_that("candidate visual relation and column selectors are deterministic", {
  testthat::expect_equal(
    select_candidate_visual_relation(c(
      "candidate_master_results",
      "final_evolutionary_candidate_prioritisation"
    )),
    "final_evolutionary_candidate_prioritisation"
  )
  testthat::expect_null(select_candidate_visual_relation("unrelated"))

  columns <- c(
    "primary_group_id",
    "final_rank",
    "final_score",
    "expression_species_fraction",
    "recommendation_status"
  )
  testthat::expect_equal(
    select_candidate_visual_identifier(columns),
    "primary_group_id"
  )
  testthat::expect_equal(select_candidate_visual_rank(columns), "final_rank")
  testthat::expect_equal(
    select_candidate_visual_rank(c("final_evolutionary_rank", columns)),
    "final_evolutionary_rank"
  )
  testthat::expect_equal(
    unname(candidate_visual_available_metrics(columns)),
    c("final_score", "expression_species_fraction")
  )
  testthat::expect_true(
    "recommendation_status" %in%
      unname(candidate_visual_colour_choices(columns))
  )
  testthat::expect_true(
    all(columns %in% candidate_visual_required_columns(columns))
  )
  testthat::expect_error(
    candidate_visual_required_columns(c("final_score", "structural_score")),
    "stable identifier"
  )
  testthat::expect_error(
    candidate_visual_required_columns(c("primary_group_id", "final_score")),
    "at least two"
  )
})

testthat::test_that("candidate visual queries are quoted and bounded", {
  query <- build_candidate_visual_query(
    relation = "candidate results",
    columns = c("primary_group_id", "final_rank", "final_score"),
    max_rows = 25L
  )
  testthat::expect_match(query, '"candidate results"', fixed = TRUE)
  testthat::expect_match(query, 'ORDER BY "final_rank" NULLS LAST', fixed = TRUE)
  testthat::expect_match(query, "LIMIT 25$", perl = TRUE)
  testthat::expect_error(
    build_candidate_visual_query(
      relation = "candidate results",
      columns = character()
    ),
    "at least one"
  )
  testthat::expect_error(
    build_candidate_visual_query(
      relation = "candidate results",
      columns = "primary_group_id",
      max_rows = 10001L
    ),
    "between 1 and 10000"
  )
})

testthat::test_that("candidate visual preparation preserves stable candidate identity", {
  raw <- tibble::tibble(
    primary_group_id = c("N0.HOG0001", "N0.HOG0002", "N0.HOG0002", ""),
    final_rank = c(1L, 2L, 2L, 3L),
    final_score = c("0.9", "0.8", "0.8", "0.7"),
    expression_species_fraction = c(1, 0.8, 0.8, 0.6)
  )
  prepared <- prepare_candidate_visual_data(
    candidate_tbl = raw,
    identifier_column = "primary_group_id",
    metric_columns = c("final_score", "expression_species_fraction")
  )
  testthat::expect_equal(prepared$.candidate_key, c("N0.HOG0001", "N0.HOG0002"))
  testthat::expect_type(prepared$final_score, "double")
  testthat::expect_equal(
    candidate_visual_metric_label("final_score"),
    "Final integrated score"
  )
  testthat::expect_equal(
    candidate_visual_metric_label("new_metric"),
    "new metric"
  )
  choices <- candidate_visual_display_choices(
    candidate_tbl = prepared,
    rank_column = "final_rank"
  )
  testthat::expect_equal(unname(choices), prepared$.candidate_key)
  testthat::expect_match(names(choices)[[1L]], "Rank 1")
  testthat::expect_error(
    prepare_candidate_visual_data(
      candidate_tbl = raw,
      identifier_column = "missing",
      metric_columns = "final_score"
    ),
    "unavailable"
  )
})

testthat::test_that("candidate landscape is interactive and validates its axes", {
  testthat::skip_if_not_installed("plotly")
  candidates <- tibble::tibble(
    .candidate_key = c("A", "B"),
    final_score = c(0.9, 0.8),
    expression_species_fraction = c(1.0, 0.8),
    recommendation_status = c("PASS", "REVIEW")
  )
  plot <- build_candidate_visual_landscape_plot(
    candidate_tbl = candidates,
    x_column = "expression_species_fraction",
    y_column = "final_score",
    colour_column = "recommendation_status",
    size_column = "final_score",
    source = "candidate_test"
  )
  testthat::expect_s3_class(plot, "plotly")
  testthat::expect_true("plotly_click" %in% plot$x$shinyEvents)
  testthat::expect_error(
    build_candidate_visual_landscape_plot(
      candidate_tbl = candidates,
      x_column = "missing",
      y_column = "final_score"
    ),
    "unavailable"
  )
})

testthat::test_that("candidate identifiers map to exact evidence fields", {
  row <- tibble::tibble(
    evolutionary_group_key = "HOG::N0.HOG0001",
    primary_group_id = "N0.HOG0001",
    cluster_id = "cluster_1",
    lead_cluster_id = "cluster_1"
  )
  identifiers <- candidate_visual_identifiers(candidate_row = row)
  testthat::expect_equal(
    unname(identifiers),
    c("HOG::N0.HOG0001", "N0.HOG0001", "cluster_1", "cluster_1")
  )
  terms <- candidate_visual_match_terms(
    columns = c("group_id", "cluster_id"),
    identifiers = identifiers
  )
  testthat::expect_equal(terms$column, c("group_id", "cluster_id"))
  query <- build_candidate_visual_evidence_query(
    relation = "domain evidence",
    match_terms = terms,
    max_rows = 50L
  )
  testthat::expect_match(query, '"domain evidence"', fixed = TRUE)
  testthat::expect_match(query, "N0.HOG0001", fixed = TRUE)
  testthat::expect_match(query, "LIMIT 50$", perl = TRUE)
  testthat::expect_error(
    build_candidate_visual_evidence_query(
      relation = "domain evidence",
      match_terms = terms[0, ]
    ),
    "no compatible"
  )
})

testthat::test_that("candidate and expression relations use a stable exact link", {
  testthat::expect_equal(
    candidate_expression_link_column(
      candidate_columns = c("primary_group_id", "cluster_id"),
      expression_columns = c("primary_group_id", "gene_id")
    ),
    "primary_group_id"
  )
  testthat::expect_null(candidate_expression_link_column(
    candidate_columns = "evolutionary_group_key",
    expression_columns = "gene_id"
  ))
  contexts <- candidate_expression_context_choices(c(
    "organism_part",
    "developmental_stage",
    "other"
  ))
  testthat::expect_equal(
    unname(contexts),
    c("organism_part", "developmental_stage")
  )
})

testthat::test_that("expression heatmap query keeps units and species explicit", {
  query <- build_candidate_expression_heatmap_query(
    relation = "candidate_expression_context_summary",
    candidate_column = "primary_group_id",
    candidate_ids = c("N0.HOG0001", "N0.HOG0002"),
    context_column = "organism_part",
    expression_unit = "TPM",
    species = "Zea_mays",
    max_cells = 200L
  )
  testthat::expect_match(query, "median_expression", fixed = TRUE)
  testthat::expect_match(
    query,
    "expression_unit AS VARCHAR) = 'TPM'",
    fixed = TRUE
  )
  testthat::expect_match(
    query,
    "species_column AS VARCHAR) = 'Zea_mays'",
    fixed = TRUE
  )
  testthat::expect_match(query, "LIMIT 200$", perl = TRUE)
  testthat::expect_error(
    build_candidate_expression_heatmap_query(
      relation = "candidate_expression_context_summary",
      candidate_column = "primary_group_id",
      candidate_ids = character(),
      context_column = "organism_part",
      expression_unit = "TPM"
    ),
    "between 1 and 25"
  )
  testthat::expect_error(
    build_candidate_expression_heatmap_query(
      relation = "candidate_expression_context_summary",
      candidate_column = "primary_group_id",
      candidate_ids = "N0.HOG0001",
      context_column = "unsupported",
      expression_unit = "TPM"
    ),
    "Unsupported"
  )
})

testthat::test_that("expression heatmap preparation retains unavailable cells", {
  testthat::skip_if_not_installed("ggplot2")
  cells <- tibble::tibble(
    candidate_id = c("A", "B", "A"),
    species = c("Zea_mays", "Zea_mays", "Arabidopsis_thaliana"),
    context_label = c("leaf", "leaf", "root"),
    expression_unit = rep("TPM", 3L),
    median_expression = c(4, NA, 0),
    context_row_count = c(2L, 0L, 1L),
    mapped_member_count = c(1L, 0L, 1L),
    positive_context_fraction = c(1, NA, 0)
  )
  prepared <- prepare_candidate_expression_heatmap(
    expression_tbl = cells,
    log_transform = TRUE
  )
  testthat::expect_equal(nrow(prepared), 2L)
  testthat::expect_equal(prepared$plot_value, c(log2(5), 0))
  testthat::expect_match(prepared$display_context[[1L]], "Zea mays")
  plot <- build_candidate_expression_heatmap_plot(
    expression_tbl = cells,
    log_transform = TRUE
  )
  testthat::expect_s3_class(plot, "ggplot")
  fill_scale <- plot$scales$get_scales("fill")
  testthat::expect_identical(
    fill_scale$palette(c(0, 1)),
    c("#FFFFFF", "#CB181D")
  )
})

testthat::test_that("species and tissue profiles retain exact source rows", {
  query <- build_candidate_expression_profile_query(
    relation = "candidate_expression_context_summary",
    candidate_column = "primary_group_id",
    candidate_id = "N0.HOG0001",
    expression_unit = "TPM",
    species = "Zea_mays",
    max_rows = 300L
  )
  testthat::expect_match(query, "SELECT * FROM", fixed = TRUE)
  testthat::expect_match(query, "N0.HOG0001", fixed = TRUE)
  testthat::expect_match(
    query,
    "expression_unit AS VARCHAR) = 'TPM'",
    fixed = TRUE
  )
  testthat::expect_match(query, "LIMIT 300$", perl = TRUE)
  testthat::expect_error(
    build_candidate_expression_profile_query(
      relation = "candidate_expression_context_summary",
      candidate_column = "primary_group_id",
      candidate_id = "",
      expression_unit = "TPM"
    ),
    "Select one candidate"
  )

  summary_query <- build_candidate_species_tissue_summary_query(
    relation = "candidate_expression_context_summary",
    candidate_column = "primary_group_id",
    candidate_id = "N0.HOG0001",
    expression_unit = "TPM",
    species = "Zea_mays",
    max_tissues = 100L
  )
  testthat::expect_match(summary_query, "GROUP BY species, tissue", fixed = TRUE)
  testthat::expect_match(summary_query, "LIMIT 100$", perl = TRUE)

  exact_rows <- tibble::tibble(
    species_column = c("Zea_mays", "Zea_mays", "Arabidopsis_thaliana"),
    organism_part = c("leaf", "leaf", "root"),
    expression_context = c("leaf", "leaf", "root"),
    expression_value = c(1, 9, 4),
    expression_positive = c(TRUE, TRUE, TRUE),
    member_accession = c("M1", "M2", "M3")
  )
  profile <- prepare_candidate_species_tissue_profile(
    expression_tbl = exact_rows,
    log_transform = TRUE
  )
  maize <- profile[profile$species == "Zea_mays", ]
  testthat::expect_equal(maize$median_expression, 5)
  testthat::expect_equal(maize$minimum_expression, 1)
  testthat::expect_equal(maize$maximum_expression, 9)
  testthat::expect_equal(maize$mapped_member_count, 2L)
  complete <- prepare_candidate_species_tissue_summary(
    summary_tbl = profile[, c(
      "species",
      "tissue",
      "median_expression",
      "minimum_expression",
      "maximum_expression",
      "context_row_count",
      "mapped_member_count",
      "positive_context_fraction"
    )],
    log_transform = FALSE
  )
  testthat::expect_equal(complete$plot_value, complete$median_expression)
  plot <- build_candidate_species_tissue_plot(
    profile_tbl = profile,
    expression_unit = "TPM",
    log_transform = TRUE
  )
  testthat::expect_s3_class(plot, "ggplot")
})

testthat::test_that("volcano helpers require true effect and significance fields", {
  capability <- tibble::tibble(
    relation = "differential_expression",
    effect_column = "log2_fold_change",
    significance_column = "fdr",
    label_column = "gene_id"
  )
  query <- build_candidate_volcano_query(capability = capability, max_rows = 42L)
  testthat::expect_match(query, '"log2_fold_change"', fixed = TRUE)
  testthat::expect_match(query, '"fdr"', fixed = TRUE)
  testthat::expect_match(query, "LIMIT 42$", perl = TRUE)

  rows <- tibble::tibble(
    label = c("higher", "lower", "unchanged", "invalid"),
    effect_size = c(2, -2, 0.1, 3),
    significance_value = c(0.01, 0.02, 0.8, 0)
  )
  prepared <- prepare_candidate_volcano_data(
    differential_tbl = rows,
    effect_threshold = 1,
    significance_threshold = 0.05
  )
  testthat::expect_equal(
    prepared$direction,
    c("Higher", "Lower", "Not significant")
  )
  plot <- build_candidate_volcano_plot(
    differential_tbl = rows,
    effect_threshold = 1,
    significance_threshold = 0.05,
    significance_label = "FDR"
  )
  testthat::expect_s3_class(plot, "ggplot")
  testthat::expect_error(
    prepare_candidate_volcano_data(rows, significance_threshold = 0),
    "within"
  )
})

testthat::test_that("candidate visualisation UI exposes all linked views", {
  ui_text <- paste(
    as.character(candidate_visualisations_ui("visual")),
    collapse = "\n"
  )
  expected <- c(
    "Candidate landscape",
    "Expression heatmap",
    "Species &amp; tissue expression",
    "Volcano eligibility",
    "visual-selected_candidate",
    "visual-candidate_evidence_table",
    "visual-profile_rows_table"
  )
  for (text in expected) {
    testthat::expect_match(ui_text, text, fixed = TRUE)
  }
})

testthat::test_that("visual collectors query a small integrated resource", {
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
    final_rank = c(1L, 2L),
    primary_group_id = c("N0.HOG0001", "N0.HOG0002"),
    cluster_id = c("cluster_1", "cluster_2"),
    final_score = c(0.9, 0.8),
    expression_species_fraction = c(1.0, 0.8)
  )
  expression <- tibble::tibble(
    primary_group_id = c("N0.HOG0001", "N0.HOG0001", "N0.HOG0002"),
    cluster_id = c("cluster_1", "cluster_1", "cluster_2"),
    member_accession = c("M1", "M1", "M2"),
    species_column = c("Zea_mays", "Zea_mays", "Arabidopsis_thaliana"),
    organism_part = c("leaf", "root", "leaf"),
    developmental_stage = c("adult", "adult", "adult"),
    condition = c("control", "control", "control"),
    expression_context = c("leaf", "root", "leaf"),
    experiment_accession = c("E1", "E1", "E2"),
    sample_or_condition = c("S1", "S2", "S3"),
    expression_unit = c("TPM", "TPM", "TPM"),
    expression_value = c(10, 2, 1),
    expression_positive = c(TRUE, TRUE, TRUE),
    gene_id = c("G1", "G1", "G2")
  )
  DBI::dbWriteTable(
    conn = connection,
    name = "final_evolutionary_candidate_prioritisation",
    value = candidates
  )
  DBI::dbWriteTable(
    conn = connection,
    name = "candidate_expression_context_summary",
    value = expression
  )
  DBI::dbDisconnect(conn = connection, shutdown = TRUE)
  source <- resolve_resource_source(resource_duckdb_path = duckdb_path)

  candidate_rows <- collect_candidate_visual_data(
    resource_source = source,
    relation = "final_evolutionary_candidate_prioritisation",
    columns = names(candidates),
    max_rows = 10L
  )
  testthat::expect_equal(nrow(candidate_rows), 2L)
  identifiers <- c(
    primary_group_id = "N0.HOG0001",
    cluster_id = "cluster_1"
  )
  relations <- candidate_visual_evidence_relations(
    resource_source = source,
    identifiers = identifiers
  )
  testthat::expect_true(
    "candidate_expression_context_summary" %in% relations
  )
  evidence <- collect_candidate_visual_evidence(
    resource_source = source,
    relation = "candidate_expression_context_summary",
    identifiers = identifiers,
    max_rows = 10L
  )
  testthat::expect_equal(nrow(evidence), 2L)
  cells <- collect_candidate_expression_heatmap(
    resource_source = source,
    relation = "candidate_expression_context_summary",
    candidate_column = "primary_group_id",
    candidate_ids = "N0.HOG0001",
    context_column = "organism_part",
    expression_unit = "TPM"
  )
  testthat::expect_equal(nrow(cells), 2L)
  exact <- collect_candidate_expression_profile(
    resource_source = source,
    relation = "candidate_expression_context_summary",
    candidate_column = "primary_group_id",
    candidate_id = "N0.HOG0001",
    expression_unit = "TPM"
  )
  testthat::expect_equal(nrow(exact), 2L)
  complete <- collect_candidate_species_tissue_summary(
    resource_source = source,
    relation = "candidate_expression_context_summary",
    candidate_column = "primary_group_id",
    candidate_id = "N0.HOG0001",
    expression_unit = "TPM"
  )
  testthat::expect_equal(nrow(complete), 2L)
  capabilities <- detect_candidate_differential_relations(
    resource_source = source
  )
  testthat::expect_equal(nrow(capabilities), 0L)
})
