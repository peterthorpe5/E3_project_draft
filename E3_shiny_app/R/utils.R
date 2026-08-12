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

#' Build a readable horizontally scrollable scientific data table.
#'
#' The DataTables scroll body keeps the header visible while users scroll
#' vertically. Column classes provide compact numeric cells, wider identifiers
#' and deliberately wrapped narrative text without squeezing all columns into
#' the viewport.
#'
#' @param data Tabular data to display.
#' @param rownames Whether to display row names.
#' @param filter DataTables filter placement.
#' @param options Additional DataTables options overriding the defaults.
#' @param extensions Optional DataTables extensions.
#' @param ... Additional arguments passed to `DT::datatable()`.
#' @return A formatted DataTables htmlwidget.
readable_datatable <- function(
  data,
  rownames = FALSE,
  filter = "top",
  options = list(),
  extensions = NULL,
  ...
) {
  if (!is.data.frame(data)) {
    stop("Readable tables require a data frame.", call. = FALSE)
  }
  if (ncol(data) == 0L || any(is.na(names(data))) || any(!nzchar(names(data)))) {
    stop("Readable tables require named columns.", call. = FALSE)
  }
  narrative <- grep(
    paste(
      "interpretation|definition|description|caution|reason|evidence|",
      "note|message|warning|limitation"
    ),
    names(data),
    ignore.case = TRUE
  ) - 1L
  wide_text <- setdiff(
    grep(
      paste(
        "accession|cluster.*id|group.*id|species|alignment.*tool|",
        "candidate.*list|present|missing|unavailable"
      ),
      names(data),
      ignore.case = TRUE
    ) - 1L,
    narrative
  )
  column_definitions <- list(list(
    targets = "_all",
    className = "e3-cell e3-cell-compact dt-center",
    width = "8rem"
  ))
  if (length(wide_text) > 0L) {
    column_definitions <- c(column_definitions, list(list(
      targets = wide_text,
      className = "e3-cell e3-cell-wide dt-left",
      width = "15rem"
    )))
  }
  if (length(narrative) > 0L) {
    column_definitions <- c(column_definitions, list(list(
      targets = narrative,
      className = "e3-cell e3-cell-narrative dt-left",
      width = "24rem"
    )))
  }
  supplied_definitions <- options$columnDefs
  options$columnDefs <- NULL
  defaults <- list(
    pageLength = 25,
    scrollX = TRUE,
    scrollY = "62vh",
    scrollCollapse = TRUE,
    deferRender = TRUE,
    autoWidth = TRUE
  )
  effective_options <- utils::modifyList(defaults, options)
  effective_options$columnDefs <- c(
    column_definitions,
    if (is.null(supplied_definitions)) list() else supplied_definitions
  )
  widget <- DT::datatable(
    data,
    rownames = rownames,
    filter = filter,
    extensions = extensions,
    options = effective_options,
    ...
  )
  numeric_names <- names(data)[vapply(data, is.numeric, logical(1))]
  scientific_names <- numeric_names[grepl(
    "(^|_)(e_?value|fdr|p_?value|q_?value)(_|$)",
    numeric_names,
    ignore.case = TRUE
  )]
  integer_like <- vapply(
    data[numeric_names],
    function(column) {
      is.integer(column) ||
        all(is.na(column) | (is.finite(column) & column == trunc(column)))
    },
    logical(1)
  )
  integer_names <- numeric_names[
    integer_like &
      grepl(
        paste0(
          "(^|_)(count|index|number|rank)(_|$)|",
          "(^|_)(length|position)$"
        ),
        numeric_names,
        ignore.case = TRUE
      )
  ]
  decimal_names <- setdiff(numeric_names, c(scientific_names, integer_names))
  if (length(decimal_names) > 0L) {
    widget <- DT::formatRound(widget, columns = decimal_names, digits = 3)
  }
  if (length(scientific_names) > 0L) {
    widget <- DT::formatSignif(widget, columns = scientific_names, digits = 3)
  }
  widget
}
