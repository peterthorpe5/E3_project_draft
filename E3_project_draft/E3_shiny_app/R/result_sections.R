#' Grant-facing result-section definitions and bounded query helpers.

result_section_specs <- list(
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
      "hierarchical_membership",
      "candidate_master_results"
    )
  ),
  domains = list(
    title = "E3 domain support",
    question = paste(
      "Is a catalogued E3-associated domain supported across assessed members,",
      "and where is annotation unavailable?"
    ),
    relations = c("domain_summary", "domain_hits", "candidate_master_results")
  ),
  expression = list(
    title = "Expression support",
    question = paste(
      "Which candidate-group members map to Expression Atlas and show broad",
      "plant expression support?"
    ),
    relations = c(
      "candidate_expression_summary",
      "candidate_expression_mapping",
      "candidate_identifier_aliases",
      "candidate_master_results"
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
      "structural_prediction_status",
      "structural_analysis_accessions",
      "candidate_master_results"
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
      "candidate_master_results"
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
      "structural_pocket_comparisons",
      "structural_pocket_residue_matches",
      "structural_alignments",
      "candidate_master_results"
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
    candidates = c(
      "final_rank", "recommendation_status", "cluster_id",
      "primary_group_id", "orthofinder_orthogroup_ids",
      "candidate_accessions", "final_score", "target_species_fraction",
      "domain_species_fraction", "expression_species_fraction",
      "structural_species_fraction", "missing_evidence"
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

#' Build a compact grant-overview query.
#'
#' @param relation Candidate-level relation.
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
      "SUM(CASE WHEN COALESCE(three_dimensional_alignment_status, ",
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
    " AS structural_assessed_count FROM ", safe_alias, ".main.", safe_relation
  )
}

#' Collect compact Milestone 1/2 counts.
#'
#' @param resource_source Flexible result source.
#' @return One-row tibble.
collect_grant_overview <- function(resource_source) {
  relations <- collect_resource_view_names(resource_source)
  candidate_relation <- c(
    "candidate_master_results",
    "final_candidate_prioritisation",
    "prestructure_ranking",
    "candidate_evidence"
  )
  candidate_relation <- candidate_relation[candidate_relation %in% relations]
  if (length(candidate_relation) == 0L) {
    return(tibble::tibble(
      candidate_count = 0,
      prestructure_pass_count = 0,
      final_pass_count = 0,
      structural_assessed_count = 0
    ))
  }
  relation <- candidate_relation[[1L]]
  columns <- collect_resource_columns(resource_source, relation)
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_grant_overview_query(
      relation = relation,
      available = as.character(columns$column_name)
    )
  )
}
