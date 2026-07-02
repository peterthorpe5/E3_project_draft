#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
experiment_manifest_tsv <- get_cli_arg(
  parsed_args = args,
  name = "experiment_manifest_tsv",
  default = "analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv"
)
output_dir <- get_cli_arg(parsed_args = args, name = "output_dir", default = "analysis/expression_atlas")
force_download <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "force_download", default = "false"),
  default = FALSE
)
require_expression_matrix <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "require_expression_matrix", default = "true"),
  default = TRUE
)
expression_file_types <- parse_expression_file_types(
  expression_file_types = get_cli_arg(
    parsed_args = args,
    name = "expression_file_types",
    default = "tpms,fpkms"
  )
)

manifest_dir <- file.path(output_dir, "manifests")
download_dir <- file.path(output_dir, "downloads")
ensure_directory(directory_path = manifest_dir)
ensure_directory(directory_path = download_dir)

experiment_tbl <- readr::read_tsv(
  file = experiment_manifest_tsv,
  show_col_types = FALSE
)

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

checked_manifest_tbl <- check_manifest_remotes(manifest_tbl = ftp_manifest_tbl)
checked_manifest_tsv <- file.path(manifest_dir, "atlas_checked_file_manifest.tsv")
readr::write_tsv(x = checked_manifest_tbl, file = checked_manifest_tsv)

expression_availability_tbl <- summary_expression_matrix_availability(
  checked_manifest_tbl = checked_manifest_tbl,
  expression_file_types = expression_file_types
)
expression_availability_tsv <- file.path(
  manifest_dir,
  "atlas_expression_matrix_availability.tsv"
)
readr::write_tsv(x = expression_availability_tbl, file = expression_availability_tsv)

selected_checked_manifest_tbl <- filter_checked_manifest_to_expression_experiments(
  checked_manifest_tbl = checked_manifest_tbl,
  expression_file_types = expression_file_types,
  require_expression_matrix = require_expression_matrix
)
selected_checked_manifest_tsv <- file.path(
  manifest_dir,
  "atlas_selected_checked_file_manifest.tsv"
)
readr::write_tsv(x = selected_checked_manifest_tbl, file = selected_checked_manifest_tsv)

download_log_tbl <- download_checked_manifest(
  checked_manifest_tbl = selected_checked_manifest_tbl,
  force = force_download
)
download_log_tsv <- file.path(manifest_dir, "atlas_download_log.tsv")
readr::write_tsv(x = download_log_tbl, file = download_log_tsv)

downloaded_files_tbl <- selected_checked_manifest_tbl |>
  dplyr::left_join(y = download_log_tbl, by = c("url", "local_path")) |>
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
readr::write_tsv(x = downloaded_files_tbl, file = downloaded_files_tsv)

message("Wrote FTP manifest: ", ftp_manifest_tsv)
message("Wrote checked manifest: ", checked_manifest_tsv)
message("Wrote expression matrix availability: ", expression_availability_tsv)
message("Wrote selected checked manifest: ", selected_checked_manifest_tsv)
message("Wrote download log: ", download_log_tsv)
message("Wrote downloaded files manifest: ", downloaded_files_tsv)
