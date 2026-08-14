test_that("seed catalogue capability requires inherited seed identifiers", {
  capability <- seed_catalogue_capability(list(
    candidate_evidence = c(
      "cluster_id", "matched_seed_ids_calculated", "seed_protein_names"
    ),
    candidate_group_member_sequences = c(
      "parsed_accession", "raw_identifier", "protein_sequence"
    )
  ))
  expect_true(capability$available)
  expect_identical(capability$mode, "cluster_summary")
  expect_identical(capability$relation, "candidate_evidence")
  expect_identical(capability$seed_id_column, "matched_seed_ids_calculated")
  expect_true(capability$sequence_available)
  authority <- seed_catalogue_capability(list(
    known_e3_seeds = c("seed_id", "seed_metadata_json"),
    candidate_evidence = c("cluster_id", "matched_seed_ids_calculated")
  ))
  expect_identical(authority$mode, "authority")
  expect_identical(authority$relation, "known_e3_seeds")
  expect_false(seed_catalogue_capability(list())$available)
})

test_that("seed catalogue query returns annotations and exact sequences", {
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
    "candidate_evidence",
    data.frame(
      cluster_id = c("cluster_1", "cluster_2"),
      matched_seed_ids_calculated = c("S1;S2", "S1"),
      seed_protein_names = c("Seed one;Seed two", "Seed one"),
      seed_categories = c("U-box", "U-box"),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbWriteTable(
    con,
    "known_e3_seeds",
    data.frame(
      seed_id = c("S1", "S2"),
      source_value = c("S1", "S2"),
      source_column = c("accession", "accession"),
      source_row = c(2L, 3L),
      source_path = c("seeds.tsv", "seeds.tsv"),
      seed_metadata_json = c(
        paste0(
          '{"protein_names":"Seed one","e3_category":"U-box",',
          '"organism":"Arabidopsis thaliana","taxon_id":"3702"}'
        ),
        '{"protein_names":"Seed two","category":"BTB"}'
      ),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbWriteTable(
    con,
    "candidate_group_member_sequences",
    data.frame(
      parsed_accession = c("S1", "OTHER"),
      raw_identifier = c("sp|S1|SEED_ONE", "OTHER"),
      species = c("Arabidopsis_thaliana", "Homo_sapiens"),
      protein_sequence = c("MAAA", "MBBB"),
      is_input_candidate = c(FALSE, FALSE),
      stringsAsFactors = FALSE
    )
  )
  DBI::dbDisconnect(con, shutdown = TRUE)
  con <- NULL
  capability <- seed_catalogue_capability(list(
    known_e3_seeds = c(
      "seed_id", "source_value", "source_column", "source_row", "source_path",
      "seed_metadata_json"
    ),
    candidate_evidence = c(
      "cluster_id", "matched_seed_ids_calculated", "seed_protein_names",
      "seed_categories"
    ),
    candidate_group_member_sequences = c(
      "parsed_accession", "raw_identifier", "species", "protein_sequence",
      "is_input_candidate"
    )
  ))
  expect_identical(capability$mode, "authority")
  result <- collect_resource_query(
    duckdb_path = path,
    query = build_seed_catalogue_query(
      capability = capability,
      max_rows = 10L
    )
  )
  expect_identical(result$seed_id, c("S1", "S2"))
  expect_equal(result$source_cluster_count, c(2, 1))
  expect_identical(result$seed_protein_names, c("Seed one", "Seed two"))
  expect_identical(result$seed_category, c("U-box", "BTB"))
  expect_identical(result$associated_seed_protein_names, c("", ""))
  expect_identical(result$annotation_scope, rep("exact seed authority row", 2L))
  expect_identical(result$protein_sequence, c("MAAA", ""))
  expect_identical(result$sequence_available, c(TRUE, FALSE))
})

test_that("seed catalogue filters pasted terms and validates bounds", {
  data <- data.frame(
    seed_id = c("S1", "S2", "S3"),
    associated_seed_protein_names = c("Alpha", "Beta", "Gamma"),
    protein_sequence = c("MA", "MB", "MC"),
    stringsAsFactors = FALSE
  )
  selected <- filter_seed_catalogue(data = data, query = "S1\nBeta")
  expect_identical(selected$seed_id, c("S1", "S2"))
  expect_identical(filter_seed_catalogue(data = data, query = ""), data)
  expect_error(
    build_seed_catalogue_query(
      capability = list(available = TRUE),
      max_rows = 0L
    ),
    "between 1 and 100000"
  )
})

test_that("seed catalogue UI exposes table and three downloads", {
  ui <- as.character(seed_catalogue_ui("seeds"))
  expect_match(ui, "seeds-seed_table", fixed = TRUE)
  expect_match(ui, "seeds-download_tsv", fixed = TRUE)
  expect_match(ui, "seeds-download_excel", fixed = TRUE)
  expect_match(ui, "seeds-fasta_download_ui", fixed = TRUE)
})
