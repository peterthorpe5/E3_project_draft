#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
output_dir <- get_cli_arg(parsed_args = args, name = "output_dir", default = "analysis/expression_atlas")
species_column <- get_cli_arg(parsed_args = args, name = "species_column", default = "Arabidopsis_thaliana")
expression_unit <- get_cli_arg(parsed_args = args, name = "expression_unit", default = "TPM")
minimum_expression <- as.numeric(
  get_cli_arg(parsed_args = args, name = "minimum_expression", default = "1")
)

parquet_glob <- file.path(
  output_dir,
  "parquet",
  "atlas_expression_long",
  "**",
  "*.parquet"
)

expression_tbl <- read_expression_parquet_duckplyr(parquet_glob = parquet_glob)

filtered_tbl <- filter_expression_duckplyr(
  expression_tbl = expression_tbl,
  species_column = species_column,
  expression_unit = expression_unit,
  minimum_expression = minimum_expression
) |>
  dplyr::select(
    .data$experiment_accession,
    .data$species_column,
    .data$gene_id,
    .data$gene_name,
    .data$sample_or_condition,
    .data$expression_value,
    .data$expression_unit
  ) |>
  dplyr::slice_head(n = 20L)

print(filtered_tbl)
