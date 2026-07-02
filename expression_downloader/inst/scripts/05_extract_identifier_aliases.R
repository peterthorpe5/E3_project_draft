#!/usr/bin/env Rscript

source(file = file.path("inst", "scripts", "_bootstrap.R"))

args <- parse_cli_args()
e3_tsv <- get_cli_arg(parsed_args = args, name = "e3_tsv", default = NULL)
sqlite_path <- get_cli_arg(parsed_args = args, name = "sqlite_path", default = NULL)
table_name <- get_cli_arg(parsed_args = args, name = "table_name", default = "e3_ligases")
install_sqlite_extension <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "install_sqlite_extension", default = "false"),
  default = FALSE
)
output_dir <- get_cli_arg(parsed_args = args, name = "output_dir", default = "analysis/expression_atlas")
force <- as_cli_logical(
  value = get_cli_arg(parsed_args = args, name = "force", default = "false"),
  default = FALSE
)

manifest_dir <- file.path(output_dir, "manifests")
parquet_dir <- file.path(output_dir, "parquet")
ensure_directory(directory_path = manifest_dir)
ensure_directory(directory_path = parquet_dir)

if (!is.null(e3_tsv)) {
  alias_tbl <- read_e3_aliases_from_tsv(e3_tsv = e3_tsv)
} else if (!is.null(sqlite_path)) {
  alias_tbl <- extract_e3_aliases_from_sqlite_duckdb(
    sqlite_path = sqlite_path,
    table_name = table_name,
    install_extension = install_sqlite_extension
  )
} else {
  stop("Provide either --e3_tsv=/path/e3_ligases.tsv or --sqlite_path=/path/database.sqlite", call. = FALSE)
}

output_tsv <- file.path(manifest_dir, "gene_identifier_aliases.tsv")
output_parquet <- file.path(parquet_dir, "gene_identifier_aliases", "gene_identifier_aliases.parquet")

write_identifier_aliases(
  alias_tbl = alias_tbl,
  output_tsv = output_tsv,
  output_parquet = output_parquet,
  force = force
)

message("Wrote identifier aliases TSV: ", output_tsv)
message("Wrote identifier aliases Parquet: ", output_parquet)
