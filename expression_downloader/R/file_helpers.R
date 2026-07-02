#' Check whether a local file exists and is non-empty.
#'
#' Tests whether a local file exists and has at least the requested number of
#' bytes. This is used to avoid re-downloading files when the import is resumed
#' or when new species are added later.
#'
#' @param file_path Path to a local file.
#' @param minimum_bytes Minimum acceptable file size in bytes.
#' @return Logical value indicating whether the file exists and is non-empty.
local_file_is_usable <- function(file_path, minimum_bytes = 1L) {
  if (!file.exists(file_path)) {
    return(FALSE)
  }

  file_size <- file.info(file_path)$size

  if (is.na(file_size)) {
    return(FALSE)
  }

  return(file_size >= minimum_bytes)
}


#' Create a directory if needed.
#'
#' @param directory_path Directory path to create.
#' @return Invisibly returns the input directory path.
ensure_directory <- function(directory_path) {
  fs::dir_create(path = directory_path, recurse = TRUE)
  return(invisible(directory_path))
}


#' Escape a string for use as a DuckDB SQL literal.
#'
#' @param value Character value to escape.
#' @return Escaped SQL literal without surrounding quotation marks.
escape_sql_literal <- function(value) {
  escaped_value <- stringr::str_replace_all(
    string = value,
    pattern = "'",
    replacement = "''"
  )

  return(escaped_value)
}


#' Quote a DuckDB identifier safely.
#'
#' Handles column names containing spaces, punctuation or special characters.
#'
#' @param identifier Column or table identifier.
#' @return A safely quoted DuckDB identifier.
quote_duckdb_identifier <- function(identifier) {
  escaped_identifier <- stringr::str_replace_all(
    string = identifier,
    pattern = "\"",
    replacement = "\"\""
  )

  quoted_identifier <- stringr::str_c("\"", escaped_identifier, "\"")

  return(quoted_identifier)
}


#' Normalise a filesystem path for DuckDB SQL.
#'
#' @param file_path Path to normalise.
#' @param must_work Logical value passed to `normalizePath()`.
#' @return Absolute or normalised path escaped for SQL use.
normalise_sql_path <- function(file_path, must_work = FALSE) {
  normalised_path <- normalizePath(
    path = file_path,
    winslash = "/",
    mustWork = must_work
  )

  escaped_path <- escape_sql_literal(value = normalised_path)

  return(escaped_path)
}
