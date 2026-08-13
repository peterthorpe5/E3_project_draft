#' Query and transformation helpers for OrthoFinder exploration.

#' Resolve the membership relation for an OrthoFinder grouping level.
#'
#' @param group_type `hierarchical_orthogroup` or `orthogroup`.
#' @return Canonical relation name.
orthology_relation_name <- function(group_type) {
  choices <- c(
    hierarchical_orthogroup = "hierarchical_membership",
    orthogroup = "orthogroup_membership"
  )
  value <- unname(choices[[as.character(group_type)]])
  if (is.null(value) || is.na(value) || !nzchar(value)) {
    stop("Unsupported OrthoFinder group type.", call. = FALSE)
  }
  value
}

#' Resolve the source record type for an OrthoFinder grouping level.
#'
#' @param group_type App grouping-level value.
#' @return Source record-type value.
orthology_record_type <- function(group_type) {
  choices <- c(
    hierarchical_orthogroup = "HIERARCHICAL_ORTHOGROUP",
    orthogroup = "ORTHOGROUP"
  )
  value <- unname(choices[[as.character(group_type)]])
  if (is.null(value) || is.na(value) || !nzchar(value)) {
    stop("Unsupported OrthoFinder group type.", call. = FALSE)
  }
  value
}

#' Return a qualified, safely quoted resource relation.
#'
#' @param relation Canonical relation name.
#' @param alias Attached DuckDB alias.
#' @return Qualified SQL identifier.
qualified_resource_relation <- function(relation, alias = "e3_resource") {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  paste0(safe_alias, ".main.", quote_duckdb_identifier(relation))
}

#' Build release-level OrthoFinder metrics SQL.
#'
#' @param relation Membership relation.
#' @param seed_relation_available Whether the seeded member relation is available.
#' @param alias Attached DuckDB alias.
#' @return DuckDB SQL query.
build_orthology_metrics_query <- function(
  relation,
  seed_relation_available = TRUE,
  alias = "e3_resource"
) {
  source <- qualified_resource_relation(relation = relation, alias = alias)
  seed_expression <- if (isTRUE(seed_relation_available)) {
    seed_source <- qualified_resource_relation(
      relation = "candidate_group_member_sequences",
      alias = alias
    )
    paste0(
      "EXISTS (SELECT 1 FROM ", seed_source,
      " seeds WHERE seeds.group_id = grouped.group_id)"
    )
  } else {
    "FALSE"
  }
  paste0(
    "WITH source AS (SELECT group_id, species FROM ", source,
    " WHERE group_id IS NOT NULL AND trim(group_id) != ''), ",
    "totals AS (SELECT COUNT(*) AS input_sequences, ",
    "COUNT(DISTINCT species) AS input_species FROM source), ",
    "grouped AS (SELECT group_id, COUNT(*) AS member_count, ",
    "COUNT(DISTINCT species) AS species_count FROM source GROUP BY group_id) ",
    "SELECT totals.input_sequences, totals.input_species, ",
    "COUNT(*) AS group_count, SUM(CASE WHEN ", seed_expression,
    " THEN 1 ELSE 0 END) AS seeded_group_count, ",
    "SUM(CASE WHEN grouped.species_count = totals.input_species ",
    "THEN 1 ELSE 0 END) AS all_species_group_count, ",
    "COALESCE(MAX(grouped.member_count), 0) AS largest_group_size, ",
    "COALESCE(arg_max(grouped.group_id, grouped.member_count), '') ",
    "AS largest_group_id FROM grouped CROSS JOIN totals ",
    "GROUP BY totals.input_sequences, totals.input_species"
  )
}

#' Build exact source-species options SQL.
#'
#' @param relation Membership relation.
#' @param alias Attached DuckDB alias.
#' @return DuckDB SQL query.
build_orthology_species_query <- function(relation, alias = "e3_resource") {
  source <- qualified_resource_relation(relation = relation, alias = alias)
  paste0(
    "SELECT DISTINCT trim(species) AS species FROM ", source,
    " WHERE species IS NOT NULL AND trim(species) != '' ",
    "ORDER BY lower(species), species"
  )
}

#' Quote a vector of SQL literal values.
#'
#' @param values Character values.
#' @return Comma-separated SQL literals.
orthology_sql_values <- function(values) {
  values <- unique(trimws(as.character(values)))
  values <- values[!is.na(values) & nzchar(values)]
  paste0("'", vapply(values, escape_sql_literal, character(1L)), "'", collapse = ", ")
}

#' Build a bounded one-row-per-OrthoFinder-group summary SQL query.
#'
#' @param relation Membership relation.
#' @param required_species Exact labels which must all occur.
#' @param taxonomy_species Curated labels of which at least one must occur.
#' @param breadth Species-breadth filter.
#' @param seeded_only Whether inherited E3 seed evidence is required.
#' @param max_rows Maximum returned groups.
#' @param seed_relation_available Whether seeded members are available.
#' @param alias Attached DuckDB alias.
#' @return DuckDB SQL query.
build_orthology_group_summary_query <- function(
  relation,
  required_species = character(),
  taxonomy_species = character(),
  breadth = "all",
  seeded_only = FALSE,
  max_rows = 1000L,
  seed_relation_available = TRUE,
  alias = "e3_resource"
) {
  breadth <- match.arg(
    breadth,
    c("all", "one_species", "multiple_species", "all_species")
  )
  max_rows <- max(1L, min(100000L, as.integer(max_rows)))
  source <- qualified_resource_relation(relation = relation, alias = alias)
  required_species <- unique(trimws(as.character(required_species)))
  required_species <- required_species[nzchar(required_species)]
  taxonomy_species <- unique(trimws(as.character(taxonomy_species)))
  taxonomy_species <- taxonomy_species[nzchar(taxonomy_species)]
  required_expression <- if (length(required_species) > 0L) {
    paste0(
      "COUNT(DISTINCT CASE WHEN species IN (",
      orthology_sql_values(required_species),
      ") THEN species END)"
    )
  } else {
    "0"
  }
  taxonomy_expression <- if (length(taxonomy_species) > 0L) {
    paste0(
      "COUNT(DISTINCT CASE WHEN species IN (",
      orthology_sql_values(taxonomy_species),
      ") THEN species END)"
    )
  } else {
    "0"
  }
  seed_expression <- if (isTRUE(seed_relation_available)) {
    seed_source <- qualified_resource_relation(
      relation = "candidate_group_member_sequences",
      alias = alias
    )
    paste0(
      "EXISTS (SELECT 1 FROM ", seed_source,
      " seeds WHERE seeds.group_id = grouped.group_id)"
    )
  } else {
    "FALSE"
  }
  filters <- character()
  if (length(required_species) > 0L) {
    filters <- c(
      filters,
      paste0("matched_required_species = ", length(required_species))
    )
  }
  if (length(taxonomy_species) > 0L) {
    filters <- c(filters, "matched_taxonomy_species > 0")
  }
  if (breadth == "one_species") {
    filters <- c(filters, "species_count = 1")
  } else if (breadth == "multiple_species") {
    filters <- c(filters, "species_count > 1 AND species_count < input_species")
  } else if (breadth == "all_species") {
    filters <- c(filters, "species_count = input_species")
  }
  if (isTRUE(seeded_only)) {
    filters <- c(filters, "contains_e3_seed_evidence")
  }
  where_clause <- if (length(filters) > 0L) {
    paste("WHERE", paste(filters, collapse = " AND "))
  } else {
    ""
  }
  paste0(
    "WITH source AS (SELECT group_id, trim(species) AS species FROM ",
    source, " WHERE group_id IS NOT NULL AND trim(group_id) != ''), ",
    "totals AS (SELECT COUNT(DISTINCT species) AS input_species FROM source), ",
    "grouped AS (SELECT group_id, COUNT(*) AS member_count, ",
    "COUNT(DISTINCT species) AS species_count, ",
    "string_agg(DISTINCT species, ';' ORDER BY species) AS species_present, ",
    required_expression, " AS matched_required_species, ",
    taxonomy_expression, " AS matched_taxonomy_species FROM source ",
    "GROUP BY group_id), labelled AS (SELECT grouped.*, totals.input_species, ",
    "CASE WHEN species_count = 1 THEN 'One species only' ",
    "WHEN species_count = input_species THEN 'All input species' ",
    "ELSE 'Multiple species (not all)' END AS species_breadth, ",
    seed_expression, " AS contains_e3_seed_evidence FROM grouped CROSS JOIN totals) ",
    "SELECT group_id, member_count, species_count, input_species, ",
    "species_breadth, contains_e3_seed_evidence, species_present FROM labelled ",
    where_clause, " ORDER BY member_count DESC, lower(group_id), group_id LIMIT ",
    max_rows
  )
}

#' Build the full group-size frequency query.
#'
#' @param relation Membership relation.
#' @param alias Attached DuckDB alias.
#' @return DuckDB SQL query.
build_orthology_size_distribution_query <- function(
  relation,
  alias = "e3_resource"
) {
  source <- qualified_resource_relation(relation = relation, alias = alias)
  paste0(
    "WITH source AS (SELECT group_id, species FROM ", source,
    " WHERE group_id IS NOT NULL AND trim(group_id) != ''), ",
    "totals AS (SELECT COUNT(DISTINCT species) AS input_species FROM source), ",
    "grouped AS (SELECT group_id, COUNT(*) AS member_count, ",
    "COUNT(DISTINCT species) AS species_count FROM source GROUP BY group_id), ",
    "labelled AS (SELECT member_count, CASE WHEN species_count = 1 ",
    "THEN 'One species only' WHEN species_count = input_species ",
    "THEN 'All input species' ELSE 'Multiple species (not all)' ",
    "END AS species_breadth FROM grouped CROSS JOIN totals) ",
    "SELECT member_count, species_breadth, COUNT(*) AS group_count FROM labelled ",
    "GROUP BY member_count, species_breadth ORDER BY member_count, species_breadth"
  )
}

#' Build available E3 seed identifier SQL.
#'
#' @param alias Attached DuckDB alias.
#' @return DuckDB SQL query.
build_seed_identifiers_query <- function(alias = "e3_resource") {
  source <- qualified_resource_relation(
    relation = "candidate_group_member_sequences",
    alias = alias
  )
  paste0(
    "SELECT DISTINCT trim(seed_id) AS seed_id FROM ", source,
    ", UNNEST(string_split(coalesce(candidate_accessions_for_cluster, ''), ';')) ",
    "AS seeds(seed_id) WHERE trim(seed_id) != '' ORDER BY lower(seed_id), seed_id"
  )
}

#' Build a sequence-bearing member query for selected E3 seeds.
#'
#' @param seed_identifiers One or more inherited E3 seed identifiers.
#' @param group_type OrthoFinder grouping level.
#' @param match_mode `any` or `all`.
#' @param species Optional exact species filter.
#' @param max_rows Maximum member rows.
#' @param alias Attached DuckDB alias.
#' @return DuckDB SQL query.
build_seed_group_members_query <- function(
  seed_identifiers,
  group_type = "hierarchical_orthogroup",
  match_mode = "any",
  species = character(),
  max_rows = 10000L,
  alias = "e3_resource"
) {
  match_mode <- match.arg(match_mode, c("any", "all"))
  seeds <- unique(trimws(as.character(seed_identifiers)))
  seeds <- seeds[!is.na(seeds) & nzchar(seeds)]
  if (length(seeds) == 0L) {
    stop("Select at least one E3 seed identifier.", call. = FALSE)
  }
  source <- qualified_resource_relation(
    relation = "candidate_group_member_sequences",
    alias = alias
  )
  having <- if (match_mode == "all") {
    paste0("COUNT(DISTINCT seed_id) = ", length(seeds))
  } else {
    "COUNT(DISTINCT seed_id) >= 1"
  }
  species <- unique(trimws(as.character(species)))
  species <- species[!is.na(species) & nzchar(species)]
  species_filter <- if (length(species) > 0L) {
    paste0(" AND members.species IN (", orthology_sql_values(species), ")")
  } else {
    ""
  }
  max_rows <- max(1L, min(100000L, as.integer(max_rows)))
  paste0(
    "WITH exploded AS (SELECT DISTINCT record_type, group_id, ",
    "trim(seed_id) AS seed_id FROM ", source,
    ", UNNEST(string_split(coalesce(candidate_accessions_for_cluster, ''), ';')) ",
    "AS seeds(seed_id) WHERE record_type = '",
    escape_sql_literal(orthology_record_type(group_type)),
    "' AND trim(seed_id) IN (", orthology_sql_values(seeds), ")), ",
    "matched_groups AS (SELECT record_type, group_id, ",
    "string_agg(DISTINCT seed_id, ';' ORDER BY seed_id) ",
    "AS matched_seed_identifiers FROM exploded GROUP BY record_type, group_id ",
    "HAVING ", having, ") SELECT members.record_type AS primary_group_type, ",
    "members.group_id AS primary_group_id, matched.matched_seed_identifiers, ",
    "string_agg(DISTINCT members.cluster_id, ';' ORDER BY members.cluster_id) ",
    "AS linked_deepclust_clusters, members.species, members.internal_id, ",
    "members.raw_identifier, members.parsed_accession, members.parsed_entry, ",
    "members.review_status, members.mapping_status, ",
    "bool_or(coalesce(members.is_input_candidate, FALSE)) AS is_input_seed_member, ",
    "max(members.sequence_length) AS sequence_length, ",
    "any_value(members.protein_sequence) AS protein_sequence FROM ", source,
    " members INNER JOIN matched_groups matched ON members.record_type = ",
    "matched.record_type AND members.group_id = matched.group_id WHERE TRUE",
    species_filter, " GROUP BY members.record_type, members.group_id, ",
    "matched.matched_seed_identifiers, members.species, members.internal_id, ",
    "members.raw_identifier, members.parsed_accession, members.parsed_entry, ",
    "members.review_status, members.mapping_status ORDER BY ",
    "lower(members.group_id), members.group_id, lower(members.species), ",
    "members.species, lower(members.raw_identifier), members.raw_identifier LIMIT ",
    max_rows
  )
}

#' Summarise sequence-bearing seed-search rows by OrthoFinder group.
#'
#' @param members Member rows.
#' @return One row per matching group.
summarise_seed_group_members <- function(members) {
  required <- c(
    "primary_group_type",
    "primary_group_id",
    "matched_seed_identifiers",
    "species",
    "raw_identifier"
  )
  missing <- setdiff(required, names(members))
  if (length(missing) > 0L) {
    stop(
      paste("Seed member result is missing columns:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  if (nrow(members) == 0L) {
    return(tibble::tibble())
  }
  members |>
    dplyr::group_by(
      .data$primary_group_type,
      .data$primary_group_id,
      .data$matched_seed_identifiers
    ) |>
    dplyr::summarise(
      member_count = dplyr::n_distinct(.data$raw_identifier),
      species_count = dplyr::n_distinct(.data$species),
      species_present = paste(sort(unique(.data$species)), collapse = ";"),
      .groups = "drop"
    )
}

#' Load the curated species manifest distributed with the app.
#'
#' @return Curated taxonomy data frame.
load_species_taxonomy <- function() {
  path <- glossary_resource_path("species_taxonomy.tsv")
  utils::read.delim(
    file = path,
    sep = "\t",
    stringsAsFactors = FALSE,
    check.names = FALSE,
    quote = "",
    comment.char = ""
  )
}
