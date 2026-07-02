#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
species_file <- get_cli_arg(parsed_args = args, name = "species_file", default = "data/species.txt")
override_tsv <- get_cli_arg(parsed_args = args, name = "override_tsv", default = "data/species_overrides.tsv")
output_tsv <- get_cli_arg(parsed_args = args, name = "output_tsv", default = "analysis/expression_atlas/manifests/species_registry.tsv")

species_tbl <- build_species_registry(species_file = species_file, override_tsv = override_tsv)
write_species_registry(species_tbl = species_tbl, output_tsv = output_tsv)

message("Wrote species registry: ", output_tsv)
