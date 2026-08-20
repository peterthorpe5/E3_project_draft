#' Grant-facing result-section definitions and bounded query helpers.

result_section_specs <- list(
  final_recommendations = list(
    title = "Final computational recommendations",
    question = paste(
      "Which distinct evolutionary candidate groups should be reviewed in the",
      "ordered top 50, which pass every grant-aligned gate, and how sensitive",
      "are those decisions to the documented alternative gates?"
    ),
    relations = c(
      "top_computational_review_shortlist",
      "top_50_computational_review_shortlist",
      "top_20_computational_review_shortlist",
      "gate_sensitivity_summary",
      "gate_sensitivity_detail",
      "grant_aligned_predicted_candidates",
      "final_evolutionary_candidate_prioritisation",
      "final_evolutionary_group_cluster_contributors",
      "final_candidate_exclusion_audit"
    )
  ),
  candidates = list(
    title = "Candidate prioritisation",
    question = paste(
      "Which candidate E3 groups best satisfy the combined conservation,",
      "domain, expression and structural evidence gates?"
    ),
    relations = c(
      "candidate_master_results",
      "final_candidate_prioritisation",
      "prestructure_ranking",
      "candidate_evidence"
    )
  ),
  orthology = list(
    title = "Cross-species orthology",
    question = paste(
      "Which OrthoFinder groups contain each candidate, which species are",
      "represented and what are the group-member sequences?"
    ),
    relations = c(
      "candidate_orthology",
      "candidate_orthology_summary",
      "candidate_group_member_sequences",
      "orthogroup_membership",
      "hierarchical_membership"
    )
  ),
  domains = list(
    title = "E3 domain support",
    question = paste(
      "Is a catalogued E3-associated domain supported across assessed members,",
      "and where is annotation unavailable?"
    ),
    relations = c("domain_summary", "domain_hits")
  ),
  expression = list(
    title = "Expression support",
    question = paste(
      "Which candidate-group members map to Expression Atlas and show broad",
      "plant expression support?"
    ),
    relations = c(
      "candidate_expression_context_summary",
      "candidate_expression_summary",
      "candidate_expression_mapping",
      "candidate_identifier_aliases"
    )
  ),
  ligandability = list(
    title = "Ligandability",
    question = paste(
      "Which shortlisted proteins have reusable, high-confidence pockets",
      "supported by fpocket and P2Rank evidence?"
    ),
    relations = c(
      "selected_pockets",
      "ranked_member_pockets",
      "structural_prediction_status",
      "structural_analysis_accessions"
    )
  ),
  pocket_conservation = list(
    title = "Pocket conservation",
    question = paste(
      "Is the pocket-bearing region conserved across candidate-group members,",
      "and can pocket residues be traced to FASTA coordinates?"
    ),
    relations = c(
      "pocket_conservation_summary",
      "pocket_conservation_members",
      "pocket_sequence_coordinates",
      "ranked_pocket_sequence_coordinates"
    )
  ),
  structural_alignment = list(
    title = "3D pocket alignment",
    question = paste(
      "Do US-align and TM-align support an equivalent 3D pocket position and",
      "stronger local pocket-structure conservation?"
    ),
    relations = c(
      "structural_alignment_summary",
      "structural_pocket_sensitivity_group_summary",
      "structural_pocket_sensitivity_member_summary",
      "structural_pocket_sensitivity_comparisons",
      "structural_pocket_sensitivity_residue_matches",
      "structural_pocket_comparisons",
      "structural_pocket_residue_matches",
      "structural_alignments"
    )
  ),
  computational_chemistry = list(
    title = "Structure-guided computational chemistry",
    question = paste(
      "Which structurally usable and evolutionarily supported pockets are",
      "ready for chemistry review, which gates determine that status, and",
      "what residue-derived pharmacophore features support each decision?"
    ),
    relations = c(
      "integrated_candidate_evidence",
      "group_pharmacophore_summary",
      "chemistry_target_manifest",
      "threshold_sensitivity",
      "threshold_sensitivity_one_at_a_time",
      "ranked_member_pocket_evidence",
      "pocket_pharmacophore_features",
      "fragment_pharmacophore_ranking",
      "fragment_properties"
    )
  ),
  provenance = list(
    title = "Provenance and quality control",
    question = paste(
      "Which release, files, checksums and evidence limitations underpin the",
      "displayed result?"
    ),
    relations = c("resource_metadata", "resource_relation_catalog")
  )
)

#' Infer the app section for an arbitrary relation.
#'
#' @param relation Relation name.
#' @return Stable section identifier.
infer_result_section <- function(relation) {
  for (section in names(result_section_specs)) {
    if (relation %in% result_section_specs[[section]]$relations) {
      return(section)
    }
  }
  text <- tolower(relation)
  if (grepl("chemistry|pharmacophore|fragment", text)) {
    return("computational_chemistry")
  }
  if (grepl("align|tm_score|centroid", text)) {
    return("structural_alignment")
  }
  if (grepl("pocket_conservation|pocket_sequence", text)) {
    return("pocket_conservation")
  }
  if (grepl("orthogroup|orthology|hierarchical", text)) {
    return("orthology")
  }
  if (grepl("domain|interpro|pfam", text)) {
    return("domains")
  }
  if (grepl("expression|atlas", text)) {
    return("expression")
  }
  if (grepl("pocket|fpocket|p2rank|ligand", text)) {
    return("ligandability")
  }
  if (grepl("manifest|metadata|provenance|validation|catalog", text)) {
    return("provenance")
  }
  if (grepl("candidate|cluster|ranking", text)) {
    return("candidates")
  }
  "other"
}

#' Return available relations for one result section.
#'
#' @param relation_names Available relation names.
#' @param section Section identifier.
#' @return Ordered character vector of matching relations.
relations_for_result_section <- function(relation_names, section) {
  if (!section %in% names(result_section_specs)) {
    stop(paste0("Unknown result section: ", section), call. = FALSE)
  }
  preferred <- result_section_specs[[section]]$relations
  selected <- preferred[preferred %in% relation_names]
  if (section == "provenance") {
    inferred <- relation_names[
      vapply(relation_names, infer_result_section, character(1L)) == section
    ]
    selected <- unique(c(selected, inferred))
  }
  selected
}

#' Select concise default columns for a grant-facing section.
#'
#' @param section Section identifier.
#' @param available Available relation columns.
#' @return Default selected columns.
default_result_columns <- function(section, available) {
  preferences <- list(
    final_recommendations = c(
      "final_evolutionary_rank", "structurally_supported_rank",
      "boss_review_status", "grant_aligned_prediction_status",
      "evolutionary_group_key", "primary_group_type", "primary_group_id",
      "contributing_deepclust_cluster_count",
      "contributing_deepclust_cluster_ids",
      "lead_cluster_id", "final_score", "target_species_fraction",
      "domain_species_fraction", "expression_species_fraction",
      "selected_pocket_count", "structural_species_fraction",
      "inclusion_reasons", "exclusion_reasons", "missing_evidence"
    ),
    candidates = c(
      "final_rank", "computational_rank", "recommendation_status",
      "grant_aligned_prediction_status", "cluster_id", "primary_group_type",
      "primary_group_id", "candidate_accession_count", "candidate_accessions",
      "orthofinder_orthogroup_ids", "orthofinder_hierarchical_group_ids",
      "orthofinder_group_member_count", "orthofinder_group_species_count",
      "prestructure_score", "final_score", "evidence_completeness_fraction",
      "target_species_count", "target_species_total", "target_species_fraction",
      "target_species_present", "target_species_missing",
      "mandatory_species_count", "mandatory_species_total",
      "mandatory_species_fraction", "mandatory_species_missing",
      "domain_supported_species_count", "domain_assessed_species_count",
      "domain_annotation_coverage_fraction", "domain_species_fraction",
      "domain_supported_species", "domain_unavailable_species",
      "expression_supported_species_count", "expression_assessed_species_count",
      "expression_evidence_coverage_fraction", "expression_species_fraction",
      "expression_supported_species", "expression_unavailable_species",
      "structural_species_fraction", "minimum_druggability_score",
      "conservation_status", "three_dimensional_alignment_status",
      "grant_aligned_prestructure_pass", "grant_aligned_final_pass",
      "inclusion_reasons", "exclusion_reasons", "missing_evidence",
      "structural_exclusion_reasons"
    ),
    orthology = c(
      "cluster_id", "record_type", "group_id", "orthogroup_id",
      "species", "parsed_accession", "member_accession", "sequence_length",
      "orthofinder_orthogroup_ids", "orthofinder_hierarchical_group_ids",
      "orthofinder_group_member_count", "orthofinder_group_species_count"
    ),
    domains = c(
      "cluster_id", "member_accession", "species_column",
      "domain_support_status", "e3_families",
      "annotation_availability_status", "domain_species_fraction",
      "domain_annotation_coverage_fraction", "domain_supported_species",
      "domain_unavailable_species"
    ),
    expression = c(
      "cluster_id", "member_accession", "species_column", "mapping_status",
      "gene_id", "experiment_accession", "sample_or_condition", "organism_part",
      "developmental_stage", "condition", "treatment",
      "metadata_status", "expression_unit", "expression_value",
      "expression_minimum", "expression_lower_quartile",
      "expression_median", "expression_upper_quartile", "expression_maximum",
      "expression_positive",
      "broad_expression_supported", "evidence_status",
      "expression_species_fraction", "expression_evidence_coverage_fraction",
      "expression_supported_species", "expression_unavailable_species"
    ),
    ligandability = c(
      "cluster_id", "candidate_accession", "species_column", "pocket_number",
      "druggability_score", "p2rank_score", "mapping_fraction",
      "structural_evidence_status", "ligandability_score",
      "minimum_druggability_score", "mean_pocket_plddt_fraction",
      "predictor_agreement_fraction", "selected_pocket_count"
    ),
    pocket_conservation = c(
      "cluster_id", "primary_group_id", "candidate_accession",
      "species_column", "conservation_status", "conserved_pocket_score",
      "fasta_position", "sequence_coordinate_status",
      "pocket_conservation_score", "mean_pairwise_region_overlap",
      "mean_chemical_group_conservation", "pocket_conservation_member_count"
    ),
    structural_alignment = c(
      "cluster_id", "primary_group_id", "alignment_tool",
      "position_alignment_status", "alignment_status",
      "mean_minimum_tm_score", "mean_pocket_overlap_fraction",
      "median_centroid_distance_angstrom",
      "three_dimensional_position_status",
      "three_dimensional_alignment_status",
      "mean_structural_residue_match_fraction",
      "mean_structural_chemical_group_conservation"
    ),
    computational_chemistry = c(
      "evolutionary_group_rank", "evolutionary_group_key",
      "primary_group_type", "primary_group_id", "cluster_id",
      "candidate_accession", "species_column", "pocket_number",
      "druggability_score", "mapped_residue_count",
      "pocket_plddt_fraction", "conserved_component_fraction",
      "chemical_conservation_fraction", "uniqueness_score",
      "chemistry_review_tier", "chemistry_handoff_status",
      "chemistry_handoff_failure_reasons", "feature_type",
      "feature_count", "fragment_id", "compatibility_score"
    ),
    provenance = c(
      "relation_name", "app_section", "row_granularity", "source_parquet",
      "resource_name", "package_version", "run_name", "configuration_digest"
    )
  )
  selected <- preferences[[section]]
  selected <- selected[selected %in% available]
  if (length(selected) == 0L) {
    selected <- head(available, 12L)
  }
  selected
}

#' Build a bounded selected-column relation query.
#'
#' @param relation Relation name.
#' @param selected_columns Columns selected in the UI.
#' @param max_rows Maximum rows.
#' @param alias Attached resource alias.
#' @return SQL query.
build_selected_result_query <- function(
  relation,
  selected_columns,
  max_rows = 1000L,
  alias = "e3_resource"
) {
  if (length(selected_columns) == 0L) {
    stop("Select at least one result column.", call. = FALSE)
  }
  safe_alias <- sanitise_duckdb_alias(alias)
  columns <- paste(
    vapply(selected_columns, quote_duckdb_identifier, character(1L)),
    collapse = ", "
  )
  safe_relation <- quote_duckdb_identifier(relation)
  paste0(
    "SELECT ", columns, " FROM ", safe_alias, ".main.", safe_relation,
    " LIMIT ", max(1L, as.integer(max_rows))
  )
}

#' Collect selected columns from one result relation.
#'
#' @param resource_source Flexible result source.
#' @param relation Relation name.
#' @param selected_columns Selected columns.
#' @param max_rows Maximum rows.
#' @return Collected bounded tibble.
collect_selected_result <- function(
  resource_source,
  relation,
  selected_columns,
  max_rows = 1000L
) {
  columns <- collect_resource_columns(
    duckdb_path = resource_source,
    view_name = relation
  )
  available <- as.character(columns$column_name)
  unknown <- setdiff(selected_columns, available)
  if (length(unknown) > 0L) {
    stop(
      paste0("Unknown selected columns: ", paste(unknown, collapse = ", ")),
      call. = FALSE
    )
  }
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_selected_result_query(
      relation = relation,
      selected_columns = selected_columns,
      max_rows = max_rows
    )
  )
}

#' Collect bounded distinct text values for a filter control.
#'
#' @param resource_source Flexible result source.
#' @param relation Relation name.
#' @param column Text column.
#' @param max_values Maximum distinct values.
#' @return Character vector.
collect_distinct_result_values <- function(
  resource_source,
  relation,
  column,
  max_values = 1000L
) {
  available <- as.character(
    collect_resource_columns(resource_source, relation)$column_name
  )
  if (!column %in% available) {
    return(character())
  }
  safe_relation <- quote_duckdb_identifier(relation)
  safe_column <- quote_duckdb_identifier(column)
  query <- paste0(
    "SELECT DISTINCT CAST(", safe_column, " AS VARCHAR) AS value FROM ",
    "e3_resource.main.", safe_relation, " WHERE COALESCE(TRIM(CAST(",
    safe_column, " AS VARCHAR)), '') <> '' ORDER BY value LIMIT ",
    max(1L, as.integer(max_values))
  )
  result <- collect_resource_query(resource_source, query)
  as.character(result$value)
}

#' Build a bounded candidate-expression context query.
#'
#' @param relation Relation name.
#' @param selected_columns Display columns.
#' @param available_columns Relation columns.
#' @param species Optional exact species label.
#' @param tissue Optional exact organism-part label.
#' @param metadata_status Optional exact metadata-status label.
#' @param expression_positive Optional logical expression-threshold state.
#' @param search Optional partial identifier search.
#' @param max_rows Maximum rows.
#' @return SQL query.
build_filtered_expression_query <- function(
  relation,
  selected_columns,
  available_columns,
  species = "",
  tissue = "",
  metadata_status = "",
  expression_positive = "",
  search = "",
  max_rows = 1000L
) {
  unknown <- setdiff(selected_columns, available_columns)
  if (length(unknown) > 0L) {
    stop(
      paste0("Unknown selected columns: ", paste(unknown, collapse = ", ")),
      call. = FALSE
    )
  }
  predicates <- character()
  exact_filter <- function(column, value) {
    if (!nzchar(trimws(value)) || !column %in% available_columns) {
      return(character())
    }
    paste0(
      "CAST(", quote_duckdb_identifier(column), " AS VARCHAR) = '",
      escape_sql_literal(trimws(value)), "'"
    )
  }
  predicates <- c(
    predicates,
    exact_filter("species_column", species),
    exact_filter("organism_part", tissue),
    exact_filter("metadata_status", metadata_status)
  )
  expression_positive <- trimws(expression_positive)
  if (
    nzchar(expression_positive) &&
      "expression_positive" %in% available_columns
  ) {
    if (!expression_positive %in% c("true", "false")) {
      stop(
        "expression_positive must be empty, 'true', or 'false'.",
        call. = FALSE
      )
    }
    predicates <- c(
      predicates,
      paste0(
        "\"expression_positive\" = ",
        toupper(expression_positive)
      )
    )
  }
  search_terms <- parse_expression_search_terms(search)
  if (length(search_terms) > 0L) {
    searchable <- intersect(
      c(
        "cluster_id", "primary_group_id", "member_accession",
        "member_identifier", "gene_id", "gene_name"
      ),
      available_columns
    )
    if (length(searchable) > 0L) {
      term_predicates <- vapply(search_terms, function(term) {
        safe_term <- escape_sql_literal(tolower(term))
        paste0(
          "(",
          paste(
            paste0(
              "instr(lower(coalesce(CAST(",
              vapply(searchable, quote_duckdb_identifier, character(1L)),
              " AS VARCHAR), '')), '", safe_term, "') > 0"
            ),
            collapse = " OR "
          ),
          ")"
        )
      }, character(1L))
      predicates <- c(
        predicates,
        paste0("(", paste(term_predicates, collapse = " OR "), ")")
      )
    }
  }
  query <- build_selected_result_query(
    relation = relation,
    selected_columns = selected_columns,
    max_rows = max_rows
  )
  if (length(predicates) == 0L) {
    return(query)
  }
  sub(
    " LIMIT ",
    paste0(" WHERE ", paste(predicates, collapse = " AND "), " LIMIT "),
    query,
    fixed = TRUE
  )
}

#' Parse one or more expression identifiers or names.
#'
#' @param value Text separated by semicolons, commas, tabs or new lines.
#' @param maximum_terms Defensive maximum number of unique values.
#' @return Ordered unique expression search terms.
parse_expression_search_terms <- function(value, maximum_terms = 50L) {
  if (
    length(maximum_terms) != 1L ||
      is.na(maximum_terms) ||
      maximum_terms < 1L
  ) {
    stop("Expression search maximum_terms must be a positive integer.", call. = FALSE)
  }
  if (length(value) == 0L || is.na(value[[1L]])) return(character())
  terms <- unlist(strsplit(as.character(value[[1L]]), "[\r\n\t,;]+"))
  terms <- trimws(terms)
  terms <- terms[nzchar(terms)]
  terms <- terms[!duplicated(tolower(terms))]
  if (length(terms) > as.integer(maximum_terms)) {
    stop(
      paste0("Expression search accepts at most ", maximum_terms, " terms."),
      call. = FALSE
    )
  }
  terms
}

#' Collect a filtered candidate-expression context result.
#'
#' @param resource_source Flexible result source.
#' @param relation Relation name.
#' @param selected_columns Display columns.
#' @param available_columns Relation columns.
#' @param species Optional exact species label.
#' @param tissue Optional exact organism-part label.
#' @param metadata_status Optional exact metadata-status label.
#' @param expression_positive Optional logical expression-threshold state.
#' @param search Optional partial identifier search.
#' @param max_rows Maximum rows.
#' @return Collected bounded tibble.
collect_filtered_expression_result <- function(
  resource_source,
  relation,
  selected_columns,
  available_columns,
  species = "",
  tissue = "",
  metadata_status = "",
  expression_positive = "",
  search = "",
  max_rows = 1000L
) {
  collect_resource_query(
    resource_source,
    build_filtered_expression_query(
      relation = relation,
      selected_columns = selected_columns,
      available_columns = available_columns,
      species = species,
      tissue = tissue,
      metadata_status = metadata_status,
      expression_positive = expression_positive,
      search = search,
      max_rows = max_rows
    )
  )
}

#' Build a compact grant-overview query.
#'
#' @param relation Candidate or evolutionary-group relation.
#' @param available Available columns.
#' @param alias Attached resource alias.
#' @return SQL query.
build_grant_overview_query <- function(
  relation,
  available,
  alias = "e3_resource"
) {
  safe_alias <- sanitise_duckdb_alias(alias)
  safe_relation <- quote_duckdb_identifier(relation)
  source_relation <- paste0(safe_alias, ".main.", safe_relation)
  if (
    relation %in% c(
      "candidate_master_results",
      "final_candidate_prioritisation",
      "prestructure_ranking"
    ) &&
      all(c("primary_group_type", "primary_group_id") %in% available)
  ) {
    order_columns <- c("final_rank", "computational_rank", "cluster_id")
    order_columns <- order_columns[order_columns %in% available]
    order_sql <- if (length(order_columns) > 0L) {
      paste(
        vapply(order_columns, quote_duckdb_identifier, character(1L)),
        collapse = ", "
      )
    } else {
      quote_duckdb_identifier("primary_group_id")
    }
    source_relation <- paste0(
      "(SELECT * EXCLUDE (_e3_group_row) FROM (SELECT *, ROW_NUMBER() OVER (",
      "PARTITION BY primary_group_type, primary_group_id ORDER BY ", order_sql,
      ") AS _e3_group_row FROM ", source_relation,
      " WHERE COALESCE(CAST(primary_group_type AS VARCHAR), '') <> '' ",
      "AND COALESCE(CAST(primary_group_id AS VARCHAR), '') <> '') ",
      "WHERE _e3_group_row = 1)"
    )
  }
  true_count <- function(column) {
    if (!column %in% available) {
      return("0")
    }
    paste0(
      "SUM(CASE WHEN COALESCE(CAST(", quote_duckdb_identifier(column),
      " AS BOOLEAN), FALSE) THEN 1 ELSE 0 END)"
    )
  }
  structural_count <- if ("three_dimensional_alignment_status" %in% available) {
    paste0(
      "SUM(CASE WHEN COALESCE(CAST(three_dimensional_alignment_status AS VARCHAR), ",
      "'NOT_ASSESSED') <> 'NOT_ASSESSED' THEN 1 ELSE 0 END)"
    )
  } else {
    "0"
  }
  prestructure <- if ("grant_aligned_prestructure_pass" %in% available) {
    true_count("grant_aligned_prestructure_pass")
  } else {
    true_count("grant_aligned_stringent_pass")
  }
  paste0(
    "SELECT COUNT(*) AS candidate_count, ", prestructure,
    " AS prestructure_pass_count, ", true_count("grant_aligned_final_pass"),
    " AS final_pass_count, ", structural_count,
    " AS structural_assessed_count FROM ", source_relation
  )
}

#' Select the authoritative relation for grant-overview group counts.
#'
#' The completed integrated resource contains a definitive one-row-per-
#' evolutionary-group relation. Cluster-level fallbacks are deduplicated by
#' `build_grant_overview_query()` when only a master Parquet is available.
#'
#' @param relation_names Available relation names.
#' @return Relation name or an empty string.
select_grant_overview_relation <- function(relation_names) {
  preferred <- c(
    "final_evolutionary_candidate_prioritisation",
    "evolutionary_candidate_group_ranking",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "prestructure_ranking"
  )
  selected <- preferred[preferred %in% relation_names]
  if (length(selected) == 0L) {
    return("")
  }
  selected[[1L]]
}

#' Collect compact Milestone 1/2 counts.
#'
#' @param resource_source Flexible result source.
#' @return One-row tibble.
collect_grant_overview <- function(resource_source) {
  relations <- collect_resource_view_names(resource_source)
  relation <- select_grant_overview_relation(relation_names = relations)
  if (!nzchar(relation)) {
    return(tibble::tibble(
      candidate_count = 0,
      prestructure_pass_count = 0,
      final_pass_count = 0,
      structural_assessed_count = 0,
      source_relation = NA_character_
    ))
  }
  columns <- collect_resource_columns(resource_source, relation)
  result <- collect_resource_query(
    duckdb_path = resource_source,
    query = build_grant_overview_query(
      relation = relation,
      available = as.character(columns$column_name)
    )
  )
  result$source_relation <- relation
  result
}
