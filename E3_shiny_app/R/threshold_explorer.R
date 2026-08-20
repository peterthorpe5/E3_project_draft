#' Configurable candidate-threshold evaluation helpers.
#'
#' These helpers deliberately re-evaluate only fields already present in the
#' completed integrated resource. They do not rerun sequence, pocket or
#' structural calculations.

RECORDED_MINIMUM_DRUGGABILITY_SCORE <- 0.50

#' Return optional post-hoc score-threshold specifications.
#'
#' These gates use aggregate values already stored in the completed resource.
#' They are disabled by default and do not rerun pocket, alignment or structure
#' calculations.
#'
#' @return Named list of optional threshold specifications.
additional_threshold_specs <- function() {
  list(
    evidence_completeness_fraction = list(
      setting = "minimum_evidence_completeness_fraction",
      label = "Minimum evidence-completeness fraction",
      default = 0.80,
      section = "prestructure",
      help = paste(
        "Optional post-hoc gate on the recorded completeness summary.",
        "It does not create missing evidence."
      )
    ),
    mean_pocket_plddt_fraction = list(
      setting = "minimum_mean_pocket_plddt_fraction",
      label = "Minimum mean pocket pLDDT fraction",
      default = 0.70,
      section = "structural",
      help = paste(
        "Optional group-level gate on the recorded mean fraction of selected",
        "pocket residues meeting the production pLDDT criterion."
      )
    ),
    predictor_agreement_fraction = list(
      setting = "minimum_predictor_agreement_fraction",
      label = "Minimum pocket-predictor agreement fraction",
      default = 0.50,
      section = "structural",
      help = paste(
        "Optional group-level gate on agreement between the linked pocket",
        "prediction signals; it is not experimental binding evidence."
      )
    ),
    mean_pairwise_region_overlap = list(
      setting = "minimum_mean_pairwise_region_overlap",
      label = "Minimum mean pocket-region overlap",
      default = 0.25,
      section = "structural",
      help = paste(
        "Optional gate on the recorded sequence-alignment overlap summary.",
        "It does not recalculate the conserved component."
      )
    ),
    mean_minimum_tm_score = list(
      setting = "minimum_mean_minimum_tm_score",
      label = "Minimum mean cross-aligner TM-score",
      default = 0.50,
      section = "structural",
      help = paste(
        "Optional post-hoc gate on the recorded group mean of the lower",
        "US-align/TM-align score."
      )
    ),
    mean_pocket_overlap_fraction = list(
      setting = "minimum_mean_pocket_overlap_fraction",
      label = "Minimum mean 3D pocket-overlap fraction",
      default = 0.50,
      section = "structural",
      help = paste(
        "Optional post-hoc gate on the recorded symmetric 3D pocket-overlap",
        "summary; it does not rerun structural superposition."
      )
    ),
    mean_structural_chemical_group_conservation = list(
      setting = "minimum_mean_structural_chemical_group_conservation",
      label = "Minimum mean structural chemical-group conservation",
      default = 0.60,
      section = "structural",
      help = paste(
        "Optional post-hoc gate on the recorded biochemical-class agreement",
        "among structurally matched pocket residues."
      )
    )
  )
}

#' Return user-facing choices for optional score thresholds.
#'
#' @return Named character vector suitable for a Shiny multiple selector.
additional_threshold_choices <- function() {
  specifications <- additional_threshold_specs()
  stats::setNames(
    names(specifications),
    vapply(specifications, function(value) value$label, character(1))
  )
}

#' Return the current grant-aligned thresholds.
#'
#' @return Named list of numeric thresholds and categorical requirements.
current_threshold_defaults <- function() {
  optional <- additional_threshold_specs()
  defaults <- list(
    target_species_fraction = 0.90,
    mandatory_species_fraction = 1.00,
    domain_species_fraction = 0.80,
    expression_species_fraction = 0.80,
    structural_species_fraction = 0.75,
    minimum_druggability_score = RECORDED_MINIMUM_DRUGGABILITY_SCORE,
    require_domain_evidence = TRUE,
    require_expression_evidence = TRUE,
    require_conserved_region = TRUE,
    require_all_member_mapping = TRUE,
    require_strict_3d = TRUE,
    include_not_assessed = FALSE,
    additional_thresholds = character(),
    mode = "structural",
    result_scope = "passing"
  )
  for (specification in optional) {
    defaults[[specification$setting]] <- specification$default
  }
  defaults
}

#' Validate and complete threshold settings.
#'
#' @param settings Named list overriding `current_threshold_defaults()`.
#' @return Complete validated threshold settings.
normalise_threshold_settings <- function(settings = list()) {
  if (!is.list(settings)) {
    stop("Threshold settings must be supplied as a named list.", call. = FALSE)
  }
  values <- utils::modifyList(current_threshold_defaults(), settings)
  numeric_fields <- c(
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    vapply(
      additional_threshold_specs(),
      function(value) value$setting,
      character(1)
    )
  )
  for (field in numeric_fields) {
    value <- suppressWarnings(as.numeric(values[[field]]))
    if (length(value) != 1L || is.na(value) || value < 0 || value > 1) {
      stop(
        paste0("Threshold `", field, "` must be a number from 0 to 1."),
        call. = FALSE
      )
    }
    values[[field]] <- value
  }

  logical_fields <- c(
    "require_domain_evidence",
    "require_expression_evidence",
    "require_conserved_region",
    "require_all_member_mapping",
    "require_strict_3d",
    "include_not_assessed"
  )
  for (field in logical_fields) {
    value <- values[[field]]
    if (length(value) != 1L || is.na(value)) {
      stop(
        paste0("Threshold option `", field, "` must be TRUE or FALSE."),
        call. = FALSE
      )
    }
    values[[field]] <- isTRUE(as.logical(value))
  }

  values$mode <- as.character(values$mode[[1L]])
  if (!values$mode %in% c("prestructure", "structural")) {
    stop("Threshold mode must be `prestructure` or `structural`.", call. = FALSE)
  }
  values$result_scope <- as.character(values$result_scope[[1L]])
  if (!values$result_scope %in% c("passing", "pass_near", "all")) {
    stop(
      "Result scope must be `passing`, `pass_near` or `all`.",
      call. = FALSE
    )
  }
  selected_additional <- unique(as.character(values$additional_thresholds))
  allowed_additional <- names(additional_threshold_specs())
  if (any(!selected_additional %in% allowed_additional)) {
    stop(
      "Additional thresholds contain an unsupported score field.",
      call. = FALSE
    )
  }
  values$additional_thresholds <- selected_additional
  values
}

#' Build matched pre-structure and structural settings.
#'
#' Both result sets use the same thresholds and row scope. Only the evaluation
#' mode differs, preventing the two displayed lists from silently drifting onto
#' different control values.
#'
#' @param settings Named shared threshold settings.
#' @return Named list containing `prestructure` and `structural` settings.
paired_threshold_settings <- function(settings = list()) {
  shared <- normalise_threshold_settings(settings = settings)
  list(
    prestructure = normalise_threshold_settings(
      settings = utils::modifyList(shared, list(mode = "prestructure"))
    ),
    structural = normalise_threshold_settings(
      settings = utils::modifyList(shared, list(mode = "structural"))
    )
  )
}

#' Return settings that vary only the final druggability threshold.
#'
#' @param minimum_druggability_score Inclusive minimum score required for every
#'   assessed member.
#' @param result_scope Candidate statuses to return.
#' @return Validated structural threshold settings.
final_druggability_settings <- function(
  minimum_druggability_score,
  result_scope = "passing"
) {
  normalise_threshold_settings(list(
    minimum_druggability_score = minimum_druggability_score,
    mode = "structural",
    result_scope = result_scope
  ))
}

#' Report missing fields needed by the focused final-gate sensitivity analysis.
#'
#' @param available Available relation columns.
#' @return Character vector of missing fields or evidence-field alternatives.
final_druggability_source_missing_columns <- function(available) {
  required <- c(
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    "all_assessed_members_pass_mapping",
    "conservation_status",
    "three_dimensional_alignment_status"
  )
  evidence_families <- list(
    c("domain_assessed_species_count", "domain_evidence_row_count"),
    c("expression_assessed_species_count", "expression_evidence_row_count")
  )
  missing <- required[!required %in% available]
  for (family in evidence_families) {
    if (!any(family %in% available)) {
      missing <- c(missing, paste(family, collapse = " or "))
    }
  }
  missing
}

#' Choose stable identity columns shared by two final-gate pass lists.
#'
#' @param recorded Recorded pass-list column names.
#' @param selected Sensitivity pass-list column names.
#' @return Character vector of identity columns.
final_druggability_identity_columns <- function(recorded, selected) {
  shared <- intersect(recorded, selected)
  groups <- list(
    "evolutionary_group_key",
    c("primary_group_type", "primary_group_id"),
    "primary_group_id",
    "lead_cluster_id",
    "cluster_id"
  )
  for (group in groups) {
    if (all(group %in% shared)) {
      return(group)
    }
  }
  stop(
    "Final-gate sensitivity results lack a stable candidate identity.",
    call. = FALSE
  )
}

#' Build null-safe candidate identity keys.
#'
#' @param data Candidate data frame.
#' @param columns Stable identity columns.
#' @return Character vector with one key per row.
final_druggability_identity_keys <- function(data, columns) {
  if (nrow(data) == 0L) {
    return(character())
  }
  values <- data[, columns, drop = FALSE]
  values[] <- lapply(values, function(value) {
    result <- as.character(value)
    result[is.na(result)] <- ""
    result
  })
  vapply(
    seq_len(nrow(values)),
    function(index) paste(values[index, , drop = TRUE], collapse = "\u001f"),
    character(1)
  )
}

#' Compare recorded and selected final-gate pass lists.
#'
#' @param recorded Groups passing every gate at the recorded 0.50 threshold.
#' @param selected Groups passing the same gates at the selected threshold.
#' @return List containing an annotated selected list and concise changed rows.
compare_final_druggability_passes <- function(recorded, selected) {
  if (!is.data.frame(recorded) || !is.data.frame(selected)) {
    stop("Final-gate pass lists must be data frames.", call. = FALSE)
  }
  identity_columns <- final_druggability_identity_columns(
    recorded = names(recorded),
    selected = names(selected)
  )
  recorded_keys <- final_druggability_identity_keys(recorded, identity_columns)
  selected_keys <- final_druggability_identity_keys(selected, identity_columns)

  annotated <- selected
  annotated$sensitivity_change <- as.character(ifelse(
    selected_keys %in% recorded_keys,
    "RECORDED_PASS",
    "ENTERS_AT_SELECTED_THRESHOLD"
  ))
  annotated <- annotated[, c(
    "sensitivity_change",
    setdiff(names(annotated), "sensitivity_change")
  ), drop = FALSE]

  entering <- annotated[
    annotated$sensitivity_change == "ENTERS_AT_SELECTED_THRESHOLD",
    ,
    drop = FALSE
  ]
  leaving <- recorded[!recorded_keys %in% selected_keys, , drop = FALSE]
  leaving$sensitivity_change <- rep(
    "LEAVES_AT_SELECTED_THRESHOLD",
    nrow(leaving)
  )
  leaving <- leaving[, c(
    "sensitivity_change",
    setdiff(names(leaving), "sensitivity_change")
  ), drop = FALSE]
  changes <- dplyr::bind_rows(entering, leaving)
  concise <- unique(c(
    "sensitivity_change",
    "final_evolutionary_rank",
    "final_rank",
    identity_columns,
    "lead_cluster_id",
    "candidate_accessions",
    "minimum_druggability_score",
    "final_score"
  ))
  changes <- changes[, concise[concise %in% names(changes)], drop = FALSE]
  list(
    selected = tibble::as_tibble(annotated),
    changes = tibble::as_tibble(changes)
  )
}

#' Select the best relation for interactive threshold evaluation.
#'
#' @param relation_names Available relation names.
#' @return Relation name or an empty string.
select_threshold_relation <- function(relation_names) {
  preferred <- c(
    "final_evolutionary_candidate_prioritisation",
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

#' Select the preferred member-level retained-pocket relation.
#'
#' @param relation_names Available relation names.
#' @return Relation name or an empty string.
select_member_druggability_relation <- function(relation_names) {
  preferred <- c("selected_pockets", "ranked_member_pockets")
  selected <- preferred[preferred %in% relation_names]
  if (length(selected) == 0L) {
    return("")
  }
  selected[[1L]]
}

#' Build a bounded query for selected-pocket scores in lead clusters.
#'
#' @param relation Member-level pocket relation.
#' @param available Available columns in the relation.
#' @param cluster_ids Exact lead cluster identifiers.
#' @param max_rows Hard row limit.
#' @return DuckDB SQL query.
build_member_druggability_query <- function(
  relation,
  available,
  cluster_ids,
  max_rows = 10000L
) {
  max_rows <- suppressWarnings(as.integer(max_rows))
  if (length(max_rows) != 1L || is.na(max_rows) || max_rows < 1L ||
      max_rows > 100000L) {
    stop(
      "Maximum member druggability rows must be between 1 and 100000.",
      call. = FALSE
    )
  }
  identifiers <- unique(trimws(as.character(cluster_ids)))
  identifiers <- identifiers[!is.na(identifiers) & nzchar(identifiers)]
  if (length(identifiers) == 0L) {
    stop("At least one lead cluster is required for the box plot.", call. = FALSE)
  }
  if (length(identifiers) > 2000L) {
    stop("Member druggability query accepts at most 2000 clusters.", call. = FALSE)
  }
  required <- c("cluster_id", "druggability_score")
  missing <- setdiff(required, available)
  if (length(missing) > 0L) {
    stop(
      paste0(
        relation,
        " is missing member druggability fields: ",
        paste(missing, collapse = ", "),
        "."
      ),
      call. = FALSE
    )
  }
  accessions <- c(
    "member_accession",
    "candidate_accession",
    "parsed_accession",
    "accession"
  )
  accession <- accessions[accessions %in% available]
  if (length(accession) == 0L) {
    stop(
      paste0(relation, " has no recognised member accession field."),
      call. = FALSE
    )
  }
  accession <- accession[[1L]]
  selection_filter <- "TRUE"
  if (identical(relation, "ranked_member_pockets")) {
    if ("selection_rank" %in% available) {
      selection_filter <- "TRY_CAST(selection_rank AS INTEGER) = 1"
    } else if ("pocket_rank" %in% available) {
      selection_filter <- "TRY_CAST(pocket_rank AS INTEGER) = 1"
    } else if ("selected_for_scoring" %in% available) {
      selection_filter <- paste(
        "COALESCE(TRY_CAST(selected_for_scoring AS BOOLEAN), FALSE)"
      )
    } else {
      stop(
        "ranked_member_pockets lacks a safe rank-one selection field.",
        call. = FALSE
      )
    }
  }
  species_sql <- if ("species_column" %in% available) {
    paste0(
      "COALESCE(NULLIF(trim(CAST(species_column AS VARCHAR)), ''), 'Unknown')"
    )
  } else {
    "'Unknown'"
  }
  pocket_sql <- if ("pocket_number" %in% available) {
    "TRY_CAST(pocket_number AS INTEGER)"
  } else {
    "NULL::INTEGER"
  }
  cluster_sql <- paste0(
    "'",
    vapply(identifiers, escape_sql_literal, character(1L)),
    "'",
    collapse = ", "
  )
  paste0(
    "SELECT CAST(cluster_id AS VARCHAR) AS cluster_id, CAST(",
    quote_duckdb_identifier(accession),
    " AS VARCHAR) AS member_accession, ",
    species_sql,
    " AS species, ",
    pocket_sql,
    " AS pocket_number, TRY_CAST(druggability_score AS DOUBLE) AS ",
    "druggability_score FROM ",
    quote_duckdb_identifier(relation),
    " WHERE CAST(cluster_id AS VARCHAR) IN (",
    cluster_sql,
    ") AND TRY_CAST(druggability_score AS DOUBLE) BETWEEN 0.0 AND 1.0 ",
    "AND (",
    selection_filter,
    ") ORDER BY cluster_id, member_accession LIMIT ",
    max_rows
  )
}

#' Collect selected-pocket member druggability scores.
#'
#' @param resource_source Flexible E3 result source.
#' @param cluster_ids Exact lead cluster identifiers.
#' @param max_rows Hard row limit.
#' @return List containing the relation and standardised score rows.
collect_member_druggability_scores <- function(
  resource_source,
  cluster_ids,
  max_rows = 10000L
) {
  relations <- collect_resource_view_names(duckdb_path = resource_source)
  relation <- select_member_druggability_relation(relations)
  if (!nzchar(relation)) {
    stop(
      "No member-level selected-pocket druggability relation is available.",
      call. = FALSE
    )
  }
  available <- as.character(
    collect_resource_columns(resource_source, relation)$column_name
  )
  data <- collect_resource_query(
    duckdb_path = resource_source,
    query = build_member_druggability_query(
      relation = relation,
      available = available,
      cluster_ids = cluster_ids,
      max_rows = max_rows
    )
  )
  list(relation = relation, data = tibble::as_tibble(data))
}

#' Return SQL for a numeric gate.
#'
#' @param column Column name.
#' @param threshold Minimum value.
#' @param available Available columns.
#' @return SQL boolean expression.
threshold_numeric_gate <- function(column, threshold, available) {
  if (!column %in% available) {
    return("FALSE")
  }
  paste0(
    "COALESCE(CAST(", quote_duckdb_identifier(column),
    " AS DOUBLE), 0.0) >= ",
    format(threshold, scientific = FALSE, trim = TRUE, digits = 12L)
  )
}

#' Return SQL for a stored boolean gate.
#'
#' @param column Column name.
#' @param required Whether the gate is required.
#' @param available Available columns.
#' @return SQL boolean expression.
threshold_boolean_gate <- function(column, required, available) {
  if (!isTRUE(required)) {
    return("TRUE")
  }
  if (!column %in% available) {
    return("FALSE")
  }
  paste0(
    "COALESCE(CAST(", quote_duckdb_identifier(column),
    " AS BOOLEAN), FALSE)"
  )
}

#' Return SQL for a non-zero evidence-row gate.
#'
#' @param candidates Candidate evidence-count columns in preference order.
#' @param required Whether evidence availability is required.
#' @param available Available columns.
#' @return SQL boolean expression.
threshold_evidence_gate <- function(candidates, required, available) {
  if (!isTRUE(required)) {
    return("TRUE")
  }
  selected <- candidates[candidates %in% available]
  if (length(selected) == 0L) {
    return("FALSE")
  }
  paste0(
    "COALESCE(CAST(", quote_duckdb_identifier(selected[[1L]]),
    " AS DOUBLE), 0.0) > 0"
  )
}

#' Return SQL for one exact status gate.
#'
#' @param column Column name.
#' @param status Required status.
#' @param required Whether the status is required.
#' @param available Available columns.
#' @return SQL boolean expression.
threshold_status_gate <- function(column, status, required, available) {
  if (!isTRUE(required)) {
    return("TRUE")
  }
  if (!column %in% available) {
    return("FALSE")
  }
  paste0(
    "COALESCE(CAST(", quote_duckdb_identifier(column),
    " AS VARCHAR), '') = '", escape_sql_literal(status), "'"
  )
}

#' Return the selected optional thresholds active in one prioritisation mode.
#'
#' @param settings Normalised threshold settings.
#' @return Character vector of source-column names.
active_additional_thresholds <- function(settings) {
  selected <- settings$additional_thresholds
  if (identical(settings$mode, "structural")) {
    return(selected)
  }
  specifications <- additional_threshold_specs()
  selected[vapply(
    specifications[selected],
    function(value) identical(value$section, "prestructure"),
    logical(1)
  )]
}

#' Return a stable pass-column name for one optional threshold.
#'
#' @param column Source score column.
#' @return SQL-safe result-column name.
additional_threshold_gate_name <- function(column) {
  paste0("custom_additional_", column, "_pass")
}

#' Return one row per evolutionary group for threshold evaluation.
#'
#' @param relation Relation name.
#' @param available Available relation columns.
#' @param alias Attached resource alias.
#' @return SQL relation expression.
threshold_source_relation <- function(
  relation,
  available,
  alias = "e3_resource"
) {
  safe_alias <- sanitise_duckdb_alias(alias = alias)
  safe_relation <- quote_duckdb_identifier(relation)
  source <- paste0(safe_alias, ".main.", safe_relation)
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
    return(paste0(
      "(SELECT * EXCLUDE (_e3_group_row) FROM (SELECT *, ROW_NUMBER() OVER (",
      "PARTITION BY primary_group_type, primary_group_id ORDER BY ", order_sql,
      ") AS _e3_group_row FROM ", source,
      " WHERE COALESCE(CAST(primary_group_type AS VARCHAR), '') <> '' ",
      "AND COALESCE(CAST(primary_group_id AS VARCHAR), '') <> '') ",
      "WHERE _e3_group_row = 1)"
    ))
  }
  source
}

#' Build reusable SQL that evaluates every configurable gate.
#'
#' @param relation Relation name.
#' @param available Available relation columns.
#' @param settings Threshold settings.
#' @param alias Attached resource alias.
#' @return SQL common-table-expression prefix.
build_threshold_evaluation_cte <- function(
  relation,
  available,
  settings = list(),
  alias = "e3_resource"
) {
  values <- normalise_threshold_settings(settings = settings)
  optional_specifications <- additional_threshold_specs()
  active_optional <- active_additional_thresholds(settings = values)
  optional_gate_names <- vapply(
    active_optional,
    additional_threshold_gate_name,
    character(1)
  )
  optional_gate_expressions <- vapply(
    active_optional,
    function(column) {
      specification <- optional_specifications[[column]]
      threshold_numeric_gate(
        column = column,
        threshold = values[[specification$setting]],
        available = available
      )
    },
    character(1)
  )
  source <- threshold_source_relation(
    relation = relation,
    available = available,
    alias = alias
  )
  target_gate <- threshold_numeric_gate(
    column = "target_species_fraction",
    threshold = values$target_species_fraction,
    available = available
  )
  mandatory_gate <- threshold_numeric_gate(
    column = "mandatory_species_fraction",
    threshold = values$mandatory_species_fraction,
    available = available
  )
  domain_gate <- threshold_numeric_gate(
    column = "domain_species_fraction",
    threshold = values$domain_species_fraction,
    available = available
  )
  expression_gate <- threshold_numeric_gate(
    column = "expression_species_fraction",
    threshold = values$expression_species_fraction,
    available = available
  )
  domain_evidence_gate <- threshold_evidence_gate(
    candidates = c("domain_assessed_species_count", "domain_evidence_row_count"),
    required = values$require_domain_evidence,
    available = available
  )
  expression_evidence_gate <- threshold_evidence_gate(
    candidates = c(
      "expression_assessed_species_count",
      "expression_evidence_row_count"
    ),
    required = values$require_expression_evidence,
    available = available
  )
  structural_coverage_gate <- threshold_numeric_gate(
    column = "structural_species_fraction",
    threshold = values$structural_species_fraction,
    available = available
  )
  druggability_gate <- threshold_numeric_gate(
    column = "minimum_druggability_score",
    threshold = values$minimum_druggability_score,
    available = available
  )
  conserved_region_gate <- threshold_status_gate(
    column = "conservation_status",
    status = "CONSERVED_REGION_SUPPORTED",
    required = values$require_conserved_region,
    available = available
  )
  recorded_member_druggability <- threshold_boolean_gate(
    column = "all_assessed_members_pass_druggability",
    required = TRUE,
    available = available
  )
  member_mapping_gate <- threshold_boolean_gate(
    column = "all_assessed_members_pass_mapping",
    required = values$require_all_member_mapping,
    available = available
  )
  strict_3d_gate <- threshold_status_gate(
    column = "three_dimensional_alignment_status",
    status = "CONSERVED_3D_POCKET_SUPPORTED",
    required = values$require_strict_3d,
    available = available
  )
  structural_assessed <- if (
    "three_dimensional_alignment_status" %in% available
  ) {
    paste0(
      "COALESCE(CAST(three_dimensional_alignment_status AS VARCHAR), ",
      "'NOT_ASSESSED') <> 'NOT_ASSESSED'"
    )
  } else {
    "FALSE"
  }
  prestructure_gates <- c(
    target_gate,
    mandatory_gate,
    domain_evidence_gate,
    domain_gate,
    expression_evidence_gate,
    expression_gate,
    optional_gate_names[vapply(
      optional_specifications[active_optional],
      function(value) identical(value$section, "prestructure"),
      logical(1)
    )]
  )
  structural_gates <- c(
    "custom_prestructure_pass",
    "custom_structural_assessed",
    conserved_region_gate,
    "custom_druggability_pass",
    member_mapping_gate,
    structural_coverage_gate,
    strict_3d_gate,
    optional_gate_names[vapply(
      optional_specifications[active_optional],
      function(value) identical(value$section, "structural"),
      logical(1)
    )]
  )
  prestructure_failure_names <- c(
    paste0("custom_", c(
      "target_species_pass",
      "mandatory_species_pass",
      "domain_evidence_pass",
      "domain_species_pass",
      "expression_evidence_pass",
      "expression_species_pass"
    )),
    optional_gate_names[vapply(
      optional_specifications[active_optional],
      function(value) identical(value$section, "prestructure"),
      logical(1)
    )]
  )
  prestructure_failure_count <- paste0(
    "(",
    paste0("CAST(NOT ", prestructure_failure_names, " AS INTEGER)", collapse = " + "),
    ")"
  )
  structural_failure_names <- c(
    paste0("custom_", c(
      "prestructure_pass",
      "conserved_region_pass",
      "druggability_pass",
      "all_member_mapping_pass",
      "structural_species_pass",
      "strict_3d_pass"
    )),
    optional_gate_names[vapply(
      optional_specifications[active_optional],
      function(value) identical(value$section, "structural"),
      logical(1)
    )]
  )
  structural_failure_count <- paste0(
    "(",
    paste0("CAST(NOT ", structural_failure_names, " AS INTEGER)", collapse = " + "),
    ")"
  )
  status_sql <- if (values$mode == "prestructure") {
    paste0(
      "CASE WHEN custom_prestructure_pass THEN 'PASS' WHEN ",
      prestructure_failure_count,
      " = 1 THEN 'NEAR_MISS' ELSE 'FAIL' END"
    )
  } else {
    paste0(
      "CASE WHEN NOT custom_structural_assessed THEN ",
      "'NOT_STRUCTURALLY_ASSESSED' WHEN custom_structural_pass THEN 'PASS' ",
      "WHEN ", structural_failure_count,
      " = 1 THEN 'NEAR_MISS' ELSE 'FAIL' END"
    )
  }
  optional_select_sql <- if (length(active_optional) == 0L) {
    ""
  } else {
    paste0(
      ", ",
      paste0(
        optional_gate_expressions,
        " AS ",
        optional_gate_names,
        collapse = ", "
      )
    )
  }
  paste0(
    "WITH source_rows AS (SELECT * FROM ", source, "), evaluated AS (SELECT *, ",
    target_gate, " AS custom_target_species_pass, ",
    mandatory_gate, " AS custom_mandatory_species_pass, ",
    domain_evidence_gate, " AS custom_domain_evidence_pass, ",
    domain_gate, " AS custom_domain_species_pass, ",
    expression_evidence_gate, " AS custom_expression_evidence_pass, ",
    expression_gate, " AS custom_expression_species_pass, ",
    structural_assessed, " AS custom_structural_assessed, ",
    conserved_region_gate, " AS custom_conserved_region_pass, ",
    druggability_gate, " AS custom_druggability_score_pass, ",
    recorded_member_druggability,
    " AS recorded_original_all_member_druggability_pass, ",
    druggability_gate, " AS custom_druggability_pass, ",
    member_mapping_gate, " AS custom_all_member_mapping_pass, ",
    structural_coverage_gate, " AS custom_structural_species_pass, ",
    strict_3d_gate, " AS custom_strict_3d_pass", optional_select_sql,
    " FROM source_rows), ",
    "decisions AS (SELECT *, (", paste(prestructure_gates, collapse = " AND "),
    ") AS custom_prestructure_pass FROM evaluated), structural_decisions AS (",
    "SELECT *, (", paste(structural_gates, collapse = " AND "),
    ") AS custom_structural_pass FROM decisions), classified AS (SELECT *, ",
    status_sql, " AS custom_status FROM structural_decisions) "
  )
}

#' Choose expanded, informative result columns.
#'
#' @param available Available source columns.
#' @param mode Threshold mode.
#' @return Ordered source-column names.
threshold_result_columns <- function(available, mode = "prestructure") {
  shared <- c(
    "final_evolutionary_rank",
    "prestructure_evolutionary_group_rank",
    "stringent_rank",
    "structurally_supported_rank",
    "boss_review_status",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "lead_computational_rank",
    "cluster_id",
    "contributing_deepclust_cluster_count",
    "contributing_deepclust_cluster_ids",
    "candidate_accession_count",
    "candidate_accessions",
    "alternative_group_count",
    "orthofinder_orthogroup_ids",
    "orthofinder_hierarchical_group_ids",
    "orthofinder_group_member_count",
    "orthofinder_group_species_count",
    "prestructure_score",
    "best_prestructure_score",
    "mean_prestructure_score",
    "minimum_prestructure_score",
    "discovery_score",
    "orthology_score",
    "domain_score",
    "expression_score",
    "evidence_completeness_fraction",
    "target_species_count",
    "target_species_total",
    "target_species_fraction",
    "target_species_present",
    "target_species_missing",
    "mandatory_species_count",
    "mandatory_species_total",
    "mandatory_species_fraction",
    "mandatory_species_missing",
    "domain_supported_species_count",
    "domain_assessed_species_count",
    "domain_unavailable_species_count",
    "domain_annotation_coverage_fraction",
    "domain_species_fraction",
    "domain_supported_species",
    "domain_annotated_negative_species",
    "domain_unavailable_species",
    "expression_supported_species_count",
    "expression_available_species_count",
    "expression_assessed_species_count",
    "expression_unavailable_species_count",
    "expression_evidence_coverage_fraction",
    "expression_species_fraction",
    "expression_supported_species",
    "expression_assessed_negative_species",
    "expression_unavailable_species",
    "reviewed_seed_fraction",
    "ubiquitin_go_positive_seed_fraction",
    "exclusion_flag_fraction",
    "discovery_known_e3_sequence_count",
    "discovery_known_e3_seed_count",
    "discovery_known_e3_seed_ids",
    "discovery_matched_seed_sequence_count",
    "discovery_matched_seed_id_count",
    "discovery_matched_seed_ids_calculated",
    "discovery_seed_categories",
    "discovery_seed_review_statuses",
    "discovery_seed_ubiquitin_go_statuses",
    "discovery_seed_organisms",
    "discovery_seed_protein_names",
    "discovery_reviewed_seed_count",
    "discovery_ubiquitin_go_positive_seed_count",
    "discovery_seed_with_exclusion_go_term_count",
    "discovery_raw_member_count",
    "discovery_strict_member_count",
    "discovery_strict_nonseed_candidate_count",
    "discovery_strict_member_fraction",
    "discovery_strict_nonseed_fraction",
    "discovery_raw_species_count_calculated",
    "discovery_strict_species_count",
    "discovery_strict_onekp_species_count",
    "domain_evidence_row_count",
    "expression_evidence_row_count",
    "grant_aligned_prestructure_pass",
    "grant_aligned_stringent_pass",
    "grant_aligned_criteria_status",
    "computational_structure_selected",
    "inclusion_reasons",
    "exclusion_reasons",
    "missing_evidence",
    "profile_name",
    "interpretation"
  )
  structural <- c(
    "final_rank",
    "recommendation_status",
    "grant_aligned_prediction_status",
    "final_score",
    "structural_score",
    "ligandability_score",
    "pocket_conservation_score",
    "three_dimensional_pocket_score",
    "selected_pocket_count",
    "structural_species_fraction",
    "minimum_druggability_score",
    "all_assessed_members_pass_druggability",
    "all_assessed_members_pass_mapping",
    "mean_pocket_plddt_fraction",
    "predictor_agreement_fraction",
    "conservation_status",
    "mean_pairwise_region_overlap",
    "mean_chemical_group_conservation",
    "three_dimensional_position_status",
    "three_dimensional_alignment_status",
    "mean_minimum_tm_score",
    "mean_pocket_overlap_fraction",
    "median_centroid_distance_angstrom",
    "mean_structural_residue_match_fraction",
    "mean_structural_residue_identity_fraction",
    "mean_structural_chemical_group_conservation",
    "grant_aligned_base_pass",
    "grant_aligned_final_pass",
    "structural_exclusion_reasons"
  )
  preferred <- if (identical(mode, "structural")) {
    c(shared, structural)
  } else {
    shared
  }
  selected <- unique(preferred[preferred %in% available])
  if (length(selected) == 0L) {
    selected <- head(available, 30L)
  }
  selected
}

#' Build the interactive candidate-list SQL query.
#'
#' @param relation Relation name.
#' @param available Available relation columns.
#' @param settings Threshold settings.
#' @param max_rows Maximum rows returned.
#' @param alias Attached resource alias.
#' @return Bounded SQL query.
build_threshold_result_query <- function(
  relation,
  available,
  settings = list(),
  max_rows = 1000L,
  alias = "e3_resource"
) {
  values <- normalise_threshold_settings(settings = settings)
  optional_specifications <- additional_threshold_specs()
  active_optional <- active_additional_thresholds(settings = values)
  limit <- suppressWarnings(as.integer(max_rows))
  if (length(limit) != 1L || is.na(limit) || limit < 1L || limit > 10000L) {
    stop("Maximum rows must be between 1 and 10000.", call. = FALSE)
  }
  source_columns <- threshold_result_columns(
    available = available,
    mode = values$mode
  )
  selected_sql <- paste(
    vapply(source_columns, quote_duckdb_identifier, character(1L)),
    collapse = ", "
  )
  gate_columns <- c(
    "custom_prestructure_pass",
    "custom_structural_pass",
    "custom_structural_assessed",
    "custom_target_species_pass",
    "custom_mandatory_species_pass",
    "custom_domain_evidence_pass",
    "custom_domain_species_pass",
    "custom_expression_evidence_pass",
    "custom_expression_species_pass",
    vapply(active_optional, additional_threshold_gate_name, character(1))
  )
  if (values$mode == "structural") {
    gate_columns <- c(
      gate_columns,
      "custom_conserved_region_pass",
      "custom_druggability_score_pass",
      "recorded_original_all_member_druggability_pass",
      "custom_druggability_pass",
      "custom_all_member_mapping_pass",
      "custom_structural_species_pass",
      "custom_strict_3d_pass"
    )
  }
  filter_sql <- switch(
    values$result_scope,
    passing = "custom_status = 'PASS'",
    pass_near = "custom_status IN ('PASS', 'NEAR_MISS')",
    all = "TRUE"
  )
  if (values$mode == "structural" && values$include_not_assessed) {
    filter_sql <- paste0(
      "(", filter_sql,
      " OR custom_status = 'NOT_STRUCTURALLY_ASSESSED')"
    )
  } else if (values$mode == "structural") {
    filter_sql <- paste0(
      "(", filter_sql,
      " AND custom_status <> 'NOT_STRUCTURALLY_ASSESSED')"
    )
  }
  score_column <- if (values$mode == "structural" && "final_score" %in% available) {
    "final_score"
  } else if ("prestructure_score" %in% available) {
    "prestructure_score"
  } else if ("best_prestructure_score" %in% available) {
    "best_prestructure_score"
  } else {
    NULL
  }
  score_order <- if (is.null(score_column)) {
    ""
  } else {
    paste0(", COALESCE(CAST(", quote_duckdb_identifier(score_column),
      " AS DOUBLE), 0.0) DESC")
  }
  mode_literal <- escape_sql_literal(values$mode)
  optional_metadata <- if (length(active_optional) == 0L) {
    "'' AS threshold_additional_fields"
  } else {
    field_metadata <- paste0(
      vapply(
        active_optional,
        function(column) {
          setting <- optional_specifications[[column]]$setting
          paste0(
            values[[setting]],
            " AS threshold_",
            setting
          )
        },
        character(1)
      ),
      collapse = ", "
    )
    paste0(
      "'",
      escape_sql_literal(paste(active_optional, collapse = ";")),
      "' AS threshold_additional_fields, ",
      field_metadata
    )
  }
  threshold_metadata <- paste0(
    "'", mode_literal, "' AS threshold_mode, ",
    values$target_species_fraction,
    " AS threshold_target_species_fraction, ",
    values$mandatory_species_fraction,
    " AS threshold_mandatory_species_fraction, ",
    values$domain_species_fraction,
    " AS threshold_domain_species_fraction, ",
    values$expression_species_fraction,
    " AS threshold_expression_species_fraction, ",
    values$structural_species_fraction,
    " AS threshold_structural_species_fraction, ",
    values$minimum_druggability_score,
    " AS threshold_minimum_druggability_score, ",
    optional_metadata
  )
  cte <- build_threshold_evaluation_cte(
    relation = relation,
    available = available,
    settings = values,
    alias = alias
  )
  paste0(
    cte,
    "SELECT ROW_NUMBER() OVER (ORDER BY CASE custom_status WHEN 'PASS' THEN 0 ",
    "WHEN 'NEAR_MISS' THEN 1 WHEN 'NOT_STRUCTURALLY_ASSESSED' THEN 2 ELSE 3 END",
    score_order,
    ") AS custom_list_rank, custom_status, ",
    paste(gate_columns, collapse = ", "), ", ", threshold_metadata, ", ",
    selected_sql, " FROM classified WHERE ", filter_sql,
    " ORDER BY custom_list_rank LIMIT ", limit
  )
}

#' Build a compact threshold-result summary query.
#'
#' @param relation Relation name.
#' @param available Available relation columns.
#' @param settings Threshold settings.
#' @param alias Attached resource alias.
#' @return SQL query.
build_threshold_summary_query <- function(
  relation,
  available,
  settings = list(),
  alias = "e3_resource"
) {
  cte <- build_threshold_evaluation_cte(
    relation = relation,
    available = available,
    settings = settings,
    alias = alias
  )
  paste0(
    cte,
    "SELECT COUNT(*) AS evaluated_count, ",
    "SUM(CASE WHEN custom_status = 'PASS' THEN 1 ELSE 0 END) AS pass_count, ",
    "SUM(CASE WHEN custom_status = 'NEAR_MISS' THEN 1 ELSE 0 END) AS near_miss_count, ",
    "SUM(CASE WHEN custom_structural_assessed THEN 1 ELSE 0 END) AS ",
    "structurally_assessed_count, ",
    "SUM(CASE WHEN custom_status = 'NOT_STRUCTURALLY_ASSESSED' THEN 1 ELSE 0 END) ",
    "AS not_structurally_assessed_count FROM classified"
  )
}

threshold_hog_text_columns <- function() {
  c(
    "human_hog_representatives", "arabidopsis_hog_representatives",
    "human_hog_accessions", "human_hog_entries", "human_hog_raw_identifiers",
    "arabidopsis_hog_accessions", "arabidopsis_hog_entries",
    "arabidopsis_hog_raw_identifiers", "rice_hog_representatives",
    "rice_hog_accessions", "rice_hog_entries", "rice_hog_raw_identifiers",
    "barley_hog_representatives", "barley_hog_accessions",
    "barley_hog_entries", "barley_hog_raw_identifiers", "hog_species_present",
    "hog_orthogroup_ids", "hog_gene_tree_parent_clades",
    "hog_review_statuses", "hog_mapping_statuses"
  )
}

threshold_hog_count_columns <- function() {
  c(
    "hog_member_count", "hog_species_count", "hog_human_member_count",
    "hog_arabidopsis_member_count", "hog_rice_member_count",
    "hog_barley_member_count"
  )
}

threshold_hog_annotation_columns <- function() {
  c(
    threshold_hog_text_columns(), threshold_hog_count_columns(),
    "hog_membership_available"
  )
}

threshold_membership_text_expression <- function(available, column) {
  if (!column %in% available) return("CAST(NULL AS VARCHAR)")
  paste0("CAST(", quote_duckdb_identifier(column), " AS VARCHAR)")
}

#' Build root-HOG annotations for a bounded threshold-result group set.
#'
#' @param membership_columns Available hierarchical-membership fields.
#' @param group_ids Requested evolutionary-group identifiers.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_threshold_hog_annotation_query <- function(
  membership_columns,
  group_ids,
  alias = "e3_resource"
) {
  groups <- unique(trimws(as.character(group_ids)))
  groups <- groups[nzchar(groups) & !is.na(groups)]
  if (length(groups) < 1L || length(groups) > 10000L) {
    stop("Threshold HOG group count must be between 1 and 10000.", call. = FALSE)
  }
  required <- c("group_id", "species", "raw_identifier")
  missing <- setdiff(required, membership_columns)
  if (length(missing) > 0L) {
    stop(
      paste("Hierarchical membership lacks fields:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  parsed_accession <- threshold_membership_text_expression(
    available = membership_columns,
    column = "parsed_accession"
  )
  parsed_entry <- threshold_membership_text_expression(
    available = membership_columns,
    column = "parsed_entry"
  )
  optional <- function(column) {
    threshold_membership_text_expression(
      available = membership_columns,
      column = column
    )
  }
  representative <- paste0(
    "coalesce(nullif(trim(", parsed_accession, "), ''), nullif(trim(",
    parsed_entry, "), ''), nullif(trim(CAST(raw_identifier AS VARCHAR)), ''))"
  )
  group_values <- paste0(
    "('", vapply(groups, escape_sql_literal, character(1L)), "')",
    collapse = ", "
  )
  membership <- qualified_resource_relation(
    relation = "hierarchical_membership",
    alias = alias
  )
  paste0(
    "WITH requested(hog_id) AS (VALUES ", group_values, "), members AS (SELECT ",
    "CAST(group_id AS VARCHAR) AS primary_group_id, CAST(species AS VARCHAR) ",
    "AS species, CAST(raw_identifier AS VARCHAR) AS raw_identifier, ",
    parsed_accession, " AS parsed_accession, ", parsed_entry,
    " AS parsed_entry, ", representative, " AS representative, ",
    optional("orthogroup_id"), " AS orthogroup_id, ",
    optional("gene_tree_parent_clade"), " AS gene_tree_parent_clade, ",
    optional("review_status"), " AS review_status, ",
    optional("mapping_status"), " AS mapping_status FROM ", membership,
    " INNER JOIN requested ON requested.hog_id = CAST(group_id AS VARCHAR)) ",
    "SELECT primary_group_id, coalesce(string_agg(DISTINCT representative, ';' ",
    "ORDER BY representative) FILTER (WHERE species = 'Homo_sapiens' AND ",
    "representative IS NOT NULL), '') AS human_hog_representatives, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE species = 'Arabidopsis_thaliana' AND representative IS NOT ",
    "NULL), '') AS arabidopsis_hog_representatives, ",
    "coalesce(string_agg(DISTINCT parsed_accession, ';' ORDER BY parsed_accession) ",
    "FILTER (WHERE species = 'Homo_sapiens' AND nullif(trim(parsed_accession), ",
    "'') IS NOT NULL), '') AS human_hog_accessions, ",
    "coalesce(string_agg(DISTINCT parsed_entry, ';' ORDER BY parsed_entry) FILTER ",
    "(WHERE species = 'Homo_sapiens' AND nullif(trim(parsed_entry), '') IS NOT ",
    "NULL), '') AS human_hog_entries, coalesce(string_agg(DISTINCT raw_identifier, ",
    "';' ORDER BY raw_identifier) FILTER (WHERE species = 'Homo_sapiens'), '') ",
    "AS human_hog_raw_identifiers, coalesce(string_agg(DISTINCT parsed_accession, ",
    "';' ORDER BY parsed_accession) FILTER (WHERE species = ",
    "'Arabidopsis_thaliana' AND nullif(trim(parsed_accession), '') IS NOT NULL), ",
    "'') AS arabidopsis_hog_accessions, coalesce(string_agg(DISTINCT parsed_entry, ",
    "';' ORDER BY parsed_entry) FILTER (WHERE species = 'Arabidopsis_thaliana' ",
    "AND nullif(trim(parsed_entry), '') IS NOT NULL), '') AS ",
    "arabidopsis_hog_entries, coalesce(string_agg(DISTINCT raw_identifier, ';' ",
    "ORDER BY raw_identifier) FILTER (WHERE species = 'Arabidopsis_thaliana'), ",
    "'') AS arabidopsis_hog_raw_identifiers, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE species = 'Oryza_sativa' AND representative IS NOT NULL), ",
    "'') AS rice_hog_representatives, coalesce(string_agg(DISTINCT ",
    "parsed_accession, ';' ORDER BY parsed_accession) FILTER (WHERE species = ",
    "'Oryza_sativa' AND nullif(trim(parsed_accession), '') IS NOT NULL), '') ",
    "AS rice_hog_accessions, coalesce(string_agg(DISTINCT parsed_entry, ';' ",
    "ORDER BY parsed_entry) FILTER (WHERE species = 'Oryza_sativa' AND ",
    "nullif(trim(parsed_entry), '') IS NOT NULL), '') AS rice_hog_entries, ",
    "coalesce(string_agg(DISTINCT raw_identifier, ';' ORDER BY raw_identifier) ",
    "FILTER (WHERE species = 'Oryza_sativa'), '') AS rice_hog_raw_identifiers, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE species = 'Hordeum_vulgare' AND representative IS NOT NULL), ",
    "'') AS barley_hog_representatives, coalesce(string_agg(DISTINCT ",
    "parsed_accession, ';' ORDER BY parsed_accession) FILTER (WHERE species = ",
    "'Hordeum_vulgare' AND nullif(trim(parsed_accession), '') IS NOT NULL), '') ",
    "AS barley_hog_accessions, coalesce(string_agg(DISTINCT parsed_entry, ';' ",
    "ORDER BY parsed_entry) FILTER (WHERE species = 'Hordeum_vulgare' AND ",
    "nullif(trim(parsed_entry), '') IS NOT NULL), '') AS barley_hog_entries, ",
    "coalesce(string_agg(DISTINCT raw_identifier, ';' ORDER BY raw_identifier) ",
    "FILTER (WHERE species = 'Hordeum_vulgare'), '') AS ",
    "barley_hog_raw_identifiers, count(*) AS hog_member_count, ",
    "count(DISTINCT species) AS hog_species_count, count(*) FILTER (WHERE species ",
    "= 'Homo_sapiens') AS hog_human_member_count, count(*) FILTER (WHERE species ",
    "= 'Arabidopsis_thaliana') AS hog_arabidopsis_member_count, ",
    "count(*) FILTER (WHERE species = 'Oryza_sativa') AS hog_rice_member_count, ",
    "count(*) FILTER (WHERE species = 'Hordeum_vulgare') AS ",
    "hog_barley_member_count, coalesce(",
    "string_agg(DISTINCT species, ';' ORDER BY species), '') AS ",
    "hog_species_present, coalesce(string_agg(DISTINCT orthogroup_id, ';' ORDER BY ",
    "orthogroup_id) FILTER (WHERE nullif(trim(orthogroup_id), '') IS NOT NULL), ",
    "'') AS hog_orthogroup_ids, coalesce(string_agg(DISTINCT ",
    "gene_tree_parent_clade, ';' ORDER BY gene_tree_parent_clade) FILTER (WHERE ",
    "nullif(trim(gene_tree_parent_clade), '') IS NOT NULL), '') AS ",
    "hog_gene_tree_parent_clades, coalesce(string_agg(DISTINCT review_status, ';' ",
    "ORDER BY review_status) FILTER (WHERE nullif(trim(review_status), '') IS NOT ",
    "NULL), '') AS hog_review_statuses, coalesce(string_agg(DISTINCT mapping_status, ",
    "';' ORDER BY mapping_status) FILTER (WHERE nullif(trim(mapping_status), '') ",
    "IS NOT NULL), '') AS hog_mapping_statuses, TRUE AS hog_membership_available ",
    "FROM members GROUP BY primary_group_id"
  )
}

add_empty_threshold_hog_annotations <- function(data) {
  result <- data
  for (column in threshold_hog_text_columns()) {
    if (!column %in% names(result)) result[[column]] <- rep("", nrow(result))
  }
  for (column in threshold_hog_count_columns()) {
    if (!column %in% names(result)) result[[column]] <- rep(0L, nrow(result))
  }
  if (!"hog_membership_available" %in% names(result)) {
    result$hog_membership_available <- rep(FALSE, nrow(result))
  }
  result
}

#' Add root-HOG membership context to bounded threshold results.
#'
#' @param resource_source Flexible E3 resource source.
#' @param data Bounded threshold result.
#' @return Enriched threshold result.
enrich_threshold_results <- function(resource_source, data) {
  empty <- add_empty_threshold_hog_annotations(data = data)
  if (nrow(data) == 0L || !"primary_group_id" %in% names(data)) return(empty)
  relations <- collect_resource_view_names(duckdb_path = resource_source)
  if (!"hierarchical_membership" %in% relations) return(empty)
  metadata <- collect_resource_columns(
    duckdb_path = resource_source,
    view_name = "hierarchical_membership"
  )
  membership_columns <- as.character(metadata$column_name)
  required <- c("group_id", "species", "raw_identifier")
  if (!all(required %in% membership_columns)) return(empty)
  groups <- unique(data$primary_group_id)
  groups <- groups[!is.na(groups) & nzchar(trimws(as.character(groups)))]
  if (length(groups) == 0L) return(empty)
  annotations <- tryCatch(
    collect_resource_query(
      duckdb_path = resource_source,
      query = build_threshold_hog_annotation_query(
        membership_columns = membership_columns,
        group_ids = groups
      )
    ),
    error = function(error) {
      message("Threshold HOG annotations are unavailable: ", conditionMessage(error))
      NULL
    }
  )
  if (is.null(annotations)) return(empty)
  new_columns <- setdiff(threshold_hog_annotation_columns(), names(data))
  if (length(new_columns) == 0L) return(data)
  annotations <- annotations[, c("primary_group_id", new_columns), drop = FALSE]
  enriched <- dplyr::left_join(data, annotations, by = "primary_group_id")
  for (column in intersect(threshold_hog_text_columns(), names(enriched))) {
    enriched[[column]][is.na(enriched[[column]])] <- ""
  }
  for (column in intersect(threshold_hog_count_columns(), names(enriched))) {
    enriched[[column]][is.na(enriched[[column]])] <- 0L
  }
  if ("hog_membership_available" %in% names(enriched)) {
    enriched$hog_membership_available[is.na(enriched$hog_membership_available)] <-
      FALSE
  }
  enriched
}

#' Collect a custom threshold candidate list.
#'
#' @param resource_source Flexible result source.
#' @param relation Relation name.
#' @param available Available relation columns.
#' @param settings Threshold settings.
#' @param max_rows Maximum rows.
#' @return Collected tibble.
collect_threshold_results <- function(
  resource_source,
  relation,
  available,
  settings = list(),
  max_rows = 1000L
) {
  data <- collect_resource_query(
    duckdb_path = resource_source,
    query = build_threshold_result_query(
      relation = relation,
      available = available,
      settings = settings,
      max_rows = max_rows
    )
  )
  enrich_threshold_results(resource_source = resource_source, data = data)
}

#' Collect custom-threshold summary counts.
#'
#' @param resource_source Flexible result source.
#' @param relation Relation name.
#' @param available Available relation columns.
#' @param settings Threshold settings.
#' @return One-row tibble.
collect_threshold_summary <- function(
  resource_source,
  relation,
  available,
  settings = list()
) {
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_threshold_summary_query(
      relation = relation,
      available = available,
      settings = settings
    )
  )
}
