#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
downloaded_files_tsv <- get_cli_arg(
  parsed_args = args,
  name = "downloaded_files_tsv",
  default = "analysis/expression_atlas/manifests/atlas_downloaded_files.tsv"
)
output_dir <- get_cli_arg(parsed_args = args, name = "output_dir", default = "analysis/expression_atlas")
force_import <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "force_import", default = "false"),
  default = FALSE
)

manifest_dir <- file.path(output_dir, "manifests")
parquet_dir <- file.path(output_dir, "parquet")
ensure_directory(directory_path = manifest_dir)
ensure_directory(directory_path = parquet_dir)

atlas_files_tbl <- readr::read_tsv(
  file = downloaded_files_tsv,
  show_col_types = FALSE
)

import_summary_tbl <- import_expression_files_to_parquet(
  atlas_files_tbl = atlas_files_tbl,
  parquet_dir = parquet_dir,
  force = force_import
)

import_summary_tsv <- file.path(manifest_dir, "atlas_expression_import_summary.tsv")
readr::write_tsv(x = import_summary_tbl, file = import_summary_tsv)

message("Wrote expression import summary: ", import_summary_tsv)
