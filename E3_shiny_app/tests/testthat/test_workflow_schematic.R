testthat::test_that("workflow schematic covers the complete release path", {
  stages <- workflow_schematic_stages()
  testthat::expect_identical(
    names(stages),
    c(
      "inputs", "discovery", "orthofinder", "orthology", "domains",
      "expression", "shortlist", "ligandability", "alignment", "chemistry",
      "integration", "reporting"
    )
  )
  testthat::expect_true(stages$chemistry$optional)
  testthat::expect_false(any(vapply(
    stages[names(stages) != "chemistry"],
    function(stage) stage$optional,
    logical(1)
  )))
})

testthat::test_that("workflow stage cards validate keys", {
  card <- paste(as.character(workflow_stage_card("ligandability")), collapse = "\n")
  testthat::expect_match(
    card,
    "Structures, pockets and pocket conservation",
    fixed = TRUE
  )
  testthat::expect_match(card, "Output:", fixed = TRUE)
  testthat::expect_error(workflow_stage_card("missing"), "Unknown workflow stage")
  testthat::expect_error(workflow_stage_card(character()), "one non-empty string")
})

testthat::test_that("workflow UI explains branches and interpretation boundary", {
  ui <- paste(as.character(workflow_schematic_ui()), collapse = "\n")
  for (text in c(
    "tantan masking",
    "OrthoFinder 2.5.5",
    "median-TPM threshold of 0.5",
    "P2Rank",
    "US-align and TM-align",
    "hard gates separate from continuous scores",
    "structural, chemical and experimental validation"
  )) {
    testthat::expect_match(ui, text, fixed = TRUE)
  }
  testthat::expect_match(ui, "role=\"figure\"", fixed = TRUE)
  testthat::expect_match(ui, "Stage 09c · optional", fixed = TRUE)
})
