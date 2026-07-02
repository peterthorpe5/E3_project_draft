# Utility functions shared by command-line scripts, data-source helpers, and
# tests. These functions deliberately avoid Shiny-specific behaviour so they can
# be tested cheaply and reused by future modules.

#' Convert a command-line value to logical.
#'
#' Converts common command-line and environment-variable strings to logical
#' values. Missing or empty values return the supplied default. Invalid values
#' fail loudly because silent TRUE/FALSE mistakes can trigger expensive imports
#' or unwanted app behaviour.
#'
#' @param value Value to convert. Usually a character scalar.
#' @param default Logical value returned for NULL, missing, or empty input.
#' @return A single logical value.
as_cli_logical <- function(value, default = FALSE) {
  if (is.null(value) || length(value) == 0L || is.na(value) || value == "") {
    return(default)
  }

  normalised_value <- tolower(trimws(as.character(value)))

  if (normalised_value %in% c("true", "t", "1", "yes", "y")) {
    return(TRUE)
  }

  if (normalised_value %in% c("false", "f", "0", "no", "n")) {
    return(FALSE)
  }

  stop(
    sprintf("Could not convert '%s' to logical", value),
    call. = FALSE
  )
}

#' Escape a SQL string literal.
#'
#' Escapes single quotes in a character value for safe use in internally built
#' SQL strings. This is currently used for file paths passed to DuckDB ATTACH
#' statements.
#'
#' @param value Character value to escape.
#' @return Escaped character value.
escape_sql_literal <- function(value) {
  gsub("'", "''", value, fixed = TRUE)
}

#' Quote a DuckDB identifier.
#'
#' Quotes a schema, table, view, or column name for DuckDB SQL. Embedded double
#' quotes are escaped according to SQL identifier rules.
#'
#' @param identifier Identifier to quote.
#' @return Quoted identifier.
quote_duckdb_identifier <- function(identifier) {
  escaped_identifier <- gsub('"', '""', identifier, fixed = TRUE)
  paste0('"', escaped_identifier, '"')
}

#' Create a DuckDB-safe database alias.
#'
#' Converts arbitrary text to a simple identifier suitable for an attached
#' DuckDB database alias. This lets callers pass human-readable aliases while
#' still producing valid SQL.
#'
#' @param alias Input alias.
#' @return Sanitised alias.
sanitise_duckdb_alias <- function(alias) {
  alias <- gsub("[^A-Za-z0-9_]", "_", alias)

  if (!grepl("^[A-Za-z_]", alias)) {
    alias <- paste0("db_", alias)
  }

  alias
}
