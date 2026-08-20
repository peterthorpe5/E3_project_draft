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

enriched_hog_member_structural_relations <- function() {
  c("selected_pockets", "pocket_conservation_members", "ranked_member_pockets")
}

enriched_hog_member_structural_columns <- function() {
  c(
    "member_structure_assessed", "member_structural_source",
    "member_structural_accession", "member_structural_species",
    "member_pocket_number", "member_druggability_score",
    "member_passes_druggability_threshold", "member_pocket_mapping_fraction",
    "member_pocket_plddt_fraction", "member_predictor_agreement",
    "member_pocket_component_selected", "member_structural_evidence_status"
  )
}

#' Collect column names for HOG-linked relations only.
#'
#' @param resource_source Flexible result source.
#' @param relations Available relation names.
#' @return Named list of relation column vectors.
collect_enriched_hog_relation_columns <- function(resource_source, relations) {
  relevant <- intersect(
    unique(c(
      "hierarchical_membership",
      human_hog_ranking_relations(),
      enriched_hog_member_structural_relations()
    )),
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
    "rice_hog_representatives",
    "barley_hog_representatives",
    "hog_three_dimensional_position_status",
    "hog_three_dimensional_alignment_status",
    "hog_conservation_status",
    "hog_same_3d_pocket_position_supported",
    "hog_conserved_3d_pocket_supported",
    "hog_minimum_druggability_score",
    "hog_all_assessed_members_pass_druggability",
    "hog_structural_species_fraction",
    "hog_mean_minimum_tm_score",
    "hog_mean_pocket_overlap_fraction",
    "hog_median_centroid_distance_angstrom",
    "hog_mean_structural_residue_match_fraction",
    "hog_mean_structural_chemical_group_conservation",
    "human_hog_accessions",
    "human_hog_entries",
    "human_hog_raw_identifiers",
    "arabidopsis_hog_accessions",
    "arabidopsis_hog_entries",
    "arabidopsis_hog_raw_identifiers",
    "rice_hog_accessions",
    "rice_hog_entries",
    "rice_hog_raw_identifiers",
    "barley_hog_accessions",
    "barley_hog_entries",
    "barley_hog_raw_identifiers",
    "hog_member_count",
    "hog_species_count",
    "hog_human_member_count",
    "hog_arabidopsis_member_count",
    "hog_rice_member_count",
    "hog_barley_member_count",
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
  member_structural_relation <- NULL
  for (relation in enriched_hog_member_structural_relations()) {
    columns <- relation_columns[[relation]] %||% character()
    if (all(c("primary_group_id", "candidate_accession") %in% columns)) {
      member_structural_relation <- relation
      break
    }
  }
  member_structural_columns <- if (is.null(member_structural_relation)) {
    character()
  } else {
    relation_columns[[member_structural_relation]] %||% character()
  }
  list(
    available = membership_available || !is.null(ranking_relation),
    membership_available = membership_available,
    membership_columns = membership_columns,
    ranking_relation = ranking_relation,
    ranking_columns = ranking_columns,
    member_structural_relation = member_structural_relation,
    member_structural_columns = member_structural_columns
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
    columns <- c(columns, enriched_hog_member_structural_columns())
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
      "CAST(NULL AS BIGINT) AS hog_rice_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_barley_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_target_plant_member_count, ",
      "CAST(NULL AS BIGINT) AS hog_target_plant_species_count, ",
      "CAST(NULL AS VARCHAR) AS hog_species_present, ",
      "CAST(NULL AS VARCHAR) AS hog_target_plant_species_present, ",
      "CAST(NULL AS VARCHAR) AS human_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS rice_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS barley_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS human_hog_accessions, ",
      "CAST(NULL AS VARCHAR) AS human_hog_entries, ",
      "CAST(NULL AS VARCHAR) AS human_hog_raw_identifiers, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_accessions, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_entries, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_raw_identifiers, ",
      "CAST(NULL AS VARCHAR) AS rice_hog_accessions, ",
      "CAST(NULL AS VARCHAR) AS rice_hog_entries, ",
      "CAST(NULL AS VARCHAR) AS rice_hog_raw_identifiers, ",
      "CAST(NULL AS VARCHAR) AS barley_hog_accessions, ",
      "CAST(NULL AS VARCHAR) AS barley_hog_entries, ",
      "CAST(NULL AS VARCHAR) AS barley_hog_raw_identifiers, ",
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
    "CAST(species AS VARCHAR) = 'Oryza_sativa' AS is_rice, ",
    "CAST(species AS VARCHAR) = 'Hordeum_vulgare' AS is_barley, ",
    "EXISTS (SELECT 1 FROM target_plants p WHERE ",
    "p.species = CAST(m.species AS VARCHAR)) AS is_target_plant, ",
    representative, " AS representative FROM membership m), ",
    "membership_summary AS (SELECT hog_id, count(*) AS hog_member_count, ",
    "count(DISTINCT CAST(species AS VARCHAR)) AS hog_species_count, ",
    "count(*) FILTER (WHERE is_human) AS hog_human_member_count, ",
    "count(*) FILTER (WHERE is_arabidopsis) AS hog_arabidopsis_member_count, ",
    "count(*) FILTER (WHERE is_rice) AS hog_rice_member_count, ",
    "count(*) FILTER (WHERE is_barley) AS hog_barley_member_count, ",
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
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE is_rice AND representative IS NOT NULL), '') ",
    "AS rice_hog_representatives, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE is_barley AND representative IS NOT NULL), '') ",
    "AS barley_hog_representatives, ",
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
    "coalesce(string_agg(DISTINCT ", parsed_accession, ", ';' ORDER BY ",
    parsed_accession, ") FILTER (WHERE is_rice AND ", parsed_accession,
    " IS NOT NULL AND trim(", parsed_accession,
    ") != ''), '') AS rice_hog_accessions, ",
    "coalesce(string_agg(DISTINCT ", parsed_entry, ", ';' ORDER BY ",
    parsed_entry, ") FILTER (WHERE is_rice AND ", parsed_entry,
    " IS NOT NULL AND trim(", parsed_entry,
    ") != ''), '') AS rice_hog_entries, ",
    "coalesce(string_agg(DISTINCT ", raw_identifier, ", ';' ORDER BY ",
    raw_identifier, ") FILTER (WHERE is_rice AND trim(", raw_identifier,
    ") != ''), '') AS rice_hog_raw_identifiers, ",
    "coalesce(string_agg(DISTINCT ", parsed_accession, ", ';' ORDER BY ",
    parsed_accession, ") FILTER (WHERE is_barley AND ", parsed_accession,
    " IS NOT NULL AND trim(", parsed_accession,
    ") != ''), '') AS barley_hog_accessions, ",
    "coalesce(string_agg(DISTINCT ", parsed_entry, ", ';' ORDER BY ",
    parsed_entry, ") FILTER (WHERE is_barley AND ", parsed_entry,
    " IS NOT NULL AND trim(", parsed_entry,
    ") != ''), '') AS barley_hog_entries, ",
    "coalesce(string_agg(DISTINCT ", raw_identifier, ", ';' ORDER BY ",
    raw_identifier, ") FILTER (WHERE is_barley AND trim(", raw_identifier,
    ") != ''), '') AS barley_hog_raw_identifiers, ",
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

enriched_hog_member_structural_expression <- function(
  columns,
  choices,
  sql_type
) {
  selected <- choices[choices %in% columns]
  if (length(selected) == 0L) {
    return(paste0("CAST(NULL AS ", sql_type, ")"))
  }
  paste0(
    "TRY_CAST(", quote_duckdb_identifier(selected[[1L]]),
    " AS ", sql_type, ")"
  )
}

enriched_hog_member_structural_ctes <- function(
  capability,
  alias = "e3_resource"
) {
  relation <- capability$member_structural_relation
  if (is.null(relation)) {
    return(paste0(
      "member_structural_rows AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, ",
      "CAST(NULL AS VARCHAR) AS candidate_accession, ",
      "CAST(NULL AS VARCHAR) AS species, CAST(NULL AS BIGINT) AS pocket_number, ",
      "CAST(NULL AS DOUBLE) AS druggability_score, ",
      "CAST(NULL AS BOOLEAN) AS passes_druggability_threshold, ",
      "CAST(NULL AS DOUBLE) AS mapping_fraction, ",
      "CAST(NULL AS DOUBLE) AS pocket_plddt_fraction, ",
      "CAST(NULL AS DOUBLE) AS predictor_agreement, ",
      "CAST(NULL AS BOOLEAN) AS component_selected, ",
      "CAST(NULL AS VARCHAR) AS structural_evidence_status WHERE FALSE)"
    ))
  }
  columns <- capability$member_structural_columns
  optional <- function(choices, sql_type) {
    enriched_hog_member_structural_expression(columns, choices, sql_type)
  }
  order_columns <- intersect(
    c("is_strict_selected", "selection_rank", "pocket_number", "cluster_id"),
    columns
  )
  order_sql <- if (length(order_columns) == 0L) {
    quote_duckdb_identifier("candidate_accession")
  } else {
    paste0(
      vapply(order_columns, quote_duckdb_identifier, character(1L)),
      ifelse(order_columns == "is_strict_selected", " DESC", " ASC"),
      " NULLS LAST",
      collapse = ", "
    )
  }
  source <- qualified_resource_relation(relation = relation, alias = alias)
  paste0(
    "member_structural_source AS (SELECT ",
    "CAST(primary_group_id AS VARCHAR) AS hog_id, ",
    "CAST(candidate_accession AS VARCHAR) AS candidate_accession, ",
    optional("species_column", "VARCHAR"), " AS species, ",
    optional("pocket_number", "BIGINT"), " AS pocket_number, ",
    optional("druggability_score", "DOUBLE"), " AS druggability_score, ",
    optional("passes_druggability_threshold", "BOOLEAN"),
    " AS passes_druggability_threshold, ",
    optional("mapping_fraction", "DOUBLE"), " AS mapping_fraction, ",
    optional(
      c("pocket_plddt_fraction", "conservative_fraction_plddt_ge_70"),
      "DOUBLE"
    ), " AS pocket_plddt_fraction, ",
    optional("predictor_agreement", "DOUBLE"), " AS predictor_agreement, ",
    optional(c("component_selected", "is_strict_selected"), "BOOLEAN"),
    " AS component_selected, ",
    optional(c("structural_evidence_status", "selection_status"), "VARCHAR"),
    " AS structural_evidence_status, row_number() OVER (PARTITION BY ",
    "CAST(primary_group_id AS VARCHAR), ",
    "upper(trim(CAST(candidate_accession AS VARCHAR))) ORDER BY ", order_sql,
    ") AS _e3_member_structural_row FROM ", source, "), ",
    "member_structural_rows AS (SELECT * EXCLUDE ",
    "(_e3_member_structural_row) FROM member_structural_source ",
    "WHERE _e3_member_structural_row = 1)"
  )
}

enriched_hog_rank_expression <- function(columns, choices) {
  column <- human_hog_first_column(columns = columns, choices = choices)
  if (is.null(column)) {
    return("CAST(NULL AS BIGINT)")
  }
  paste0("TRY_CAST(r.", quote_duckdb_identifier(column), " AS BIGINT)")
}

enriched_hog_value_expression <- function(columns, choices, sql_type) {
  column <- human_hog_first_column(columns = columns, choices = choices)
  if (is.null(column)) {
    return(paste0("CAST(NULL AS ", sql_type, ")"))
  }
  paste0(
    "TRY_CAST(r.", quote_duckdb_identifier(column), " AS ", sql_type, ")"
  )
}

enriched_hog_support_expression <- function(columns, choices, supported_status) {
  status <- enriched_hog_value_expression(columns, choices, "VARCHAR")
  paste0(
    "CASE WHEN ", status, " IS NULL OR ", status, " = 'NOT_ASSESSED' ",
    "THEN CAST(NULL AS BOOLEAN) ELSE ", status, " = '",
    supported_status, "' END"
  )
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
    "coalesce(s.rice_hog_representatives, '') AS rice_hog_representatives",
    "coalesce(s.barley_hog_representatives, '') AS barley_hog_representatives",
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "three_dimensional_position_status",
        "VARCHAR"
      ),
      " AS hog_three_dimensional_position_status"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "three_dimensional_alignment_status",
        "VARCHAR"
      ),
      " AS hog_three_dimensional_alignment_status"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "conservation_status",
        "VARCHAR"
      ),
      " AS hog_conservation_status"
    ),
    paste0(
      enriched_hog_support_expression(
        capability$ranking_columns,
        "three_dimensional_position_status",
        "SAME_3D_POCKET_POSITION_SUPPORTED"
      ),
      " ",
      "AS hog_same_3d_pocket_position_supported"
    ),
    paste0(
      enriched_hog_support_expression(
        capability$ranking_columns,
        "three_dimensional_alignment_status",
        "CONSERVED_3D_POCKET_SUPPORTED"
      ),
      " ",
      "AS hog_conserved_3d_pocket_supported"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "minimum_druggability_score",
        "DOUBLE"
      ),
      " AS hog_minimum_druggability_score"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "all_assessed_members_pass_druggability",
        "BOOLEAN"
      ),
      " AS hog_all_assessed_members_pass_druggability"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "structural_species_fraction",
        "DOUBLE"
      ),
      " AS hog_structural_species_fraction"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "mean_minimum_tm_score",
        "DOUBLE"
      ),
      " AS hog_mean_minimum_tm_score"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "mean_pocket_overlap_fraction",
        "DOUBLE"
      ),
      " AS hog_mean_pocket_overlap_fraction"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "median_centroid_distance_angstrom",
        "DOUBLE"
      ),
      " AS hog_median_centroid_distance_angstrom"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "mean_structural_residue_match_fraction",
        "DOUBLE"
      ),
      " AS hog_mean_structural_residue_match_fraction"
    ),
    paste0(
      enriched_hog_value_expression(
        capability$ranking_columns,
        "mean_structural_chemical_group_conservation",
        "DOUBLE"
      ),
      " AS hog_mean_structural_chemical_group_conservation"
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
    "coalesce(s.rice_hog_accessions, '') AS rice_hog_accessions",
    "coalesce(s.rice_hog_entries, '') AS rice_hog_entries",
    "coalesce(s.rice_hog_raw_identifiers, '') AS rice_hog_raw_identifiers",
    "coalesce(s.barley_hog_accessions, '') AS barley_hog_accessions",
    "coalesce(s.barley_hog_entries, '') AS barley_hog_entries",
    "coalesce(s.barley_hog_raw_identifiers, '') AS barley_hog_raw_identifiers",
    "coalesce(s.hog_member_count, 0) AS hog_member_count",
    "coalesce(s.hog_species_count, 0) AS hog_species_count",
    "coalesce(s.hog_human_member_count, 0) AS hog_human_member_count",
    paste0(
      "coalesce(s.hog_arabidopsis_member_count, 0) ",
      "AS hog_arabidopsis_member_count"
    ),
    "coalesce(s.hog_rice_member_count, 0) AS hog_rice_member_count",
    "coalesce(s.hog_barley_member_count, 0) AS hog_barley_member_count",
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
    enriched_hog_member_structural_ctes(
      capability = capability,
      alias = alias
    ),
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
    structural_source <- escape_sql_literal(
      capability$member_structural_relation %||% ""
    )
    structural_sql <- c(
      "p.hog_id IS NOT NULL AS member_structure_assessed",
      paste0(
        "CASE WHEN p.hog_id IS NULL THEN '' ELSE '", structural_source,
        "' END AS member_structural_source"
      ),
      paste0(
        "coalesce(p.candidate_accession, '') AS member_structural_accession"
      ),
      "coalesce(p.species, '') AS member_structural_species",
      "p.pocket_number AS member_pocket_number",
      "p.druggability_score AS member_druggability_score",
      paste0(
        "p.passes_druggability_threshold AS ",
        "member_passes_druggability_threshold"
      ),
      "p.mapping_fraction AS member_pocket_mapping_fraction",
      "p.pocket_plddt_fraction AS member_pocket_plddt_fraction",
      "p.predictor_agreement AS member_predictor_agreement",
      "p.component_selected AS member_pocket_component_selected",
      paste0(
        "coalesce(p.structural_evidence_status, '') AS ",
        "member_structural_evidence_status"
      )
    )
    expressions <- c(expressions, member_sql, structural_sql)
    from_sql <- paste0(
      from_sql,
      " LEFT JOIN member_classes m USING (hog_id) ",
      "LEFT JOIN member_structural_rows p ON p.hog_id = m.hog_id ",
      "AND upper(trim(p.candidate_accession)) = ",
      "upper(trim(m.representative))"
    )
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
    columns %in% enriched_hog_member_structural_columns() ~
      capability$member_structural_relation %||% "structural evidence unavailable",
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
