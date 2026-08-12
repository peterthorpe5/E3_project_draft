#' Transparent ranking formulas and non-authoritative reweighting helpers.

#' Return the recorded production score weights.
#'
#' @return Named list of named numeric weight vectors.
recorded_ranking_weights <- function() {
  list(
    prestructure = c(
      discovery = 0.10,
      orthology = 0.35,
      domain = 0.20,
      expression = 0.35
    ),
    ligandability = c(
      minimum_druggability = 0.25,
      pocket_plddt = 0.25,
      member_mapping = 0.25,
      predictor_agreement = 0.25
    ),
    structural = c(
      ligandability = 0.55,
      pocket_conservation = 0.45
    ),
    final = c(
      prestructure = 0.60,
      structural = 0.40
    )
  )
}

#' Return user-facing labels for each adjustable ranking component.
#'
#' @return Named list of named character vectors.
ranking_weight_labels <- function() {
  list(
    prestructure = c(
      discovery = "Discovery score",
      orthology = "Orthology score",
      domain = "Domain score",
      expression = "Expression score"
    ),
    ligandability = c(
      minimum_druggability = "Minimum member druggability",
      pocket_plddt = "Mean pocket pLDDT fraction",
      member_mapping = "All-member mapping pass",
      predictor_agreement = "Pocket-predictor agreement"
    ),
    structural = c(
      ligandability = "Ligandability score",
      pocket_conservation = "Pocket-conservation score"
    ),
    final = c(
      prestructure = "Pre-structure score",
      structural = "Structural score"
    )
  )
}

#' Select the most authoritative relation for weight sensitivity.
#'
#' @param relation_names Available relation names.
#' @return Relation name or an empty string.
select_ranking_relation <- function(relation_names) {
  preferred <- c(
    "final_evolutionary_candidate_prioritisation",
    "top_computational_review_shortlist",
    "top_50_computational_review_shortlist",
    "candidate_master_results",
    "final_candidate_prioritisation"
  )
  selected <- preferred[preferred %in% relation_names]
  if (length(selected) == 0L) "" else selected[[1L]]
}

#' Validate and normalise one adjustable weight group.
#'
#' @param weights Named numeric vector.
#' @param expected Expected component names.
#' @return Named numeric vector summing to one.
normalise_ranking_weights <- function(weights, expected) {
  if (!is.numeric(weights) || !setequal(names(weights), expected)) {
    stop(
      "Ranking weights do not match the expected numeric components.",
      call. = FALSE
    )
  }
  weights <- weights[expected]
  if (any(is.na(weights)) || any(weights < 0) || any(weights > 1)) {
    stop("Ranking weights must be between 0 and 1.", call. = FALSE)
  }
  total <- sum(weights)
  if (total <= 0) {
    stop(
      "At least one ranking weight in each group must be positive.",
      call. = FALSE
    )
  }
  weights / total
}

#' Return the bounded columns required for score reweighting.
#'
#' @param available Available source columns.
#' @return Ordered source columns.
ranking_source_columns <- function(available) {
  preferred <- c(
    "final_evolutionary_rank", "final_rank", "computational_rank",
    "evolutionary_group_key", "primary_group_type", "primary_group_id",
    "lead_cluster_id", "cluster_id", "boss_review_status",
    "grant_aligned_prediction_status", "grant_aligned_base_pass",
    "grant_aligned_final_pass", "lead_discovery_score", "discovery_score",
    "lead_orthology_score", "orthology_score", "lead_domain_score",
    "domain_score", "lead_expression_score", "expression_score",
    "minimum_druggability_score", "mean_pocket_plddt_fraction",
    "all_assessed_members_pass_mapping", "predictor_agreement_fraction",
    "pocket_conservation_score", "three_dimensional_pocket_score",
    "three_dimensional_alignment_status", "evidence_completeness_fraction",
    "prestructure_score", "ligandability_score", "structural_score",
    "final_score"
  )
  preferred[preferred %in% available]
}

#' Check whether a relation retains all score-component families.
#'
#' @param columns Available source columns.
#' @return Logical scalar.
ranking_source_is_complete <- function(columns) {
  alternatives <- list(
    c("lead_discovery_score", "discovery_score"),
    c("lead_orthology_score", "orthology_score"),
    c("lead_domain_score", "domain_score"),
    c("lead_expression_score", "expression_score")
  )
  required <- c(
    "minimum_druggability_score",
    "mean_pocket_plddt_fraction",
    "all_assessed_members_pass_mapping",
    "predictor_agreement_fraction",
    "pocket_conservation_score",
    "three_dimensional_pocket_score"
  )
  all(required %in% columns) && all(vapply(
    alternatives,
    function(values) any(values %in% columns),
    logical(1)
  ))
}

#' Return the first available bounded numeric component.
#'
#' @param data Source data frame.
#' @param candidates Candidate column names in preference order.
#' @return Numeric vector bounded to zero through one.
ranking_numeric_component <- function(data, candidates) {
  selected <- candidates[candidates %in% names(data)]
  if (length(selected) == 0L) {
    stop(
      paste("Ranking sensitivity requires one of:", paste(candidates, collapse = ", ")),
      call. = FALSE
    )
  }
  values <- suppressWarnings(as.numeric(data[[selected[[1L]]]]))
  values[is.na(values)] <- 0
  pmax(0, pmin(1, values))
}

#' Return a conservative logical interpretation of one stored field.
#'
#' @param data Source data frame.
#' @param column Column name.
#' @return Logical vector.
ranking_logical_component <- function(data, column) {
  if (!column %in% names(data)) {
    stop(paste("Ranking sensitivity requires", column), call. = FALSE)
  }
  values <- data[[column]]
  if (is.logical(values)) {
    values[is.na(values)] <- FALSE
    return(values)
  }
  tolower(trimws(as.character(values))) %in% c(
    "true", "t", "1", "yes", "y", "pass"
  )
}

#' Recompute an explicitly non-authoritative sensitivity ranking.
#'
#' @param data Complete ranking component rows.
#' @param weights Nested adjustable weight list.
#' @param three_dimensional_weight Optional recorded-3D score weight.
#' @param preserve_gate_tier Whether recorded base-gate passes remain first.
#' @return Compact re-ranked data frame.
recompute_exploratory_ranking <- function(
  data,
  weights = recorded_ranking_weights(),
  three_dimensional_weight = 0,
  preserve_gate_tier = TRUE
) {
  if (!is.data.frame(data)) {
    stop("Ranking sensitivity requires a data frame.", call. = FALSE)
  }
  if (nrow(data) == 0L) {
    return(data.frame())
  }
  defaults <- recorded_ranking_weights()
  if (!is.list(weights) || !setequal(names(weights), names(defaults))) {
    stop("Ranking sensitivity requires every weight group.", call. = FALSE)
  }
  normalised <- lapply(names(defaults), function(group) {
    normalise_ranking_weights(
      weights = weights[[group]],
      expected = names(defaults[[group]])
    )
  })
  names(normalised) <- names(defaults)
  if (
    length(three_dimensional_weight) != 1L ||
      is.na(three_dimensional_weight) ||
      !is.numeric(three_dimensional_weight) ||
      three_dimensional_weight < 0 ||
      three_dimensional_weight > 1
  ) {
    stop("The 3D refinement weight must be between 0 and 1.", call. = FALSE)
  }
  pre <- normalised$prestructure
  ligand <- normalised$ligandability
  structural <- normalised$structural
  final <- normalised$final
  discovery <- ranking_numeric_component(
    data, c("lead_discovery_score", "discovery_score")
  )
  orthology <- ranking_numeric_component(
    data, c("lead_orthology_score", "orthology_score")
  )
  domain <- ranking_numeric_component(
    data, c("lead_domain_score", "domain_score")
  )
  expression <- ranking_numeric_component(
    data, c("lead_expression_score", "expression_score")
  )
  exploratory_prestructure <-
    discovery * pre[["discovery"]] +
    orthology * pre[["orthology"]] +
    domain * pre[["domain"]] +
    expression * pre[["expression"]]
  exploratory_ligandability <-
    ranking_numeric_component(data, "minimum_druggability_score") *
      ligand[["minimum_druggability"]] +
    ranking_numeric_component(data, "mean_pocket_plddt_fraction") *
      ligand[["pocket_plddt"]] +
    as.numeric(ranking_logical_component(
      data, "all_assessed_members_pass_mapping"
    )) * ligand[["member_mapping"]] +
    ranking_numeric_component(data, "predictor_agreement_fraction") *
      ligand[["predictor_agreement"]]
  base_structural <-
    exploratory_ligandability * structural[["ligandability"]] +
    ranking_numeric_component(data, "pocket_conservation_score") *
      structural[["pocket_conservation"]]
  three_dimensional <- ranking_numeric_component(
    data, "three_dimensional_pocket_score"
  )
  assessed <- if ("three_dimensional_alignment_status" %in% names(data)) {
    status <- trimws(as.character(data$three_dimensional_alignment_status))
    !is.na(status) & nzchar(status) & !toupper(status) %in%
      c("NOT_ASSESSED", "NOT_STRUCTURALLY_ASSESSED")
  } else {
    rep(FALSE, nrow(data))
  }
  exploratory_structural <- base_structural
  exploratory_structural[assessed] <-
    base_structural[assessed] * (1 - three_dimensional_weight) +
    three_dimensional[assessed] * three_dimensional_weight
  exploratory_final <-
    exploratory_prestructure * final[["prestructure"]] +
    exploratory_structural * final[["structural"]]

  result <- data
  result$exploratory_prestructure_score <- exploratory_prestructure
  result$exploratory_ligandability_score <- exploratory_ligandability
  result$exploratory_structural_score <- exploratory_structural
  result$exploratory_final_score <- exploratory_final
  identity_candidates <- c(
    "evolutionary_group_key", "primary_group_id", "lead_cluster_id", "cluster_id"
  )
  identity <- identity_candidates[identity_candidates %in% names(result)]
  if (length(identity) == 0L) {
    stop("Ranking sensitivity requires a stable group identifier.", call. = FALSE)
  }
  identity <- identity[[1L]]
  completeness <- if ("evidence_completeness_fraction" %in% names(result)) {
    ranking_numeric_component(result, "evidence_completeness_fraction")
  } else {
    rep(0, nrow(result))
  }
  gate_tier <- if (
    isTRUE(preserve_gate_tier) && "grant_aligned_base_pass" %in% names(result)
  ) {
    ranking_logical_component(result, "grant_aligned_base_pass")
  } else {
    rep(FALSE, nrow(result))
  }
  order_index <- order(
    if (isTRUE(preserve_gate_tier)) !gate_tier else rep(FALSE, nrow(result)),
    -result$exploratory_final_score,
    -completeness,
    as.character(result[[identity]]),
    na.last = TRUE
  )
  result <- result[order_index, , drop = FALSE]
  result$exploratory_rank <- seq_len(nrow(result))
  rank_candidates <- c(
    "final_evolutionary_rank", "final_rank", "computational_rank"
  )
  recorded_rank <- rank_candidates[rank_candidates %in% names(result)]
  if (length(recorded_rank) > 0L) {
    recorded_rank <- recorded_rank[[1L]]
    result$rank_change_positive_means_moved_up <-
      suppressWarnings(as.integer(result[[recorded_rank]])) -
      result$exploratory_rank
  } else {
    recorded_rank <- character()
  }
  preferred <- c(
    "exploratory_rank", "rank_change_positive_means_moved_up", recorded_rank,
    identity, "primary_group_type", "primary_group_id", "lead_cluster_id",
    "boss_review_status", "grant_aligned_prediction_status",
    "grant_aligned_base_pass", "grant_aligned_final_pass", "final_score",
    "exploratory_final_score", "prestructure_score",
    "exploratory_prestructure_score", "ligandability_score",
    "exploratory_ligandability_score", "structural_score",
    "exploratory_structural_score", "pocket_conservation_score",
    "three_dimensional_pocket_score", "evidence_completeness_fraction"
  )
  preferred <- unique(preferred[preferred %in% names(result)])
  rownames(result) <- NULL
  result[, preferred, drop = FALSE]
}
