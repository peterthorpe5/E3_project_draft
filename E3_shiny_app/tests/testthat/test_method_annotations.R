testthat::test_that("scientific tabs have substantive method annotations", {
  expected <- c(
    "Workflow schematic", "Computational recommendations", "Threshold explorer",
    "Independent structural-review shortlist", "Orthology", "Domains",
    "Expression evidence", "Ligandability", "Pocket conservation",
    "3D structures & pockets", "Pocket-aligned sequences", "3D alignment",
    "Computational chemistry", "Provenance and QC"
  )
  entries <- method_annotation_entries()
  testthat::expect_setequal(names(entries), expected)
  for (entry in entries) {
    testthat::expect_gte(nchar(entry$introduction), 70L)
    testthat::expect_true(length(entry$sections) >= 1L)
    testthat::expect_true(all(vapply(
      entry$sections,
      function(section) {
        nzchar(section$heading) && length(section$bullets) >= 1L &&
          all(nzchar(section$bullets))
      },
      logical(1)
    )))
    testthat::expect_gte(nchar(entry$interpretation_boundary), 60L)
  }
})

testthat::test_that("3D annotation records thresholds and the TM-score source", {
  html <- as.character(method_annotation_ui(tab_name = "3D alignment"))
  testthat::expect_match(html, "TM-score at least 0.50", fixed = TRUE)
  testthat::expect_match(html, "centroid distance at most 8 Angstrom", fixed = TRUE)
  testthat::expect_match(html, "within 4 Angstrom", fixed = TRUE)
  testthat::expect_match(html, "chemical-group conservation at least 0.60", fixed = TRUE)
  testthat::expect_match(html, "group support at least 0.75", fixed = TRUE)
  testthat::expect_match(
    html,
    "not a threshold invented for this project",
    fixed = TRUE
  )
  testthat::expect_match(html, TM_SCORE_REFERENCE_URL, fixed = TRUE)
  testthat::expect_match(html, "Xu and Zhang (2010)", fixed = TRUE)
})

testthat::test_that("AlphaFold annotation distinguishes retrieval, QC and scope", {
  html <- as.character(
    method_annotation_ui(tab_name = "3D structures & pockets")
  )
  testthat::expect_match(html, "Canonical monomer mmCIF models", fixed = TRUE)
  testthat::expect_match(html, "No human model was selected", fixed = TRUE)
  testthat::expect_match(html, "0.50 of residues at pLDDT", fixed = TRUE)
  testthat::expect_match(
    html,
    "not a standalone downstream exclusion gate",
    fixed = TRUE
  )
  testthat::expect_match(html, "not a formal production gate", fixed = TRUE)
})

testthat::test_that("mapping annotation distinguishes integrated and component QC", {
  html <- as.character(method_annotation_ui(tab_name = "Ligandability"))
  testthat::expect_match(
    html,
    "integrated pocket-mapping pass used mapping fraction at least 0.95",
    fixed = TRUE
  )
  testthat::expect_match(html, "stricter mapping_qc_pass", fixed = TRUE)
  testthat::expect_match(html, "zero ambiguous mappings", fixed = TRUE)
  testthat::expect_match(
    html,
    "0.70 of all predicted pocket residues",
    fixed = TRUE
  )
  testthat::expect_match(
    html,
    "could not inflate this conservative fraction",
    fixed = TRUE
  )
})

testthat::test_that("invalid method annotations fail defensively", {
  testthat::expect_error(
    method_annotation_entry("Unknown"),
    "No method and threshold annotation"
  )
  testthat::expect_error(
    method_annotation_section("", "value"),
    "require a heading"
  )
  testthat::expect_error(
    method_annotation_reference("Reference", "http://example.org"),
    "HTTPS URL"
  )
})
