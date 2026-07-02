test_that("species file is parsed correctly", {
  species_file <- tempfile(fileext = ".txt")
  writeLines(
    text = c(
      "# comment",
      "Arabidopsis_thaliana",
      "Zea mays",
      "",
      "Zea mays  # duplicate"
    ),
    con = species_file
  )

  species_tbl <- read_species_file(species_file = species_file)

  expect_equal(nrow(species_tbl), 2L)
  expect_true("Arabidopsis_thaliana" %in% species_tbl$species_column)
  expect_true("Zea_mays" %in% species_tbl$species_column)
  expect_equal(
    species_tbl$scientific_name[species_tbl$species_column == "Zea_mays"],
    "Zea mays"
  )
})

test_that("species overrides are applied", {
  species_file <- tempfile(fileext = ".txt")
  override_tsv <- tempfile(fileext = ".tsv")

  writeLines(text = "Physcomitrella_patens", con = species_file)
  readr::write_tsv(
    x = tibble::tibble(
      species_column = "Physcomitrella_patens",
      scientific_name = "Physcomitrium patens",
      atlas_species_query = "Physcomitrium patens",
      include = TRUE,
      priority = "plant_priority",
      notes = "updated name"
    ),
    file = override_tsv
  )

  species_tbl <- build_species_registry(
    species_file = species_file,
    override_tsv = override_tsv
  )

  expect_equal(species_tbl$atlas_species_query[[1L]], "Physcomitrium patens")
  expect_equal(species_tbl$notes[[1L]], "updated name")
})
