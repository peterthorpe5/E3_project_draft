#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
output_dir <- get_cli_arg(
  parsed_args = args,
  name = "output_dir",
  default = "analysis/expression_atlas"
)
duckdb_path <- get_cli_arg(
  parsed_args = args,
  name = "duckdb_path",
  default = file.path(output_dir, "e3_expression.duckdb")
)

parquet_dir <- file.path(output_dir, "parquet")
expression_glob <- build_expression_parquet_glob(parquet_dir = parquet_dir)
alias_glob <- file.path(parquet_dir, "gene_identifier_aliases", "**", "*.parquet")
sample_long_glob <- build_sample_metadata_long_parquet_glob(parquet_dir = parquet_dir)
sample_wide_glob <- build_sample_metadata_wide_parquet_glob(parquet_dir = parquet_dir)

alias_glob_for_view <- NULL
if (length(Sys.glob(paths = alias_glob)) > 0L) {
  alias_glob_for_view <- alias_glob
}

sample_long_glob_for_view <- NULL
if (length(Sys.glob(paths = sample_long_glob)) > 0L) {
  sample_long_glob_for_view <- sample_long_glob
}

sample_wide_glob_for_view <- NULL
if (length(Sys.glob(paths = sample_wide_glob)) > 0L) {
  sample_wide_glob_for_view <- sample_wide_glob
}

materialise_duckdb_views_from_parquet(
  duckdb_path = duckdb_path,
  expression_parquet_glob = expression_glob,
  alias_parquet_glob = alias_glob_for_view,
  sample_long_parquet_glob = sample_long_glob_for_view,
  sample_wide_parquet_glob = sample_wide_glob_for_view
)

message("Created DuckDB views in: ", duckdb_path)
