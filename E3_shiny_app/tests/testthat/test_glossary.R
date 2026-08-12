testthat::test_that("glossary defines requested language and exact thresholds", {
  glossary <- scientific_glossary()
  required <- c(
    "Seed",
    "Normalised seed",
    "Non-seed member",
    "Gate",
    "Gated / gated out",
    "Strict / stringent",
    "Minimum domain-supported assessed-species fraction",
    "Tissue / organism part",
    "NOT_MAPPED"
  )
  testthat::expect_true(all(required %in% glossary$Term))
  recorded <- paste(glossary$`Recorded top-200 rule`, collapse = "\n")
  for (value in c("0.90", "1.00", "0.80", "0.75", "0.50", "8 Å", "4 Å")) {
    testthat::expect_match(recorded, value, fixed = TRUE)
  }
  testthat::expect_match(recorded, "Median TPM at least 0.5", fixed = TRUE)
  testthat::expect_false(grepl("Greater than 0.0 TPM/FPKM", recorded, fixed = TRUE))
  definitions <- paste(glossary$`Plain-language definition`, collapse = "\n")
  testthat::expect_match(definitions, "five-number summary", fixed = TRUE)
  testthat::expect_match(
    definitions,
    "not a list of biological replicates",
    fixed = TRUE
  )
  testthat::expect_gte(nrow(glossary), 360L)
  testthat::expect_true(all(nzchar(glossary$Section)))
  for (term in c(
    "Tantan masking",
    "P2Rank",
    "fpocket-rescore",
    "rescore_2024",
    "PAE",
    "FMOPhore",
    "FrAncestor",
    "final_evolutionary_rank",
    "boss_review_status"
  )) {
    testthat::expect_true(term %in% glossary$Term)
  }
  field <- dplyr::filter(
    glossary,
    .data$Term == "final_evolutionary_rank"
  )
  testthat::expect_identical(
    field$`Type / unit`[[1L]],
    "Integer; blank if ineligible"
  )
  testthat::expect_identical(
    field$Source[[1L]],
    "Final candidate field dictionary v1.0"
  )
})

testthat::test_that("threshold help explains assessed-species denominators", {
  domain_help <- threshold_help_text("domain_species_fraction")
  expression_help <- threshold_help_text("expression_species_fraction")
  testthat::expect_match(domain_help, "usable domain annotation")
  testthat::expect_match(domain_help, "not silently")
  testthat::expect_match(expression_help, "mapped uniquely")
  testthat::expect_match(expression_help, "not treated as measured zero")
  testthat::expect_error(threshold_help_text("unknown"), "Unknown")
})

testthat::test_that("glossary tab and inline definitions are present", {
  app_text <- paste(readLines(file.path(repo_dir, "app.R")), collapse = "\n")
  testthat::expect_match(app_text, "Glossary", fixed = TRUE)
  ui_text <- paste(
    as.character(threshold_explorer_ui(id = "explorer")),
    collapse = "\n"
  )
  testthat::expect_match(ui_text, "usable domain annotation", fixed = TRUE)
})

testthat::test_that("glossary resources are validated defensively", {
  testthat::expect_error(glossary_resource_path("../bad.tsv"), "safe")
  testthat::expect_error(
    load_project_glossary("project_term_glossary.tsv", ""),
    "source label"
  )
})
