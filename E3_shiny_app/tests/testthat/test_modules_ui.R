testthat::test_that("application omits the retired raw-expression interface", {
  app_text <- paste(readLines(file.path(repo_dir, "app.R")), collapse = "\n")

  testthat::expect_false(grepl("Raw Expression Atlas filters", app_text, fixed = TRUE))
  testthat::expect_false(grepl("expression_filters_ui", app_text, fixed = TRUE))
  testthat::expect_false(grepl("expression_filters_server", app_text, fixed = TRUE))
  testthat::expect_false(grepl('"Expression summary"', app_text, fixed = TRUE))
  testthat::expect_false(grepl('"Expression table"', app_text, fixed = TRUE))
  testthat::expect_false(grepl('"Visualise expression"', app_text, fixed = TRUE))
  testthat::expect_true(grepl('"Workflow schematic"', app_text, fixed = TRUE))
  testthat::expect_true(grepl("workflow_schematic_ui()", app_text, fixed = TRUE))
})

testthat::test_that("tabular modules expose Excel beside TSV downloads", {
  glossary <- paste(as.character(glossary_ui("glossary")), collapse = "\n")
  testthat::expect_match(glossary, "glossary-download_tsv", fixed = TRUE)
  testthat::expect_match(glossary, "glossary-download_excel", fixed = TRUE)
  testthat::expect_match(glossary, "All sections", fixed = TRUE)
  testthat::expect_match(glossary, "glossary-row_count", fixed = TRUE)

  expression <- paste(
    as.character(result_section_ui("expression", "expression")),
    collapse = "\n"
  )
  testthat::expect_match(expression, "expression-open_expression_heatmap")
  testthat::expect_match(expression, "expression-open_expression_volcano")

  alignment <- paste(
    as.character(result_section_ui("alignment", "structural_alignment")),
    collapse = "\n"
  )
  testthat::expect_match(alignment, "alignment-alignment_plot")
  testthat::expect_match(alignment, "alignment-download_alignment_plot_pdf")
  testthat::expect_match(alignment, "Interactive 3D alignment evidence map")

  visual <- paste(
    as.character(candidate_visualisations_ui("visual")),
    collapse = "\n"
  )
  for (identifier in c(
    "visual-download_candidate_evidence_excel",
    "visual-download_heatmap_cells_excel",
    "visual-download_profile_rows_excel",
    "visual-download_volcano_rows_excel",
    "visual-download_candidate_landscape_pdf",
    "visual-download_expression_heatmap_pdf",
    "visual-download_species_tissue_profile_pdf",
    "visual-download_volcano_plot_pdf"
  )) {
    testthat::expect_match(visual, identifier, fixed = TRUE)
  }

  pocket <- paste(
    as.character(pocket_review_ui("pocket", focus = "structure")),
    collapse = "\n"
  )
  testthat::expect_match(
    pocket,
    "pocket-download_members_excel",
    fixed = TRUE
  )
  alignment_review <- paste(
    as.character(pocket_review_ui("alignment_review", focus = "alignment")),
    collapse = "\n"
  )
  testthat::expect_match(
    alignment_review,
    "alignment_review-download_alignment_fasta",
    fixed = TRUE
  )

  recommendations <- paste(
    as.character(result_section_ui("recommendations", "final_recommendations")),
    collapse = "\n"
  )
  testthat::expect_match(
    recommendations,
    "recommendations-download_final_druggability_boxplot_pdf",
    fixed = TRUE
  )
})

testthat::test_that("summary UI contains value boxes and metadata output", {
  ui_text <- paste(as.character(expression_summary_ui("summary")), collapse = "\n")

  testthat::expect_match(ui_text, "summary-row_count", fixed = TRUE)
  testthat::expect_match(ui_text, "summary-gene_count", fixed = TRUE)
  testthat::expect_match(ui_text, "summary-metadata_coverage", fixed = TRUE)
})

testthat::test_that("expression table UI contains the table output", {
  ui_text <- paste(as.character(expression_table_ui("table")), collapse = "\n")

  testthat::expect_match(ui_text, "table-expression_table", fixed = TRUE)
})

testthat::test_that("gene lookup UI contains query controls and table output", {
  ui_text <- paste(as.character(gene_lookup_ui("lookup")), collapse = "\n")

  testthat::expect_match(ui_text, "lookup-gene_query", fixed = TRUE)
  testthat::expect_match(ui_text, "lookup-unit", fixed = TRUE)
  testthat::expect_match(ui_text, "lookup-gene_table", fixed = TRUE)
})
