#' Query helpers for the E3 Expression Shiny app.
#'
#' These functions translate Shiny filter values into DuckDB SQL.  They avoid
#' collecting large lazy tables into R and keep all heavy filtering inside
#' DuckDB.  The style is deliberately explicit and defensive because this app
#' is expected to grow as more project tables are added.

#' Check whether a filter value should be ignored.
#'
#' Treats NULL, NA, empty strings, and the UI sentinel value `All` as inactive
#' filters. This keeps SQL WHERE clauses clean and prevents accidental filtering
#' on placeholder values.
#'
#' @param value Candidate filter value.
#' @return TRUE if the value should not be used as a filter.
is_inactive_filter_value <- function(value) {
  if (is.null(value)) {
    return(TRUE)
  }

  if (length(value) == 0L) {
    return(TRUE)
  }

  first_value <- value[[1L]]

  if (is.na(first_value)) {
    return(TRUE)
  }

  first_value <- trimws(as.character(first_value))

  first_value == "" || first_value == "All" || first_value == "Loading..."
}

#' Escape a SQL LIKE pattern.
#'
#' Escapes SQL LIKE wildcards. This helper is retained for ad hoc use and
#' backwards-compatible tests, but production gene searches now use DuckDB's
#' `instr()` function rather than `LIKE ... ESCAPE`. That avoids an escaping
#' incompatibility seen on some DuckDB builds.
#'
#' @param value Search value supplied by the user.
#' @return Escaped SQL LIKE value.
escape_sql_like <- function(value) {
  escaped <- escape_sql_literal(as.character(value))
  escaped <- gsub("\\\\", "\\\\\\\\", escaped)
  escaped <- gsub("%", "\\\\%", escaped, fixed = TRUE)
  escaped <- gsub("_", "\\\\_", escaped, fixed = TRUE)
  escaped
}

#' Build a case-insensitive literal gene-search SQL condition.
#'
#' DuckDB rejected the previous `LIKE ... ESCAPE '\\'` form on some
#' installations because the escape string was interpreted as more than one
#' character. A subsequent `contains()` implementation was also inconsistent
#' across DuckDB/R builds. This helper therefore uses `instr()` on lower-case
#' strings, which performs literal substring matching without SQL wildcards.
#'
#' @param search_value User-supplied gene ID or gene-name fragment.
#' @return SQL condition searching both `gene_id` and `gene_name`.
build_gene_instr_condition <- function(search_value) {
  clean_value <- tolower(trimws(as.character(search_value[[1L]])))
  safe_value <- escape_sql_literal(clean_value)

  paste0(
    "(",
    "instr(lower(coalesce(CAST(gene_id AS VARCHAR), '')), '",
    safe_value,
    "') > 0 OR instr(lower(coalesce(CAST(gene_name AS VARCHAR), '')), '",
    safe_value,
    "') > 0",
    ")"
  )
}

#' Backwards-compatible gene-search condition helper.
#'
#' Older tests and downstream code may still call this name from the previous
#' implementation. It now delegates to `build_gene_instr_condition()`.
#'
#' @param search_value User-supplied gene ID or gene-name fragment.
#' @return SQL condition searching both `gene_id` and `gene_name`.
build_gene_contains_condition <- function(search_value) {
  build_gene_instr_condition(search_value = search_value)
}

#' Build SQL conditions from app filters.
#'
#' Creates safe equality/range/search conditions for the expression-plus-metadata
#' view. The returned vector is joined by `AND` by downstream query builders.
#'
#' @param filters Named list of app filter values.
#' @return Character vector of SQL conditions.
build_expression_filter_conditions <- function(filters = list()) {
  conditions <- character()

  equality_columns <- c(
    "species_column",
    "expression_unit",
    "experiment_accession",
    "organism_part",
    "developmental_stage",
    "condition"
  )

  for (column_name in equality_columns) {
    value <- filters[[column_name]]

    if (!is_inactive_filter_value(value)) {
      conditions <- c(
        conditions,
        paste0(
          quote_duckdb_identifier(column_name),
          " = '",
          escape_sql_literal(as.character(value[[1L]])),
          "'"
        )
      )
    }
  }

  minimum_expression <- filters$minimum_expression

  if (!is.null(minimum_expression) && length(minimum_expression) > 0L) {
    minimum_expression <- suppressWarnings(as.numeric(minimum_expression[[1L]]))

    if (!is.na(minimum_expression)) {
      conditions <- c(
        conditions,
        paste0("expression_value >= ", format(minimum_expression, scientific = FALSE))
      )
    }
  }

  gene_search <- filters$gene_search

  if (!is_inactive_filter_value(gene_search)) {
    conditions <- c(
      conditions,
      build_gene_instr_condition(search_value = gene_search[[1L]])
    )
  }

  conditions
}

#' Build a WHERE clause for expression queries.
#'
#' Converts a named filter list into a SQL WHERE clause. Returns an empty string
#' when no active filters are present.
#'
#' @param filters Named list of app filter values.
#' @return SQL WHERE clause, or an empty string.
build_expression_where_clause <- function(filters = list()) {
  conditions <- build_expression_filter_conditions(filters = filters)

  if (length(conditions) == 0L) {
    return("")
  }

  paste("WHERE", paste(conditions, collapse = " AND "))
}

#' Build a summary SQL query.
#'
#' Counts rows, genes, experiments and expression groups for the current filter
#' selection. DuckDB performs the aggregation; only the small one-row result is
#' collected by R.
#'
#' @param filters Named list of app filter values.
#' @param alias Attached DuckDB alias.
#' @return SQL query string.
build_expression_summary_query <- function(filters = list(), alias = "expr_app") {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  where_clause <- build_expression_where_clause(filters = filters)

  paste(
    "SELECT",
    "COUNT(*) AS rows,",
    "COUNT(DISTINCT gene_id) AS genes,",
    "COUNT(DISTINCT experiment_accession) AS experiments,",
    "COUNT(DISTINCT sample_or_condition) AS groups",
    "FROM", paste0(safe_alias, ".main.atlas_expression_with_sample_metadata"),
    where_clause
  )
}

#' Build a metadata coverage SQL query.
#'
#' Counts how many filtered rows have common metadata fields populated. This is
#' used in the summary tab and keeps the app responsive because the result is a
#' single row.
#'
#' @param filters Named list of app filter values.
#' @param alias Attached DuckDB alias.
#' @return SQL query string.
build_metadata_coverage_query <- function(filters = list(), alias = "expr_app") {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  where_clause <- build_expression_where_clause(filters = filters)

  paste(
    "SELECT",
    "COUNT(*) AS rows,",
    "SUM(CASE WHEN organism_part IS NOT NULL AND organism_part != '' THEN 1 ELSE 0 END) AS rows_with_organism_part,",
    "SUM(CASE WHEN developmental_stage IS NOT NULL AND developmental_stage != '' THEN 1 ELSE 0 END) AS rows_with_developmental_stage,",
    "SUM(CASE WHEN condition IS NOT NULL AND condition != '' THEN 1 ELSE 0 END) AS rows_with_condition",
    "FROM", paste0(safe_alias, ".main.atlas_expression_with_sample_metadata"),
    where_clause
  )
}

#' Build a display-table SQL query.
#'
#' Selects a bounded number of rows for display in the Shiny table. The limit is
#' required; the app should never collect the full expression table.
#'
#' @param filters Named list of app filter values.
#' @param max_rows Maximum number of rows to collect.
#' @param alias Attached DuckDB alias.
#' @return SQL query string.
build_expression_display_query <- function(
  filters = list(),
  max_rows = 1000L,
  alias = "expr_app"
) {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  where_clause <- build_expression_where_clause(filters = filters)

  paste(
    "SELECT",
    "species_column, experiment_accession, gene_id, gene_name,",
    "sample_or_condition, organism_part, developmental_stage, cultivar,",
    "genotype, condition, expression_value, expression_unit",
    "FROM", paste0(safe_alias, ".main.atlas_expression_with_sample_metadata"),
    where_clause,
    "LIMIT", as.integer(max_rows)
  )
}

#' Build a gene lookup SQL query.
#'
#' Searches gene identifiers and names across the expression table for the gene
#' lookup tab. The query is intentionally bounded by `LIMIT`.
#'
#' @param gene_query Gene ID or name search string.
#' @param expression_unit Expression unit to search, usually TPM or FPKM.
#' @param max_rows Maximum number of rows to collect.
#' @param alias Attached DuckDB alias.
#' @return SQL query string.
build_gene_lookup_query <- function(
  gene_query,
  expression_unit = "TPM",
  max_rows = 1000L,
  alias = "expr_app"
) {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  unit_value <- escape_sql_literal(expression_unit)
  gene_condition <- build_gene_instr_condition(search_value = gene_query)

  paste(
    "SELECT",
    "species_column, experiment_accession, gene_id, gene_name,",
    "sample_or_condition, organism_part, developmental_stage, condition,",
    "expression_value, expression_unit",
    "FROM", paste0(safe_alias, ".main.atlas_expression_with_sample_metadata"),
    paste0("WHERE expression_unit = '", unit_value, "'"),
    "AND", gene_condition,
    "LIMIT", as.integer(max_rows)
  )
}

#' Collect a SQL query from an attached DuckDB database.
#'
#' Attaches the database if needed, executes a SQL query through duckplyr, and
#' collects the result. Only use this helper for queries that are expected to
#' return small result sets.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @param query SQL query to execute.
#' @param alias Attached DuckDB alias.
#' @return Collected tibble.
collect_duckdb_query <- function(duckdb_path, query, alias = "expr_app") {
  attach_expression_duckdb(duckdb_path = duckdb_path, alias = alias)

  duckplyr::read_sql_duckdb(query) |>
    dplyr::collect()
}

#' Collect expression summary from DuckDB.
#'
#' @param duckdb_path Path to DuckDB database.
#' @param filters Named list of app filter values.
#' @return One-row tibble of summary values.
collect_expression_summary <- function(duckdb_path, filters = list()) {
  collect_duckdb_query(
    duckdb_path = duckdb_path,
    query = build_expression_summary_query(filters = filters)
  )
}

#' Collect metadata coverage from DuckDB.
#'
#' @param duckdb_path Path to DuckDB database.
#' @param filters Named list of app filter values.
#' @return One-row tibble of metadata coverage values.
collect_metadata_coverage <- function(duckdb_path, filters = list()) {
  collect_duckdb_query(
    duckdb_path = duckdb_path,
    query = build_metadata_coverage_query(filters = filters)
  )
}

#' Collect a bounded expression table from DuckDB.
#'
#' @param duckdb_path Path to DuckDB database.
#' @param filters Named list of app filter values.
#' @param max_rows Maximum number of rows to return.
#' @return Collected tibble.
collect_expression_display_sql <- function(
  duckdb_path,
  filters = list(),
  max_rows = 1000L
) {
  collect_duckdb_query(
    duckdb_path = duckdb_path,
    query = build_expression_display_query(
      filters = filters,
      max_rows = max_rows
    )
  )
}

#' Apply expression filters to an in-memory or lazy expression table.
#'
#' This helper is retained for tests and ad hoc interactive use. The Shiny app
#' itself uses SQL query builders for the heavy production queries.
#'
#' @param expr_table Lazy or in-memory expression table.
#' @param filters Named list of filter values.
#' @return Filtered table.
apply_expression_filters <- function(expr_table, filters) {
  filtered_table <- expr_table

  if (!is_inactive_filter_value(filters$species_column)) {
    filtered_table <- filtered_table |>
      dplyr::filter(.data$species_column == filters$species_column)
  }

  if (!is_inactive_filter_value(filters$expression_unit)) {
    filtered_table <- filtered_table |>
      dplyr::filter(.data$expression_unit == filters$expression_unit)
  }

  if (!is_inactive_filter_value(filters$experiment_accession)) {
    filtered_table <- filtered_table |>
      dplyr::filter(.data$experiment_accession == filters$experiment_accession)
  }

  if (!is_inactive_filter_value(filters$organism_part)) {
    filtered_table <- filtered_table |>
      dplyr::filter(.data$organism_part == filters$organism_part)
  }

  if (!is_inactive_filter_value(filters$developmental_stage)) {
    filtered_table <- filtered_table |>
      dplyr::filter(.data$developmental_stage == filters$developmental_stage)
  }

  if (!is_inactive_filter_value(filters$condition)) {
    filtered_table <- filtered_table |>
      dplyr::filter(.data$condition == filters$condition)
  }

  if (!is.null(filters$minimum_expression) && length(filters$minimum_expression) > 0L) {
    minimum_expression <- suppressWarnings(as.numeric(filters$minimum_expression[[1L]]))

    if (!is.na(minimum_expression)) {
      filtered_table <- filtered_table |>
        dplyr::filter(.data$expression_value >= minimum_expression)
    }
  }

  if (!is_inactive_filter_value(filters$gene_search)) {
    search_value <- paste0("%", trimws(filters$gene_search[[1L]]), "%")

    filtered_table <- filtered_table |>
      dplyr::filter(
        stringr::str_like(.data$gene_id, search_value) |
          stringr::str_like(.data$gene_name, search_value)
      )
  }

  filtered_table
}

#' Summarise a filtered expression table.
#'
#' This in-memory/lazy helper is kept for test coverage and simple interactive
#' checks. The app summary tab uses `collect_expression_summary()` instead.
#'
#' @param filtered_table Filtered lazy or in-memory expression table.
#' @return Collected tibble when possible.
summarise_expression_selection <- function(filtered_table) {
  filtered_table |>
    dplyr::summarise(
      rows = dplyr::n(),
      genes = dplyr::n_distinct(.data$gene_id),
      experiments = dplyr::n_distinct(.data$experiment_accession),
      groups = dplyr::n_distinct(.data$sample_or_condition),
      .groups = "drop"
    ) |>
    dplyr::collect()
}

#' Collect a limited expression table for display.
#'
#' @param filtered_table Filtered lazy expression table.
#' @param max_rows Maximum number of rows to collect.
#' @return Collected tibble.
collect_expression_display <- function(filtered_table, max_rows = 1000L) {
  filtered_table |>
    dplyr::select(
      .data$species_column,
      .data$experiment_accession,
      .data$gene_id,
      .data$gene_name,
      .data$sample_or_condition,
      .data$organism_part,
      .data$developmental_stage,
      .data$cultivar,
      .data$genotype,
      .data$condition,
      .data$expression_value,
      .data$expression_unit
    ) |>
    head(max_rows) |>
    dplyr::collect()
}

#' Build metadata coverage summary.
#'
#' @param filtered_table Filtered lazy expression table.
#' @return Collected tibble with coverage counts.
summarise_metadata_coverage <- function(filtered_table) {
  filtered_table |>
    dplyr::summarise(
      rows = dplyr::n(),
      rows_with_organism_part = sum(!is.na(.data$organism_part)),
      rows_with_developmental_stage = sum(!is.na(.data$developmental_stage)),
      rows_with_condition = sum(!is.na(.data$condition)),
      .groups = "drop"
    ) |>
    dplyr::collect()
}

#' Build a bounded expression-plot SQL query.
#'
#' Selects the columns needed by the visualisation module from the
#' metadata-aware expression view. The caller must provide a gene search term;
#' this prevents the app from collecting broad expression tables for plotting.
#'
#' @param filters Named list of sidebar filter values. A `gene_search` entry is
#'   expected and is treated as active when it is not empty or `All`.
#' @param max_rows Maximum number of rows to collect.
#' @param alias Attached DuckDB alias.
#' @return SQL query string.
build_expression_plot_query <- function(
  filters = list(),
  max_rows = 5000L,
  alias = "expr_app"
) {
  if (is_inactive_filter_value(filters$gene_search)) {
    stop("A gene ID or gene-name search is required for plotting.", call. = FALSE)
  }

  safe_alias <- sanitise_duckdb_alias(alias = alias)
  where_clause <- build_expression_where_clause(filters = filters)

  paste(
    "SELECT",
    "species_column, experiment_accession, gene_id, gene_name,",
    "sample_or_condition, organism_part, developmental_stage, cultivar,",
    "genotype, condition, expression_value, expression_unit",
    "FROM", paste0(safe_alias, ".main.atlas_expression_with_sample_metadata"),
    where_clause,
    "LIMIT", as.integer(max_rows)
  )
}

#' Collect bounded expression rows for plotting.
#'
#' Executes `build_expression_plot_query()` and collects a small table suitable
#' for visualisation. This helper is intentionally separate from the expression
#' table display helper so plot-specific limits and validation can evolve
#' independently.
#'
#' @param duckdb_path Path to the DuckDB database.
#' @param filters Named list of sidebar and plot filter values.
#' @param max_rows Maximum number of rows to collect.
#' @return Collected tibble of expression rows for plotting.
collect_expression_plot_data <- function(
  duckdb_path,
  filters = list(),
  max_rows = 5000L
) {
  collect_duckdb_query(
    duckdb_path = duckdb_path,
    query = build_expression_plot_query(
      filters = filters,
      max_rows = max_rows
    )
  )
}
