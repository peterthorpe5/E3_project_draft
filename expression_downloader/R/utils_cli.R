#' Parse simple command-line arguments.
#'
#' Parses arguments of the form `--name=value` or `--flag`. Values are returned
#' as character strings except bare flags, which are returned as `TRUE`.
#'
#' @param args Character vector of command-line arguments. If `NULL`, arguments
#'   are read from `commandArgs(trailingOnly = TRUE)`.
#' @return A named list of parsed argument values.
parse_cli_args <- function(args = NULL) {
  if (is.null(args)) {
    args <- base::commandArgs(trailingOnly = TRUE)
  }

  parsed_args <- list()

  for (arg in args) {
    if (!stringr::str_starts(string = arg, pattern = "--")) {
      next
    }

    stripped_arg <- stringr::str_remove(string = arg, pattern = "^--")

    if (stringr::str_detect(string = stripped_arg, pattern = "=")) {
      split_arg <- stringr::str_split_fixed(
        string = stripped_arg,
        pattern = "=",
        n = 2L
      )
      parsed_args[[split_arg[[1L]]]] <- split_arg[[2L]]
    } else {
      parsed_args[[stripped_arg]] <- TRUE
    }
  }

  return(parsed_args)
}


#' Retrieve a parsed command-line argument.
#'
#' Returns the named value from a parsed command-line argument list, or a default
#' value when the key is absent.
#'
#' @param parsed_args Named list produced by `parse_cli_args()`.
#' @param name Name of the argument to retrieve.
#' @param default Default value returned when the argument is absent.
#' @return The argument value or `default`.
get_cli_arg <- function(parsed_args, name, default = NULL) {
  if (!name %in% names(parsed_args)) {
    return(default)
  }

  return(parsed_args[[name]])
}


#' Convert a command-line value to logical.
#'
#' @param value Character or logical value to convert.
#' @param default Default logical value for missing input.
#' @return A logical value.
as_cli_logical <- function(value, default = FALSE) {
  if (is.null(value)) {
    return(default)
  }

  if (is.logical(value)) {
    return(value)
  }

  normalised_value <- stringr::str_to_lower(string = value)

  if (normalised_value %in% c("true", "t", "1", "yes", "y")) {
    return(TRUE)
  }

  if (normalised_value %in% c("false", "f", "0", "no", "n")) {
    return(FALSE)
  }

  return(default)
}
