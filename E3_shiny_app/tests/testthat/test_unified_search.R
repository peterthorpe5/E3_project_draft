test_that("pasted unified-search lists parse and validate", {
  terms <- parse_unified_search_terms("Q9SA03, N0.HOG1\nFB27;Q9SA03")
  expect_identical(terms, c("Q9SA03", "N0.HOG1", "FB27"))
  expect_error(
    parse_unified_search_terms("a,b,c", maximum_terms = 2L),
    "At most 2"
  )
  expect_identical(validate_unified_search_mode("smart"), "smart")
  expect_error(validate_unified_search_mode("regex"), "Unsupported")
})

test_that("unified-search UI exposes list, mode and downloads", {
  ui <- as.character(unified_search_ui("search"))
  expect_match(ui, "search-terms", fixed = TRUE)
  expect_match(ui, "search-mode", fixed = TRUE)
  expect_match(ui, "Search the complete loaded resource", fixed = TRUE)
  expect_match(ui, "search-download_matches_excel", fixed = TRUE)
})

test_that("unified search query uses recognised fields and bounds", {
  query <- build_unified_search_query(
    "candidate_aliases",
    c("primary_group_id", "identifier_value", "score"),
    c("N0.HOG1", "F-box protein"),
    mode = "smart",
    max_rows = 25L
  )
  expect_match(query, "_search_term", fixed = TRUE)
  expect_match(query, "_matched_columns", fixed = TRUE)
  expect_match(query, "primary_group_id", fixed = TRUE)
  expect_match(query, "identifier_value", fixed = TRUE)
  expect_match(query, "LIMIT 25", fixed = TRUE)
  expect_null(build_unified_search_query(
    "unsearchable",
    c("score", "value"),
    "test"
  ))
})

test_that("unified search combines unlike source schemas as character data", {
  skip_if_not_installed("DBI")
  skip_if_not_installed("duckdb")
  skip_if_not_installed("duckplyr")
  path <- tempfile(fileext = ".duckdb")
  con <- DBI::dbConnect(duckdb::duckdb(), dbdir = path, read_only = FALSE)
  on.exit({
    try(DBI::dbDisconnect(con, shutdown = TRUE), silent = TRUE)
    unlink(path)
  }, add = TRUE)
  DBI::dbWriteTable(
    con,
    "ranked",
    data.frame(
      primary_group_id = "N0.HOG1",
      seed_protein_names = "F-box protein",
      final_rank = 7L,
      stringsAsFactors = FALSE
    )
  )
  DBI::dbWriteTable(
    con,
    "aliases",
    data.frame(
      group_id = "N0.HOG1",
      parsed_accession = "Q9SA03",
      score = 0.9,
      stringsAsFactors = FALSE
    )
  )
  DBI::dbDisconnect(con, shutdown = TRUE)
  con <- NULL
  catalogue <- collect_resource_query(
    path,
    build_unified_search_catalogue_query()
  )
  matches <- collect_unified_search_results(
    path,
    catalogue,
    c("N0.HOG1", "F-box protein"),
    mode = "smart"
  )
  expect_true(nrow(matches) >= 3L)
  expect_true(all(vapply(matches, is.character, logical(1L))))
  summary <- summarise_unified_search_results(matches)
  expect_true(all(c("search_term", "relation", "matching_rows") %in% names(summary)))
})
