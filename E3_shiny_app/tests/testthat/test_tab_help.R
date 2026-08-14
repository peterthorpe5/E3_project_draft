test_that("every R application tab has substantive contextual help", {
  expected <- c(
    "Grant overview", "Workflow schematic", "Glossary",
    "Computational recommendations", "Threshold explorer",
    "Pre-structure ranked HOGs", "Visual explorer", "Candidates", "Orthology",
    "Human HOGs", "Plant & human HOGs", "Seed & HOG explorer", "Domains",
    "Expression evidence", "Ligandability", "Pocket conservation",
    "3D structures & pockets", "Pocket-aligned sequences", "3D alignment",
    "Computational chemistry", "Search", "All results", "Provenance and QC",
    "Files used", "About"
  )
  expect_setequal(names(tab_help_entries()), expected)
  expect_true(all(nchar(tab_help_entries()) >= 80L))
  expect_match(
    as.character(tab_help_ui(tab_name = "Grant overview")),
    "How to use this tab",
    fixed = TRUE
  )
  expect_error(tab_help_text("Unknown"), "No contextual help")
})
