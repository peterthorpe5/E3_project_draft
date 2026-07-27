#!/usr/bin/env Rscript

# Write a Markdown report documenting the source files and derived tables used
# by the E3 PROTAC source-first Parquet/DuckDB resource.

source(file.path(dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1L]]), mustWork = TRUE)), "script_utils.R"))

repo_dir <- get_repo_dir_from_script()
setwd(repo_dir)

source("R/utils.R")
source("R/data_source_report.R")
source("R/app_config.R")

args <- parse_cli_args(commandArgs(trailingOnly = TRUE))
config <- get_app_config(commandArgs(trailingOnly = TRUE))

derived_dir <- args$derived_dir %||% config$resource_derived_dir
output_path <- args$output %||% file.path(derived_dir, "docs", "FILES_USED.md")
max_rows <- as.integer(args$max_rows %||% "500")

if (is.null(derived_dir) || !nzchar(derived_dir)) {
  stop("A derived directory is required. Pass --derived_dir or set E3_RESOURCE_DERIVED_DIR.", call. = FALSE)
}

message("Writing data-source report")
message("Derived dir: ", derived_dir)
message("Output: ", output_path)

write_data_sources_report(
  derived_dir = derived_dir,
  output_path = output_path,
  max_rows = max_rows
)

message("Done: ", output_path)
