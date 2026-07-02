#' Data-source helpers for the E3 Expression Shiny app.
#'
#' These helpers are intentionally small wrappers around DuckDB/duckplyr.  The
#' app must never load the full Expression Atlas data into R memory.  Functions
#' in this file either return lazy duckplyr frames or collect only small vectors
#' of filter choices.

#' Validate the DuckDB database path.
#'
#' Checks that the configured DuckDB file exists before the app starts or before
#' a query is sent to DuckDB.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @return Invisibly returns TRUE when the path is valid.
validate_duckdb_path <- function(duckdb_path) {
  if (!file.exists(duckdb_path)) {
    stop(
      paste0(
        "DuckDB database was not found: ", duckdb_path,
        "\nSet E3_EXPRESSION_DUCKDB or pass --duckdb_path."
      ),
      call. = FALSE
    )
  }

  invisible(TRUE)
}

#' Attach a DuckDB file to the duckplyr default connection.
#'
#' Attaches an existing DuckDB file under a stable alias. Existing aliases are
#' detached where possible, which helps during Shiny reloads and local testing.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @param alias Alias used for the attachment.
#' @return The sanitised alias used for the attachment.
attach_expression_duckdb <- function(duckdb_path, alias = "expr_app") {
  validate_duckdb_path(duckdb_path = duckdb_path)

  safe_alias <- sanitise_duckdb_alias(alias = alias)
  safe_path <- escape_sql_literal(normalizePath(duckdb_path, mustWork = TRUE))

  detach_sql <- paste0("DETACH DATABASE IF EXISTS ", safe_alias)
  attach_sql <- paste0(
    "ATTACH DATABASE '", safe_path, "' AS ", safe_alias,
    " (READ_ONLY)"
  )

  try(duckplyr::db_exec(detach_sql), silent = TRUE)
  duckplyr::db_exec(attach_sql)

  safe_alias
}

#' Build a SELECT query for an attached DuckDB view.
#'
#' Builds a SQL query against the `main` schema of an attached DuckDB file.
#'
#' @param table_name View or table name.
#' @param alias Attached database alias.
#' @return SQL SELECT statement.
build_attached_view_query <- function(table_name, alias = "expr_app") {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  safe_table <- quote_duckdb_identifier(identifier = table_name)

  paste0("SELECT * FROM ", safe_alias, ".main.", safe_table)
}

#' Read an attached DuckDB view using duckplyr.
#'
#' Returns a lazy duckplyr frame. Data are not collected into R memory until
#' `collect()` is called downstream.
#'
#' @param table_name View or table name.
#' @param duckdb_path Path to the DuckDB database.
#' @param alias Attached database alias.
#' @return Lazy duckplyr data frame.
read_expression_view <- function(table_name, duckdb_path, alias = "expr_app") {
  attach_expression_duckdb(duckdb_path = duckdb_path, alias = alias)

  duckplyr::read_sql_duckdb(
    build_attached_view_query(table_name = table_name, alias = alias)
  )
}

#' Read expression with sample metadata.
#'
#' Reads the metadata-aware joined expression view from the DuckDB database.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @return Lazy duckplyr data frame.
get_expression_with_metadata <- function(duckdb_path) {
  read_expression_view(
    table_name = "atlas_expression_with_sample_metadata",
    duckdb_path = duckdb_path
  )
}

#' Read expression sample metadata.
#'
#' Reads the joinable wide sample metadata view.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @return Lazy duckplyr data frame.
get_sample_metadata <- function(duckdb_path) {
  read_expression_view(
    table_name = "atlas_sample_metadata_wide_joinable",
    duckdb_path = duckdb_path
  )
}

#' Read expression table without metadata.
#'
#' Reads the long expression table from the DuckDB database.
#' @param duckdb_path Path to the DuckDB database.
#' @return Lazy duckplyr data frame.
get_expression_long <- function(duckdb_path) {
  read_expression_view(
    table_name = "atlas_expression_long",
    duckdb_path = duckdb_path
  )
}

#' Collect distinct values for a column.
#'
#' Collects distinct non-missing values from a lazy or in-memory table. This is
#' safe only for low-cardinality columns used in filter controls.
#'
#' @param table Lazy or in-memory table.
#' @param column_name Column name to collect.
#' @param limit Maximum number of values to return.
#' @return Character vector of sorted distinct values.
collect_distinct_values <- function(table, column_name, limit = 5000L) {
  column_symbol <- rlang::sym(column_name)

  values <- table |>
    dplyr::filter(!is.na(!!column_symbol)) |>
    dplyr::distinct(!!column_symbol) |>
    dplyr::arrange(!!column_symbol) |>
    head(limit) |>
    dplyr::collect()

  as.character(values[[column_name]])
}

#' Build a WHERE clause for filter-choice SQL.
#'
#' Creates a small SQL WHERE clause for low-cardinality filter-choice queries.
#' Only simple equality filters are supported by design.
#'
#' @param filters Named list of column-value filters.
#' @return SQL WHERE clause beginning with `WHERE`, or an empty string.
build_filter_where_clause <- function(filters = list()) {
  if (length(filters) == 0L) {
    return("")
  }

  non_empty_filters <- filters[!vapply(
    X = filters,
    FUN = function(value) {
      is.null(value) || is.na(value) || identical(value, "") || identical(value, "All")
    },
    FUN.VALUE = logical(1L)
  )]

  if (length(non_empty_filters) == 0L) {
    return("")
  }

  clauses <- vapply(
    X = names(non_empty_filters),
    FUN = function(column_name) {
      paste0(
        quote_duckdb_identifier(column_name),
        " = '",
        escape_sql_literal(as.character(non_empty_filters[[column_name]])),
        "'"
      )
    },
    FUN.VALUE = character(1L)
  )

  paste("WHERE", paste(clauses, collapse = " AND "))
}

#' Build a SQL query for distinct filter values.
#'
#' This avoids collecting filter choices from the large joined expression view.
#' Species, experiments and units are collected from the expression view; sample
#' metadata choices are collected from the much smaller metadata view.
#'
#' @param view_name DuckDB view name.
#' @param column_name Column to collect.
#' @param filters Named list of simple equality filters.
#' @param alias Attached DuckDB alias.
#' @param limit Maximum number of values.
#' @return SQL query string.
build_filter_choice_query <- function(
  view_name,
  column_name,
  filters = list(),
  alias = "expr_app",
  limit = 5000L
) {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  safe_view <- quote_duckdb_identifier(view_name)
  safe_column <- quote_duckdb_identifier(column_name)
  filter_where <- build_filter_where_clause(filters = filters)

  base_conditions <- c(
    paste0(safe_column, " IS NOT NULL"),
    paste0(safe_column, " != ''")
  )

  if (filter_where == "") {
    where_clause <- paste("WHERE", paste(base_conditions, collapse = " AND "))
  } else {
    stripped_where <- sub("^WHERE\\s+", "", filter_where)
    all_conditions <- c(stripped_where, base_conditions)
    where_clause <- paste("WHERE", paste(all_conditions, collapse = " AND "))
  }

  paste0(
    "SELECT DISTINCT ", safe_column, " AS value ",
    "FROM ", safe_alias, ".main.", safe_view, " ",
    where_clause, " ",
    "ORDER BY value ",
    "LIMIT ", as.integer(limit)
  )
}

#' Collect filter values directly from DuckDB.
#'
#' Queries only the appropriate lightweight view and collects a bounded vector
#' for a Shiny filter control. This prevents the app from hanging while it tries
#' to derive choices from the huge expression-plus-metadata join.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @param view_name DuckDB view name.
#' @param column_name Column to collect.
#' @param filters Named list of simple equality filters.
#' @param limit Maximum number of values.
#' @param alias Attached DuckDB alias.
#' @return Character vector of distinct values.
collect_filter_values <- function(
  duckdb_path,
  view_name,
  column_name,
  filters = list(),
  limit = 5000L,
  alias = "expr_app"
) {
  attach_expression_duckdb(duckdb_path = duckdb_path, alias = alias)

  query <- build_filter_choice_query(
    view_name = view_name,
    column_name = column_name,
    filters = filters,
    alias = alias,
    limit = limit
  )

  values <- duckplyr::read_sql_duckdb(query) |>
    dplyr::collect()

  as.character(values$value)
}

#' Collect initial filter choices for app start-up.
#'
#' Species and expression units come from the expression table only, avoiding a
#' metadata join during app initialisation.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @return Named list containing species and expression-unit choices.
collect_initial_filter_choices <- function(duckdb_path) {
  list(
    species = collect_filter_values(
      duckdb_path = duckdb_path,
      view_name = "atlas_expression_long",
      column_name = "species_column"
    ),
    expression_units = collect_filter_values(
      duckdb_path = duckdb_path,
      view_name = "atlas_expression_long",
      column_name = "expression_unit"
    )
  )
}

#' Collect context-dependent filter choices.
#'
#' Experiments are collected from expression. Metadata fields are collected from
#' joinable wide metadata, which is much smaller than the expression table.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @param species_column Selected species, or `All`.
#' @param expression_unit Selected expression unit, or `All`.
#' @return Named list of filter choice vectors.
collect_context_filter_choices <- function(
  duckdb_path,
  species_column = "All",
  expression_unit = "All"
) {
  expression_filters <- list(
    species_column = species_column,
    expression_unit = expression_unit
  )

  metadata_filters <- list(
    species_column = species_column
  )

  list(
    experiments = collect_filter_values(
      duckdb_path = duckdb_path,
      view_name = "atlas_expression_long",
      column_name = "experiment_accession",
      filters = expression_filters
    ),
    organism_parts = collect_filter_values(
      duckdb_path = duckdb_path,
      view_name = "atlas_sample_metadata_wide_joinable",
      column_name = "organism_part",
      filters = metadata_filters
    ),
    developmental_stages = collect_filter_values(
      duckdb_path = duckdb_path,
      view_name = "atlas_sample_metadata_wide_joinable",
      column_name = "developmental_stage",
      filters = metadata_filters
    ),
    conditions = collect_filter_values(
      duckdb_path = duckdb_path,
      view_name = "atlas_sample_metadata_wide_joinable",
      column_name = "condition",
      filters = metadata_filters
    )
  )
}
