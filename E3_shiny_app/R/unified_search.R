#' Batch-capable, multi-field search across integrated E3 relations.

unified_search_exact_columns <- function() {
  c(
    "accession", "candidate_accession", "candidate_accessions",
    "member_accession", "parsed_accession", "primary_group_id", "group_id",
    "hog_id", "orthogroup_id", "orthofinder_orthogroup_ids", "cluster_id",
    "lead_cluster_id", "representative_id", "internal_id", "gene_id",
    "protein_id", "entry", "parsed_entry", "member_identifier",
    "raw_identifier", "matched_seed_ids_calculated",
    "discovery_matched_seed_ids_calculated", "candidate_accessions_for_cluster"
  )
}

unified_search_text_columns <- function() {
  c(
    "name", "protein_name", "gene_name", "seed_protein_names",
    "discovery_seed_protein_names", "identifier_value", "available_aliases",
    "description", "annotation", "organism", "species", "species_column"
  )
}

#' Parse pasted search terms safely and deterministically.
#'
#' @param value Pasted newline/comma/semicolon/tab-delimited text.
#' @param maximum_terms Maximum accepted unique terms.
#' @return Unique non-empty terms in input order.
parse_unified_search_terms <- function(value, maximum_terms = 200L) {
  maximum_terms <- as.integer(maximum_terms)
  if (length(maximum_terms) != 1L || is.na(maximum_terms) || maximum_terms < 1L) {
    stop("maximum_terms must be a positive integer.", call. = FALSE)
  }
  if (length(value) == 0L || is.na(value[[1L]])) return(character())
  terms <- unlist(strsplit(as.character(value[[1L]]), "[\r\n,;\t]+"))
  terms <- trimws(terms)
  terms <- terms[nzchar(terms)]
  terms <- terms[!duplicated(tolower(terms))]
  if (length(terms) > maximum_terms) {
    stop(
      paste0("At most ", maximum_terms, " unique search terms are accepted."),
      call. = FALSE
    )
  }
  terms
}

validate_unified_search_mode <- function(mode) {
  if (
    length(mode) != 1L ||
      is.na(mode) ||
      !mode %in% c("smart", "exact", "contains")
  ) {
    stop("Unsupported unified-search matching mode.", call. = FALSE)
  }
  mode
}

#' Build a one-call relation/column catalogue query.
#'
#' @param alias Attached database alias.
#' @return DuckDB SQL query.
build_unified_search_catalogue_query <- function(alias = "e3_resource") {
  safe_alias <- escape_sql_literal(sanitise_duckdb_alias(alias))
  paste0(
    "SELECT table_name AS relation_name, column_name FROM ",
    "information_schema.columns WHERE table_catalog = '", safe_alias,
    "' AND table_schema = 'main' ORDER BY table_name, ordinal_position"
  )
}

unified_search_condition <- function(column, term, mode, text_column) {
  field <- paste0("coalesce(CAST(source.", quote_duckdb_identifier(column),
    " AS VARCHAR), '')"
  )
  safe <- escape_sql_literal(tolower(term))
  contains <- paste0("instr(lower(", field, "), '", safe, "') > 0")
  exact <- paste0(
    "(lower(trim(", field, ")) = '", safe,
    "' OR list_contains(string_split(replace(lower(", field,
    "), '; ', ';'), ';'), '", safe, "'))"
  )
  if (mode == "contains" || (mode == "smart" && text_column)) {
    contains
  } else {
    exact
  }
}

#' Build a bounded query for one searchable relation.
#'
#' @param relation Relation name.
#' @param columns Source column names.
#' @param terms Parsed search terms.
#' @param mode Smart, exact or contains.
#' @param max_rows Maximum matching rows for this relation.
#' @param alias Attached database alias.
#' @return DuckDB SQL query or NULL when no fields are searchable.
build_unified_search_query <- function(
  relation,
  columns,
  terms,
  mode = "smart",
  max_rows = 250L,
  alias = "e3_resource"
) {
  mode <- validate_unified_search_mode(mode)
  terms <- parse_unified_search_terms(paste(terms, collapse = "\n"))
  if (length(terms) == 0L) stop("At least one search term is required.", call. = FALSE)
  max_rows <- max(1L, min(10000L, as.integer(max_rows)))
  exact_columns <- intersect(unified_search_exact_columns(), columns)
  text_columns <- intersect(unified_search_text_columns(), columns)
  searchable <- unique(c(exact_columns, text_columns))
  if (length(searchable) == 0L) return(NULL)
  source <- qualified_resource_relation(relation, alias)
  source_fields <- paste(vapply(columns, function(column) {
    paste0(
      "CAST(source.", quote_duckdb_identifier(column), " AS VARCHAR) AS ",
      quote_duckdb_identifier(column)
    )
  }, character(1L)), collapse = ", ")
  queries <- vapply(terms, function(term) {
    conditions <- vapply(searchable, function(column) {
      unified_search_condition(
        column,
        term,
        mode,
        column %in% text_columns
      )
    }, character(1L))
    matched_fields <- vapply(seq_along(searchable), function(index) {
      paste0(
        "CASE WHEN ", conditions[[index]], " THEN '",
        escape_sql_literal(searchable[[index]]), "' ELSE NULL END"
      )
    }, character(1L))
    paste0(
      "SELECT '", escape_sql_literal(term), "' AS _search_term, '",
      escape_sql_literal(relation), "' AS _relation, ",
      "concat_ws(';', ", paste(matched_fields, collapse = ", "),
      ") AS _matched_columns, ", source_fields, " FROM ", source,
      " source WHERE ", paste(conditions, collapse = " OR ")
    )
  }, character(1L))
  paste0(
    "SELECT * FROM (", paste(queries, collapse = " UNION ALL "),
    ") matches LIMIT ", max_rows
  )
}

#' Search every relation containing recognised fields.
#'
#' @param resource_source Flexible E3 resource source.
#' @param catalogue Relation/column catalogue.
#' @param terms Parsed search terms.
#' @param mode Matching mode.
#' @param max_rows_per_relation Per-relation row limit.
#' @param max_total_rows Total output limit.
#' @return Character-stable combined matching rows.
collect_unified_search_results <- function(
  resource_source,
  catalogue,
  terms,
  mode = "smart",
  max_rows_per_relation = 250L,
  max_total_rows = 10000L
) {
  max_total_rows <- max(1L, min(100000L, as.integer(max_total_rows)))
  relations <- unique(as.character(catalogue$relation_name))
  results <- list()
  for (relation in relations) {
    columns <- as.character(
      catalogue$column_name[catalogue$relation_name == relation]
    )
    query <- build_unified_search_query(
      relation,
      columns,
      terms,
      mode,
      max_rows_per_relation
    )
    if (is.null(query)) next
    rows <- tryCatch(
      collect_resource_query(resource_source, query),
      error = function(error) {
        warning(
          paste0("Search skipped relation ", relation, ": ", error$message),
          call. = FALSE
        )
        NULL
      }
    )
    if (!is.null(rows) && nrow(rows) > 0L) results[[relation]] <- rows
  }
  if (length(results) == 0L) {
    return(tibble::tibble(
      `_search_term` = character(),
      `_relation` = character(),
      `_matched_columns` = character()
    ))
  }
  combined <- dplyr::bind_rows(results)
  utils::head(combined, max_total_rows)
}

#' Summarise complete unified-search rows.
#'
#' @param matches Complete result rows.
#' @return Counts by term, relation and matched fields.
summarise_unified_search_results <- function(matches) {
  required <- c("_search_term", "_relation", "_matched_columns")
  missing <- setdiff(required, names(matches))
  if (length(missing) > 0L) {
    stop(
      paste("Search matches are missing:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  if (nrow(matches) == 0L) {
    return(tibble::tibble(
      search_term = character(),
      relation = character(),
      matched_columns = character(),
      matching_rows = integer()
    ))
  }
  summary <- matches |>
    dplyr::count(
      .data$`_search_term`,
      .data$`_relation`,
      .data$`_matched_columns`,
      name = "matching_rows"
    )
  names(summary)[match(required, names(summary))] <- c(
    "search_term",
    "relation",
    "matched_columns"
  )
  dplyr::arrange(summary, .data$search_term, .data$relation, .data$matched_columns)
}
