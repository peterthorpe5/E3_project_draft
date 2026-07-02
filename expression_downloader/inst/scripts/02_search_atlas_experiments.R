#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
species_registry_tsv <- get_cli_arg(
  parsed_args = args,
  name = "species_registry_tsv",
  default = "analysis/expression_atlas/manifests/species_registry.tsv"
)
manual_experiment_tsv <- get_cli_arg(parsed_args = args, name = "manual_experiment_tsv", default = NULL)
output_tsv <- get_cli_arg(
  parsed_args = args,
  name = "output_tsv",
  default = "analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv"
)

atlas_search_terms <- parse_expression_file_types(
  expression_file_types = get_cli_arg(
    parsed_args = args,
    name = "atlas_search_terms",
    default = "RNA-seq,RNA sequencing,transcriptome,baseline"
  )
)
search_backend <- get_cli_arg(
  parsed_args = args,
  name = "search_backend",
  default = "arrayexpress_api"
)
experiment_type_filter <- get_cli_arg(
  parsed_args = args,
  name = "experiment_type_filter",
  default = "rna|sequencing"
)

species_registry_tbl <- readr::read_tsv(
  file = species_registry_tsv,
  show_col_types = FALSE
)

searched_tbl <- search_atlas_from_species_registry(
  species_registry_tbl = species_registry_tbl,
  search_terms = atlas_search_terms,
  search_backend = search_backend,
  experiment_type_filter = experiment_type_filter
)
manual_tbl <- read_manual_experiments(experiment_tsv = manual_experiment_tsv)

experiment_tbl <- dplyr::bind_rows(searched_tbl, manual_tbl) |>
  dplyr::distinct(.data$species_column, .data$experiment_accession, .keep_all = TRUE)

ensure_directory(directory_path = dirname(output_tsv))
readr::write_tsv(x = experiment_tbl, file = output_tsv)

message("Wrote candidate experiment manifest: ", output_tsv)
