#' Resource-wide enriched root-HOG results.

enriched_hog_overview_key <- function() "__enriched_hog_overview__"

enriched_hog_members_key <- function() "__enriched_hog_members__"

enriched_hog_result_labels <- function() {
  stats::setNames(
    c(enriched_hog_overview_key(), enriched_hog_members_key()),
    c(
      "Enriched HOG overview (joined across the resource)",
      "Enriched HOG member detail (joined across the resource)"
    )
  )
}

#' Collect column names for HOG-linked relations only.
#'
#' @param resource_source Flexible result source.
#' @param relations Available relation names.
#' @return Named list of relation column vectors.
collect_enriched_hog_relation_columns <- function(resource_source, relations) {
  relevant <- intersect(
    unique(c("hierarchical_membership", human_hog_ranking_relations())),
    relations
  )
  result <- list()
  for (relation in relevant) {
    metadata <- collect_resource_columns(
      duckdb_path = resource_source,
      view_name = relation
    )
    result[[relation]] <- as.character(metadata$column_name)
  }
  result
}

#' Validate a virtual enriched-HOG result key.
#'
#' @param result Result key.
#' @return Validated result key.
validate_enriched_hog_result <- function(result) {
  available <- unname(enriched_hog_result_labels())
  if (
    length(result) != 1L ||
      is.na(result) ||
      !result %in% available
  ) {
    stop("Unsupported enriched HOG result.", call. = FALSE)
  }
  result
}

enriched_hog_overview_columns <- function() {
  c(
    "hog_id",
    "hog_prestructure_rank",
    "hog_poststructure_rank",
    "human_hog_representatives",
    "arabidopsis_hog_representatives",
    "human_hog_accessions",
    "human_hog_entries",
    "human_hog_raw_identifiers",
    "arabidopsis_hog_accessions",
    "arabidopsis_hog_entries",
    "arabidopsis_hog_raw_identifiers",
    "hog_member_count",
    "hog_species_count",
    "hog_human_member_count",
    "hog_arabidopsis_member_count",
    "hog_target_plant_member_count",
    "hog_target_plant_species_count",
    "hog_species_present",
    "hog_target_plant_species_present",
    "hog_orthogroup_ids",
    "hog_gene_tree_parent_clades",
    "hog_record_types",
    "hog_review_statuses",
    "hog_mapping_statuses",
    "hog_mapping_reasons",
    "hog_identifier_formats",
    "hog_membership_source_files",
    "hog_membership_available",
    "hog_ranking_available",
    "hog_ranking_source",
    "hog_ranking_source_row_count"
  )
}

enriched_hog_prestructure_rank_columns <- function() {
  c(
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank"
  )
}

enriched_hog_poststructure_rank_columns <- function() {
  c("final_evolutionary_rank", "final_rank")
}

#' Report available membership and HOG-linked ranking sources.
#'
#' @param relation_columns Named list of relation column vectors.
#' @return Enrichment capability metadata.
enriched_hog_capability <- function(relation_columns) {
  membership_columns <- relation_columns[["hierarchical_membership"]]
  membership_columns <- membership_columns %||% character()
  membership_available <- all(
    c("group_id", "species", "raw_identifier") %in% membership_columns
  )
  ranking_relation <- select_human_hog_ranking_relation(
    relation_columns = relation_columns
  )
  ranking_columns <- if (is.null(ranking_relation)) {
    character()
  } else {
    relation_columns[[ranking_relation]] %||% character()
  }
  list(
    available = membership_available || !is.null(ranking_relation),
    membership_available = membership_available,
    membership_columns = membership_columns,
    ranking_relation = ranking_relation,
    ranking_columns = ranking_columns
  )
}

enriched_hog_ranking_column_mapping <- function(ranking_columns) {
  reserved <- enriched_hog_overview_columns()
  source_columns <- setdiff(ranking_columns, "primary_group_id")
  output_columns <- character(length(source_columns))
  for (index in seq_along(source_columns)) {
    source <- source_columns[[index]]
    output <- source
    if (output %in% reserved || startsWith(output, "member_")) {
      output <- paste0("ranking_", source)
    }
    candidate <- output
    suffix <- 2L
    while (candidate %in% reserved) {
      candidate <- paste0(output, "_", suffix)
      suffix <- suffix + 1L
    }
    output_columns[[index]] <- candidate
    reserved <- c(reserved, candidate)
  }
  tibble::tibble(source = source_columns, output = output_columns)
}

enriched_hog_member_column_mapping <- function(membership_columns) {
  source_columns <- setdiff(membership_columns, "group_id")
  tibble::tibble(
    source = source_columns,
    output = paste0("member_", source_columns)
  )
}

#' Return every selectable field in one enriched-HOG result.
#'
#' @param result Result key.
#' @param capability Enrichment capability metadata.
#' @return Ordered output field names.
enriched_hog_columns <- function(result, capability) {
  selected_result <- validate_enriched_hog_result(result = result)
  if (!isTRUE(capability$available)) {
    stop("No root-HOG membership or HOG-linked ranking is available.", call. = FALSE)
  }
  columns <- enriched_hog_overview_columns()
  if (identical(selected_result, enriched_hog_members_key())) {
    columns <- c(
      columns,
      enriched_hog_member_column_mapping(
        membership_columns = capability$membership_columns
      )$output
    )
  }
  c(
    columns,
    enriched_hog_ranking_column_mapping(
      ranking_columns = capability$ranking_columns
    )$output
  )
}

enriched_hog_optional_text <- function(columns, column) {
  if (!column %in% columns) {
    return("CAST(NULL AS VARCHAR)")
  }
  paste0("CAST(", quote_duckdb_identifier(column), " AS VARCHAR)")
}

enriched_hog_membership_ctes <- function(capability, alias = "e3_resource") {
  if (!isTRUE(capability$membership_available)) {
    return(paste0(
      "membership AS (SELECT CAST(NULL AS VARCHAR) AS hog_id WHERE FALSE), ",
      "membership_summary AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, ",
      "CAST(NULL AS BIGINT) AS hog_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_species_count, ",
      "CAST(NULL AS BIGINT) AS hog_human_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_arabidopsis_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_target_plant_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_target_plant_species_count, ",
      "CAST(NULL AS VARCHAR) AS hog_species_present, ",
      "CAST(NULL AS VARCHAR) AS hog_target_plant_species_present, ",
      "CAST(NULL AS VARCHAR) AS human_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS human_hog_accessions, ",
      "CAST(NULL AS VARCHAR) AS human_hog_entries, ",
      "CAST(NULL AS VARCHAR) AS human_hog_raw_identifiers, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_accessions, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_entries, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_raw_identifiers, ",
      "CAST(NULL AS VARCHAR) AS hog_orthogroup_ids, ",
      "CAST(NULL AS VARCHAR) AS hog_gene_tree_parent_clades, ",
      "CAST(NULL AS VARCHAR) AS hog_record_types, ",
      "CAST(NULL AS VARCHAR) AS hog_review_statuses, ",
      "CAST(NULL AS VARCHAR) AS hog_mapping_statuses, ",
      "CAST(NULL AS VARCHAR) AS hog_mapping_reasons, ",
      "CAST(NULL AS VARCHAR) AS hog_identifier_formats, ",
      "CAST(NULL AS VARCHAR) AS hog_membership_source_files WHERE FALSE)"
    ))
  }
  columns <- capability$membership_columns
  selected <- c(
    "CAST(group_id AS VARCHAR) AS hog_id",
    vapply(
      setdiff(columns, "group_id"),
      quote_duckdb_identifier,
      character(1L)
    )
  )
  parsed_accession <- enriched_hog_optional_text(columns, "parsed_accession")
  parsed_entry <- enriched_hog_optional_text(columns, "parsed_entry")
  representative <- paste0(
    "coalesce(nullif(trim(", parsed_accession, "), ''), ",
    "nullif(trim(", parsed_entry, "), ''), ",
    "nullif(trim(CAST(raw_identifier AS VARCHAR)), ''))"
  )
  orthogroup <- enriched_hog_optional_text(columns, "orthogroup_id")
  parent <- enriched_hog_optional_text(columns, "gene_tree_parent_clade")
  raw_identifier <- "CAST(raw_identifier AS VARCHAR)"
  summary_fields <- c(
    hog_record_types = "record_type",
    hog_review_statuses = "review_status",
    hog_mapping_statuses = "mapping_status",
    hog_mapping_reasons = "mapping_reason",
    hog_identifier_formats = "identifier_format",
    hog_membership_source_files = "source_file"
  )
  membership_summary_sql <- vapply(names(summary_fields), function(output) {
    expression <- enriched_hog_optional_text(
      columns = columns,
      column = unname(summary_fields[[output]])
    )
    paste0(
      "coalesce(string_agg(DISTINCT ", expression, ", ';' ORDER BY ",
      expression, ") FILTER (WHERE ", expression, " IS NOT NULL AND trim(",
      expression, ") != ''), '') AS ", output
    )
  }, character(1L))
  plants <- human_hog_target_plants()
  if (length(plants) == 0L) {
    stop("The packaged taxonomy manifest contains no target plants.", call. = FALSE)
  }
  plant_values <- paste0(
    "('",
    vapply(plants, escape_sql_literal, character(1L)),
    "')",
    collapse = ", "
  )
  source <- qualified_resource_relation(
    relation = "hierarchical_membership",
    alias = alias
  )
  paste0(
    "membership AS (SELECT ", paste(selected, collapse = ", "), " FROM ",
    source, " WHERE group_id IS NOT NULL AND ",
    "starts_with(trim(CAST(group_id AS VARCHAR)), 'N0.HOG')), ",
    "target_plants(species) AS (VALUES ", plant_values, "), ",
    "member_classes AS (SELECT m.*, ",
    "CAST(species AS VARCHAR) = 'Homo_sapiens' AS is_human, ",
    "CAST(species AS VARCHAR) = 'Arabidopsis_thaliana' AS is_arabidopsis, ",
    "EXISTS (SELECT 1 FROM target_plants p WHERE ",
    "p.species = CAST(m.species AS VARCHAR)) AS is_target_plant, ",
    representative, " AS representative FROM membership m), ",
    "membership_summary AS (SELECT hog_id, count(*) AS hog_member_count, ",
    "count(DISTINCT CAST(species AS VARCHAR)) AS hog_species_count, ",
    "count(*) FILTER (WHERE is_human) AS hog_human_member_count, ",
    "count(*) FILTER (WHERE is_arabidopsis) AS hog_arabidopsis_member_count, ",
    "count(*) FILTER (WHERE is_target_plant) AS hog_target_plant_member_count, ",
    "count(DISTINCT CAST(species AS VARCHAR)) FILTER (WHERE is_target_plant) ",
    "AS hog_target_plant_species_count, ",
    "coalesce(string_agg(DISTINCT CAST(species AS VARCHAR), ';' ORDER BY ",
    "CAST(species AS VARCHAR)), '') AS hog_species_present, ",
    "coalesce(string_agg(DISTINCT CAST(species AS VARCHAR), ';' ORDER BY ",
    "CAST(species AS VARCHAR)) FILTER (WHERE is_target_plant), '') ",
    "AS hog_target_plant_species_present, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE is_human AND representative IS NOT NULL), '') ",
    "AS human_hog_representatives, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE is_arabidopsis AND representative IS NOT NULL), '') ",
    "AS arabidopsis_hog_representatives, ",
    "coalesce(string_agg(DISTINCT ", parsed_accession, ", ';' ORDER BY ",
    parsed_accession, ") FILTER (WHERE is_human AND ", parsed_accession,
    " IS NOT NULL AND trim(", parsed_accession,
    ") != ''), '') AS human_hog_accessions, ",
    "coalesce(string_agg(DISTINCT ", parsed_entry, ", ';' ORDER BY ",
    parsed_entry, ") FILTER (WHERE is_human AND ", parsed_entry,
    " IS NOT NULL AND trim(", parsed_entry,
    ") != ''), '') AS human_hog_entries, ",
    "coalesce(string_agg(DISTINCT ", raw_identifier, ", ';' ORDER BY ",
    raw_identifier, ") FILTER (WHERE is_human AND trim(", raw_identifier,
    ") != ''), '') AS human_hog_raw_identifiers, ",
    "coalesce(string_agg(DISTINCT ", parsed_accession, ", ';' ORDER BY ",
    parsed_accession, ") FILTER (WHERE is_arabidopsis AND ",
    parsed_accession, " IS NOT NULL AND trim(", parsed_accession,
    ") != ''), '') AS arabidopsis_hog_accessions, ",
    "coalesce(string_agg(DISTINCT ", parsed_entry, ", ';' ORDER BY ",
    parsed_entry, ") FILTER (WHERE is_arabidopsis AND ", parsed_entry,
    " IS NOT NULL AND trim(", parsed_entry,
    ") != ''), '') AS arabidopsis_hog_entries, ",
    "coalesce(string_agg(DISTINCT ", raw_identifier, ", ';' ORDER BY ",
    raw_identifier, ") FILTER (WHERE is_arabidopsis AND trim(",
    raw_identifier, ") != ''), '') AS arabidopsis_hog_raw_identifiers, ",
    "coalesce(string_agg(DISTINCT ", orthogroup, ", ';' ORDER BY ",
    orthogroup, ") FILTER (WHERE ", orthogroup, " IS NOT NULL AND trim(",
    orthogroup, ") != ''), '') AS hog_orthogroup_ids, ",
    "coalesce(string_agg(DISTINCT ", parent, ", ';' ORDER BY ", parent,
    ") FILTER (WHERE ", parent, " IS NOT NULL AND trim(", parent,
    ") != ''), '') AS hog_gene_tree_parent_clades, ",
    paste(membership_summary_sql, collapse = ", "), " FROM member_classes ",
    "GROUP BY hog_id)"
  )
}

enriched_hog_ranking_ctes <- function(capability, alias = "e3_resource") {
  relation <- capability$ranking_relation
  if (is.null(relation)) {
    return(paste0(
      "ranking_rows AS (SELECT CAST(NULL AS VARCHAR) AS primary_group_id, ",
      "CAST(NULL AS BIGINT) AS _e3_hog_ranking_source_row_count WHERE FALSE)"
    ))
  }
  columns <- capability$ranking_columns
  order_columns <- unique(intersect(
    c(
      human_hog_rank_columns(),
      "lead_cluster_id",
      "cluster_id",
      "candidate_accessions"
    ),
    columns
  ))
  order_sql <- paste0(
    vapply(order_columns, quote_duckdb_identifier, character(1L)),
    " NULLS LAST",
    collapse = ", "
  )
  source <- qualified_resource_relation(relation = relation, alias = alias)
  paste0(
    "rank_source AS (SELECT *, count(*) OVER (PARTITION BY ",
    "CAST(primary_group_id AS VARCHAR)) AS _e3_hog_ranking_source_row_count, ",
    "row_number() OVER (PARTITION BY CAST(primary_group_id AS VARCHAR) ",
    "ORDER BY ", order_sql, ") AS _e3_hog_ranking_row FROM ", source,
    " WHERE primary_group_id IS NOT NULL AND starts_with(",
    "trim(CAST(primary_group_id AS VARCHAR)), 'N0.HOG')), ",
    "ranking_rows AS (SELECT * EXCLUDE (_e3_hog_ranking_row) FROM ",
    "rank_source WHERE _e3_hog_ranking_row = 1)"
  )
}

enriched_hog_rank_expression <- function(columns, choices) {
  column <- human_hog_first_column(columns = columns, choices = choices)
  if (is.null(column)) {
    return("CAST(NULL AS BIGINT)")
  }
  paste0("TRY_CAST(r.", quote_duckdb_identifier(column), " AS BIGINT)")
}

enriched_hog_overview_expressions <- function(capability) {
  relation <- capability$ranking_relation %||% ""
  c(
    "u.hog_id AS hog_id",
    paste0(
      enriched_hog_rank_expression(
        columns = capability$ranking_columns,
        choices = enriched_hog_prestructure_rank_columns()
      ),
      " AS hog_prestructure_rank"
    ),
    paste0(
      enriched_hog_rank_expression(
        columns = capability$ranking_columns,
        choices = enriched_hog_poststructure_rank_columns()
      ),
      " AS hog_poststructure_rank"
    ),
    "coalesce(s.human_hog_representatives, '') AS human_hog_representatives",
    paste0(
      "coalesce(s.arabidopsis_hog_representatives, '') ",
      "AS arabidopsis_hog_representatives"
    ),
    "coalesce(s.human_hog_accessions, '') AS human_hog_accessions",
    "coalesce(s.human_hog_entries, '') AS human_hog_entries",
    paste0(
      "coalesce(s.human_hog_raw_identifiers, '') ",
      "AS human_hog_raw_identifiers"
    ),
    paste0(
      "coalesce(s.arabidopsis_hog_accessions, '') ",
      "AS arabidopsis_hog_accessions"
    ),
    "coalesce(s.arabidopsis_hog_entries, '') AS arabidopsis_hog_entries",
    paste0(
      "coalesce(s.arabidopsis_hog_raw_identifiers, '') ",
      "AS arabidopsis_hog_raw_identifiers"
    ),
    "coalesce(s.hog_member_count, 0) AS hog_member_count",
    "coalesce(s.hog_species_count, 0) AS hog_species_count",
    "coalesce(s.hog_human_member_count, 0) AS hog_human_member_count",
    paste0(
      "coalesce(s.hog_arabidopsis_member_count, 0) ",
      "AS hog_arabidopsis_member_count"
    ),
    paste0(
      "coalesce(s.hog_target_plant_member_count, 0) ",
      "AS hog_target_plant_member_count"
    ),
    paste0(
      "coalesce(s.hog_target_plant_species_count, 0) ",
      "AS hog_target_plant_species_count"
    ),
    "coalesce(s.hog_species_present, '') AS hog_species_present",
    paste0(
      "coalesce(s.hog_target_plant_species_present, '') ",
      "AS hog_target_plant_species_present"
    ),
    "coalesce(s.hog_orthogroup_ids, '') AS hog_orthogroup_ids",
    paste0(
      "coalesce(s.hog_gene_tree_parent_clades, '') ",
      "AS hog_gene_tree_parent_clades"
    ),
    "coalesce(s.hog_record_types, '') AS hog_record_types",
    "coalesce(s.hog_review_statuses, '') AS hog_review_statuses",
    "coalesce(s.hog_mapping_statuses, '') AS hog_mapping_statuses",
    "coalesce(s.hog_mapping_reasons, '') AS hog_mapping_reasons",
    "coalesce(s.hog_identifier_formats, '') AS hog_identifier_formats",
    paste0(
      "coalesce(s.hog_membership_source_files, '') ",
      "AS hog_membership_source_files"
    ),
    "s.hog_id IS NOT NULL AS hog_membership_available",
    "r.primary_group_id IS NOT NULL AS hog_ranking_available",
    paste0(
      "CASE WHEN r.primary_group_id IS NULL THEN '' ELSE '",
      escape_sql_literal(relation),
      "' END AS hog_ranking_source"
    ),
    paste0(
      "coalesce(r._e3_hog_ranking_source_row_count, 0) ",
      "AS hog_ranking_source_row_count"
    )
  )
}

#' Build a bounded enriched-HOG query.
#'
#' @param result Overview or member-detail result key.
#' @param selected_columns Explicit output columns.
#' @param capability Enrichment capability metadata.
#' @param max_rows Maximum returned rows.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_enriched_hog_query <- function(
  result,
  selected_columns,
  capability,
  max_rows = 1000L,
  alias = "e3_resource"
) {
  selected_result <- validate_enriched_hog_result(result = result)
  max_rows <- suppressWarnings(as.integer(max_rows[[1L]]))
  if (is.na(max_rows) || max_rows < 1L || max_rows > 100000L) {
    stop("Maximum enriched HOG rows must be between 1 and 100000.", call. = FALSE)
  }
  available <- enriched_hog_columns(
    result = selected_result,
    capability = capability
  )
  selected <- unique(as.character(selected_columns))
  if (length(selected) == 0L) {
    stop("Select at least one enriched HOG column.", call. = FALSE)
  }
  unknown <- setdiff(selected, available)
  if (length(unknown) > 0L) {
    stop(
      paste("Unknown enriched HOG columns:", paste(unknown, collapse = ", ")),
      call. = FALSE
    )
  }
  ctes <- c(
    enriched_hog_membership_ctes(capability = capability, alias = alias),
    enriched_hog_ranking_ctes(capability = capability, alias = alias),
    paste0(
      "hog_universe AS (SELECT hog_id FROM membership_summary UNION ",
      "SELECT CAST(primary_group_id AS VARCHAR) AS hog_id FROM ranking_rows)"
    )
  )
  expressions <- enriched_hog_overview_expressions(capability = capability)
  from_sql <- paste0(
    "FROM hog_universe u LEFT JOIN membership_summary s USING (hog_id) ",
    "LEFT JOIN ranking_rows r ON CAST(r.primary_group_id AS VARCHAR) = u.hog_id"
  )
  if (identical(selected_result, enriched_hog_members_key())) {
    member_mapping <- enriched_hog_member_column_mapping(
      membership_columns = capability$membership_columns
    )
    member_sql <- paste0(
      "m.",
      vapply(member_mapping$source, quote_duckdb_identifier, character(1L)),
      " AS ",
      vapply(member_mapping$output, quote_duckdb_identifier, character(1L))
    )
    expressions <- c(expressions, member_sql)
    from_sql <- paste(from_sql, "LEFT JOIN membership m USING (hog_id)")
  }
  ranking_mapping <- enriched_hog_ranking_column_mapping(
    ranking_columns = capability$ranking_columns
  )
  ranking_sql <- paste0(
    "r.",
    vapply(ranking_mapping$source, quote_duckdb_identifier, character(1L)),
    " AS ",
    vapply(ranking_mapping$output, quote_duckdb_identifier, character(1L))
  )
  expressions <- c(expressions, ranking_sql)
  order <- paste0(
    "hog_poststructure_rank NULLS LAST, hog_prestructure_rank NULLS LAST, hog_id"
  )
  if (
    identical(selected_result, enriched_hog_members_key()) &&
      "species" %in% capability$membership_columns
  ) {
    order <- paste0(order, ", member_species NULLS LAST")
  }
  selected_sql <- paste0(
    vapply(selected, quote_duckdb_identifier, character(1L)),
    collapse = ", "
  )
  paste0(
    "WITH ", paste(ctes, collapse = ", "), ", enriched AS (SELECT ",
    paste(expressions, collapse = ", "), " ", from_sql, ") SELECT ",
    selected_sql, " FROM enriched ORDER BY ", order, " LIMIT ", max_rows
  )
}

#' Build display metadata for enriched-HOG fields.
#'
#' @param result Result key.
#' @param capability Enrichment capability metadata.
#' @return Column metadata tibble.
enriched_hog_column_schema <- function(result, capability) {
  columns <- enriched_hog_columns(result = result, capability = capability)
  source <- dplyr::case_when(
    startsWith(columns, "member_") ~ "hierarchical_membership",
    columns %in% enriched_hog_overview_columns() ~ "derived HOG summary",
    TRUE ~ capability$ranking_relation %||% "ranking unavailable"
  )
  tibble::tibble(
    column_name = columns,
    column_type = "source or derived",
    source = source
  )
}
