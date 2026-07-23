# Configuration and command-line parsing helpers. The app is usually launched
# through inst/scripts/run_app.R, but these helpers are also useful during
# testing and scripted deployments.

#' Parse simple command-line arguments.
#'
#' Parses arguments of the form `--name=value`, `--name value`, or bare boolean
#' flags such as `--verbose`. Positional arguments are rejected to avoid
#' accidentally treating a mistyped option as a file path.
#'
#' @param args Character vector of command-line arguments.
#' @return Named list of parsed values.
parse_cli_args <- function(args = commandArgs(trailingOnly = TRUE)) {
  parsed_args <- list()
  index <- 1L

  while (index <= length(args)) {
    current_arg <- args[[index]]

    if (!startsWith(current_arg, "--")) {
      stop(
        sprintf("Unexpected positional argument: %s", current_arg),
        call. = FALSE
      )
    }

    stripped_arg <- sub("^--", "", current_arg)

    if (grepl("=", stripped_arg, fixed = TRUE)) {
      key <- sub("=.*$", "", stripped_arg)
      value <- sub("^[^=]*=", "", stripped_arg)
      parsed_args[[key]] <- value
      index <- index + 1L
      next
    }

    key <- stripped_arg
    next_index <- index + 1L

    if (next_index <= length(args) && !startsWith(args[[next_index]], "--")) {
      parsed_args[[key]] <- args[[next_index]]
      index <- index + 2L
    } else {
      parsed_args[[key]] <- TRUE
      index <- index + 1L
    }
  }

  parsed_args
}

#' Get a default expression DuckDB path.
#'
#' @return Default path used in Pete's current cluster layout.
default_expression_duckdb_path <- function() {
  paste0(
    "/home/pthorpe001/data/2026_E3_protac/analysis/",
    "expression_atlas_ftp_full/e3_expression.duckdb"
  )
}

#' Infer a resource derived directory from config values.
#'
#' @param resource_duckdb_path Path to source-first resource DuckDB.
#' @param explicit_derived_dir Explicit derived directory, if supplied.
#' @return Derived directory path.
resolve_resource_derived_dir <- function(resource_duckdb_path, explicit_derived_dir = NULL) {
  if (!is.null(explicit_derived_dir) && nzchar(explicit_derived_dir)) {
    return(explicit_derived_dir)
  }

  infer_derived_dir(resource_duckdb_path = resource_duckdb_path)
}

#' Get the app configuration.
#'
#' Builds a simple app configuration list from defaults, environment variables,
#' and optional command-line arguments. Command-line values take priority over
#' environment variables, which take priority over hard-coded defaults.
#'
#' The app supports one flexible E3 result source and a separate expression DB:
#' * `resource_duckdb_path`: completed integrated/source-first DuckDB.
#' * `resource_parquet_path`: single candidate master-results Parquet.
#' * `resource_run_dir`: workflow run containing current stage Parquets.
#' * `expression_duckdb_path`: the Expression Atlas DuckDB created by the
#'   separate expression-downloader pipeline.
#'
#' @param args Character vector of command-line arguments.
#' @return Named list containing app configuration values.
get_app_config <- function(args = commandArgs(trailingOnly = TRUE)) {
  parsed_args <- parse_cli_args(args = args)

  expression_duckdb_path <- parsed_args$expression_duckdb_path %||%
    parsed_args$duckdb_path %||%
    Sys.getenv("E3_EXPRESSION_DUCKDB", unset = default_expression_duckdb_path())

  resource_duckdb_path <- parsed_args$resource_duckdb_path %||%
    Sys.getenv("E3_RESOURCE_DUCKDB", unset = "")
  resource_parquet_path <- parsed_args$resource_parquet_path %||%
    Sys.getenv("E3_RESOURCE_PARQUET", unset = "")
  resource_run_dir <- parsed_args$resource_run_dir %||%
    Sys.getenv("E3_RESOURCE_RUN_DIR", unset = "")
  if (
    !nzchar(resource_duckdb_path) &&
      !nzchar(resource_parquet_path) &&
      !nzchar(resource_run_dir) &&
      !is.null(parsed_args$duckdb_path)
  ) {
    resource_duckdb_path <- parsed_args$duckdb_path
  }
  resource_source <- resolve_resource_source(
    resource_duckdb_path = resource_duckdb_path,
    resource_parquet_path = resource_parquet_path,
    resource_run_dir = resource_run_dir
  )

  resource_derived_dir <- resolve_resource_derived_dir(
    resource_duckdb_path = resource_duckdb_path,
    resource_parquet_path = resource_parquet_path,
    resource_run_dir = resource_run_dir,
    resource_source = resource_source,
    explicit_derived_dir = parsed_args$resource_derived_dir %||%
      Sys.getenv("E3_RESOURCE_DERIVED_DIR", unset = "")
  )

  max_table_rows <- as.integer(
    parsed_args$max_table_rows %||%
      Sys.getenv("E3_MAX_TABLE_ROWS", unset = "1000")
  )

  list(
    resource_duckdb_path = resource_duckdb_path,
    resource_derived_dir = resource_derived_dir,
    expression_duckdb_path = expression_duckdb_path,
    # Backwards-compatible field used by older modules/tests.
    duckdb_path = expression_duckdb_path,
    max_table_rows = max_table_rows,
    default_expression_unit = parsed_args$default_expression_unit %||%
      Sys.getenv("E3_DEFAULT_EXPRESSION_UNIT", unset = "TPM"),
    host = parsed_args$host %||%
      Sys.getenv("E3_SHINY_HOST", unset = "127.0.0.1"),
    port = as.integer(
      parsed_args$port %||% Sys.getenv("E3_SHINY_PORT", unset = "0")
    )
  )
}

#' Null coalescing operator.
#'
#' Returns `x` unless it is NULL, otherwise returns `y`. It is kept local to the
#' package so the code does not rely on rlang for this small operation.
#'
#' @param x Primary value.
#' @param y Fallback value.
#' @return `x` or `y`.
`%||%` <- function(x, y) {
  if (is.null(x)) {
    return(y)
  }

  x
}
