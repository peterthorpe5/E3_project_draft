#' Run the full Expression Atlas import pipeline.
#'
#' Builds the species registry, searches Expression Atlas or reads manual
#' experiments, builds and checks FTP manifests, downloads missing non-empty
#' files, imports TPM/FPKM matrices to long Parquet, and creates optional DuckDB
#' views for lazy duckplyr querying.
#'
#' @param species_file Path to one-species-per-line species file.
#' @param output_dir Output directory for manifests, downloads and Parquet data.
#' @param override_tsv Optional species override TSV.
#' @param manual_experiment_tsv Optional manually curated experiment TSV.
#' @param force_download Logical value controlling whether to re-download files.
#' @param force_import Logical value controlling whether to rebuild Parquet files.
#' @param create_duckdb Logical value controlling whether to create DuckDB views.
#' @param duckdb_path Optional DuckDB database path for view creation.
#' @param require_expression_matrix Logical value controlling whether to keep
#'   only experiments with downloadable normalised expression matrices.
#' @param expression_file_types File types that count as expression matrices.
#' @return A named list of output paths and summary tables.
run_expression_atlas_pipeline <- function(
  species_file,
  output_dir = "analysis/expression_atlas",
  override_tsv = NULL,
  manual_experiment_tsv = NULL,
  force_download = FALSE,
  force_import = FALSE,
  create_duckdb = TRUE,
  duckdb_path = NULL,
  require_expression_matrix = TRUE,
  expression_file_types = c("tpms", "fpkms"),
  search_terms = c("RNA-seq", "RNA sequencing", "transcriptome", "baseline"),
  search_backend = "arrayexpress_api",
  experiment_type_filter = "rna|sequencing"
) {
  manifest_dir <- file.path(output_dir, "manifests")
  download_dir <- file.path(output_dir, "downloads")
  parquet_dir <- file.path(output_dir, "parquet")

  ensure_directory(directory_path = output_dir)
  ensure_directory(directory_path = manifest_dir)
  ensure_directory(directory_path = download_dir)
  ensure_directory(directory_path = parquet_dir)

  species_registry_tbl <- build_species_registry(
    species_file = species_file,
    override_tsv = override_tsv
  )

  species_registry_tsv <- file.path(manifest_dir, "species_registry.tsv")
  write_species_registry(
    species_tbl = species_registry_tbl,
    output_tsv = species_registry_tsv
  )

  message("Starting Expression Atlas discovery")
  searched_experiment_tbl <- search_atlas_from_species_registry(
    species_registry_tbl = species_registry_tbl,
    search_terms = search_terms,
    search_backend = search_backend,
    experiment_type_filter = experiment_type_filter
  )
  message("Expression Atlas discovery returned ", nrow(searched_experiment_tbl), " candidate rows")

  manual_experiment_tbl <- read_manual_experiments(
    experiment_tsv = manual_experiment_tsv
  )

  experiment_tbl <- dplyr::bind_rows(
    searched_experiment_tbl,
    manual_experiment_tbl
  ) |>
    dplyr::distinct(
      .data$species_column,
      .data$experiment_accession,
      .keep_all = TRUE
    )

  experiment_manifest_tsv <- file.path(
    manifest_dir,
    "atlas_candidate_experiments.tsv"
  )

  readr::write_tsv(
    x = experiment_tbl,
    file = experiment_manifest_tsv
  )

  if (nrow(experiment_tbl) == 0L) {
    warning(
      "No Expression Atlas experiments were kept after searching and filtering. Check atlas_candidate_experiments.tsv, species_registry.tsv, and consider using --experiment_type_filter=all or a manual_experiment_tsv.",
      call. = FALSE
    )

    return(
      list(
        species_registry_tsv = species_registry_tsv,
        experiment_manifest_tsv = experiment_manifest_tsv,
        output_dir = output_dir
      )
    )
  }

  ftp_manifest_tbl <- purrr::pmap_dfr(
    .l = list(
      experiment_accession = experiment_tbl$experiment_accession,
      species_column = experiment_tbl$species_column
    ),
    .f = function(experiment_accession, species_column) {
      build_atlas_ftp_manifest(
        experiment_accession = experiment_accession,
        species_column = species_column
      )
    }
  ) |>
    dplyr::mutate(
      local_path = file.path(
        download_dir,
        .data$species_column,
        .data$experiment_accession,
        .data$file_name
      )
    )

  ftp_manifest_tsv <- file.path(manifest_dir, "atlas_ftp_manifest.tsv")
  readr::write_tsv(x = ftp_manifest_tbl, file = ftp_manifest_tsv)

  message("Checking remote availability for ", nrow(ftp_manifest_tbl), " candidate Atlas files")
  checked_manifest_tbl <- check_manifest_remotes(manifest_tbl = ftp_manifest_tbl)
  message("Remote checking complete: ", sum(checked_manifest_tbl$remote_exists & checked_manifest_tbl$remote_non_empty), " available files")

  checked_manifest_tsv <- file.path(
    manifest_dir,
    "atlas_checked_file_manifest.tsv"
  )

  readr::write_tsv(
    x = checked_manifest_tbl,
    file = checked_manifest_tsv
  )

  expression_availability_tbl <- summary_expression_matrix_availability(
    checked_manifest_tbl = checked_manifest_tbl,
    expression_file_types = expression_file_types
  )

  expression_availability_tsv <- file.path(
    manifest_dir,
    "atlas_expression_matrix_availability.tsv"
  )

  readr::write_tsv(
    x = expression_availability_tbl,
    file = expression_availability_tsv
  )

  selected_checked_manifest_tbl <- filter_checked_manifest_to_expression_experiments(
    checked_manifest_tbl = checked_manifest_tbl,
    expression_file_types = expression_file_types,
    require_expression_matrix = require_expression_matrix
  )

  selected_checked_manifest_tsv <- file.path(
    manifest_dir,
    "atlas_selected_checked_file_manifest.tsv"
  )

  readr::write_tsv(
    x = selected_checked_manifest_tbl,
    file = selected_checked_manifest_tsv
  )

  message("Selected ", nrow(selected_checked_manifest_tbl), " files from experiments with expression matrices")

  download_log_tbl <- download_checked_manifest(
    checked_manifest_tbl = selected_checked_manifest_tbl,
    force = force_download
  )

  download_log_tsv <- file.path(manifest_dir, "atlas_download_log.tsv")

  readr::write_tsv(
    x = download_log_tbl,
    file = download_log_tsv
  )

  downloaded_files_tbl <- selected_checked_manifest_tbl |>
    dplyr::left_join(
      y = download_log_tbl,
      by = c("url", "local_path")
    ) |>
    dplyr::filter(.data$success) |>
    dplyr::select(
      .data$experiment_accession,
      .data$species_column,
      .data$file_type,
      .data$file_name,
      .data$url,
      .data$local_path,
      .data$local_bytes
    ) |>
    dplyr::distinct()

  downloaded_files_tsv <- file.path(manifest_dir, "atlas_downloaded_files.tsv")

  readr::write_tsv(
    x = downloaded_files_tbl,
    file = downloaded_files_tsv
  )

  message("Downloaded files available for import: ", nrow(downloaded_files_tbl))

  import_summary_tbl <- import_expression_files_to_parquet(
    atlas_files_tbl = downloaded_files_tbl,
    parquet_dir = parquet_dir,
    force = force_import
  )

  import_summary_tsv <- file.path(
    manifest_dir,
    "atlas_expression_import_summary.tsv"
  )

  readr::write_tsv(
    x = import_summary_tbl,
    file = import_summary_tsv
  )

  duckdb_result <- NULL

  if (create_duckdb) {
    if (is.null(duckdb_path)) {
      duckdb_path <- file.path(output_dir, "e3_expression.duckdb")
    }

    expression_parquet_glob <- file.path(
      parquet_dir,
      "atlas_expression_long",
      "**",
      "*.parquet"
    )

    duckdb_result <- tryCatch(
      expr = {
        materialise_duckdb_views_from_parquet(
          duckdb_path = duckdb_path,
          expression_parquet_glob = expression_parquet_glob
        )
        duckdb_path
      },
      error = function(error) {
        warning(
          stringr::str_c(
            "DuckDB view creation failed: ",
            conditionMessage(error)
          ),
          call. = FALSE
        )
        NULL
      }
    )
  }

  return(
    list(
      species_registry_tsv = species_registry_tsv,
      experiment_manifest_tsv = experiment_manifest_tsv,
      ftp_manifest_tsv = ftp_manifest_tsv,
      checked_manifest_tsv = checked_manifest_tsv,
      expression_availability_tsv = expression_availability_tsv,
      selected_checked_manifest_tsv = selected_checked_manifest_tsv,
      download_log_tsv = download_log_tsv,
      downloaded_files_tsv = downloaded_files_tsv,
      import_summary_tsv = import_summary_tsv,
      parquet_dir = parquet_dir,
      duckdb_path = duckdb_result,
      species_registry = species_registry_tbl,
      experiments = experiment_tbl,
      import_summary = import_summary_tbl
    )
  )
}
