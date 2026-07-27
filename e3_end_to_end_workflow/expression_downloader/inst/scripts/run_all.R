#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
species_file <- get_cli_arg(parsed_args = args, name = "species_file", default = "data/species.txt")
override_tsv <- get_cli_arg(parsed_args = args, name = "override_tsv", default = "data/species_overrides.tsv")
manual_experiment_tsv <- get_cli_arg(parsed_args = args, name = "manual_experiment_tsv", default = NULL)
output_dir <- get_cli_arg(parsed_args = args, name = "output_dir", default = "analysis/expression_atlas")
force_download <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "force_download", default = "false"),
  default = FALSE
)
force_import <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "force_import", default = "false"),
  default = FALSE
)
create_duckdb <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "create_duckdb", default = "true"),
  default = TRUE
)
duckdb_path <- get_cli_arg(parsed_args = args, name = "duckdb_path", default = NULL)
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

search_terms <- parse_expression_file_types(
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

result <- run_expression_atlas_pipeline(
  species_file = species_file,
  output_dir = output_dir,
  override_tsv = override_tsv,
  manual_experiment_tsv = manual_experiment_tsv,
  force_download = force_download,
  force_import = force_import,
  create_duckdb = create_duckdb,
  duckdb_path = duckdb_path,
  require_expression_matrix = require_expression_matrix,
  expression_file_types = expression_file_types,
  search_terms = search_terms,
  search_backend = search_backend,
  experiment_type_filter = experiment_type_filter
)

message("Pipeline finished.")
message("Species registry: ", result$species_registry_tsv)
message("Experiment manifest: ", result$experiment_manifest_tsv)
message("Import summary: ", if (is.null(result$import_summary_tsv)) "not created" else result$import_summary_tsv)
message("Parquet directory: ", if (is.null(result$parquet_dir)) "not created" else result$parquet_dir)
message("DuckDB path: ", if (is.null(result$duckdb_path)) "not created" else result$duckdb_path)
