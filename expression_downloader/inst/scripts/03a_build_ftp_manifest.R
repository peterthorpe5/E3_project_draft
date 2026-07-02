#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
experiment_manifest_tsv <- get_cli_arg(
  parsed_args = args,
  name = "experiment_manifest_tsv",
  default = "analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv"
)
output_dir <- get_cli_arg(
  parsed_args = args,
  name = "output_dir",
  default = "analysis/expression_atlas"
)

manifest_dir <- file.path(output_dir, "manifests")
download_dir <- file.path(output_dir, "downloads")
ensure_directory(directory_path = manifest_dir)
ensure_directory(directory_path = download_dir)

experiment_tbl <- readr::read_tsv(
  file = experiment_manifest_tsv,
  show_col_types = FALSE
)

if (nrow(experiment_tbl) == 0L) {
  ftp_manifest_tbl <- tibble::tibble(
    experiment_accession = character(),
    species_column = character(),
    file_type = character(),
    file_name = character(),
    url = character(),
    local_path = character()
  )
} else {
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
}

ftp_manifest_tsv <- file.path(manifest_dir, "atlas_ftp_manifest.tsv")
readr::write_tsv(x = ftp_manifest_tbl, file = ftp_manifest_tsv)

message("Wrote FTP manifest: ", ftp_manifest_tsv)
