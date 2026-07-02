# Load package source files for tests run from either the repository root or
# tests/testthat. This makes the tests robust to `testthat::test_dir()` and the
# package's helper script.

find_repo_dir <- function(start_dir = getwd()) {
  candidates <- unique(normalizePath(
    path = c(
      start_dir,
      file.path(start_dir, ".."),
      file.path(start_dir, "..", "..")
    ),
    mustWork = FALSE
  ))

  for (candidate in candidates) {
    if (
      file.exists(file.path(candidate, "DESCRIPTION")) &&
        file.exists(file.path(candidate, "R", "utils.R"))
    ) {
      return(normalizePath(candidate, mustWork = TRUE))
    }
  }

  stop("Could not find package repository root for tests.", call. = FALSE)
}

repo_dir <- find_repo_dir()

source(file.path(repo_dir, "inst", "scripts", "script_utils.R"))
source(file.path(repo_dir, "R", "utils.R"))
source(file.path(repo_dir, "R", "data_source_report.R"))
source(file.path(repo_dir, "R", "app_config.R"))
source(file.path(repo_dir, "R", "data_sources.R"))
source(file.path(repo_dir, "R", "query_helpers.R"))
source(file.path(repo_dir, "R", "resource_helpers.R"))
source(file.path(repo_dir, "R", "module_expression_filters.R"))
source(file.path(repo_dir, "R", "module_expression_summary.R"))
source(file.path(repo_dir, "R", "module_expression_table.R"))
source(file.path(repo_dir, "R", "module_gene_lookup.R"))
source(file.path(repo_dir, "R", "module_expression_plots.R"))
source(file.path(repo_dir, "R", "module_resource_overview.R"))
source(file.path(repo_dir, "R", "module_resource_browser.R"))
source(file.path(repo_dir, "R", "module_data_sources.R"))

make_test_expression_tbl <- function() {
  tibble::tibble(
    species_column = c(
      "Zea_mays",
      "Zea_mays",
      "Zea_mays",
      "Arabidopsis_thaliana"
    ),
    expression_unit = c("TPM", "FPKM", "TPM", "TPM"),
    experiment_accession = c("E1", "E1", "E2", "E3"),
    gene_id = c("Zm00001", "Zm00001", "Zm00002", "AT1G01010"),
    gene_name = c("", "", "E3GENE", "NAC001"),
    sample_or_condition = c("g1", "g1", "g2", "g1"),
    organism_part = c("leaf", "leaf", NA_character_, "root"),
    developmental_stage = c("9 day", "9 day", NA_character_, "adult"),
    cultivar = c("B73", "B73", NA_character_, NA_character_),
    genotype = c(
      "wild type genotype",
      "wild type genotype",
      NA_character_,
      NA_character_
    ),
    condition = c("leaf section 1", "leaf section 1", NA_character_, "control"),
    expression_value = c(5, 10, 0.5, 1),
    source_file = paste0("file", 1:4)
  )
}

make_test_duckdb <- function() {
  testthat::skip_if_not_installed("DBI")
  testthat::skip_if_not_installed("duckdb")
  testthat::skip_if_not_installed("duckplyr")

  duckdb_path <- tempfile(fileext = ".duckdb")
  con <- DBI::dbConnect(duckdb::duckdb(), dbdir = duckdb_path, read_only = FALSE)

  DBI::dbWriteTable(con, "atlas_expression_long", make_test_expression_tbl())
  DBI::dbExecute(
    con,
    "CREATE VIEW atlas_expression_with_sample_metadata AS
     SELECT * FROM atlas_expression_long"
  )
  DBI::dbExecute(
    con,
    "CREATE VIEW atlas_sample_metadata_wide_joinable AS
     SELECT DISTINCT
       species_column,
       experiment_accession,
       sample_or_condition,
       organism_part,
       developmental_stage,
       genotype,
       cultivar,
       condition
     FROM atlas_expression_long
     WHERE sample_or_condition IS NOT NULL
       AND sample_or_condition != ''"
  )
  DBI::dbDisconnect(con, shutdown = TRUE)

  duckdb_path
}

make_test_resource_duckdb <- function() {
  testthat::skip_if_not_installed("DBI")
  testthat::skip_if_not_installed("duckdb")
  testthat::skip_if_not_installed("duckplyr")

  duckdb_path <- tempfile(fileext = ".duckdb")
  con <- DBI::dbConnect(duckdb::duckdb(), dbdir = duckdb_path, read_only = FALSE)

  DBI::dbWriteTable(
    con,
    "proteins__proteins",
    tibble::tibble(
      protein_id = c("Q39090", "O80608"),
      species = c("Arabidopsis_thaliana", "Arabidopsis_thaliana"),
      source_file = c("tables/e3_ligases.csv", "tables/e3_ligases.csv")
    )
  )
  DBI::dbWriteTable(
    con,
    "parquet_view_catalog",
    tibble::tibble(
      view_name = "proteins__proteins",
      parquet_file = "parquet/proteins/proteins.parquet",
      status = "created",
      error = ""
    )
  )
  DBI::dbDisconnect(con, shutdown = TRUE)

  duckdb_path
}
