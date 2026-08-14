#' Authoritative top-N pre-structure ranking for root-level HOGs.

prestructure_hog_relation_preference <- function() {
  c(
    "final_evolutionary_candidate_prioritisation",
    "evolutionary_candidate_group_ranking",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "prestructure_ranking"
  )
}

prestructure_hog_rank_columns <- function() {
  c("prestructure_evolutionary_group_rank", "evolutionary_group_rank")
}

prestructure_hog_pass_columns <- function() {
  c("grant_aligned_prestructure_pass", "grant_aligned_stringent_pass")
}

prestructure_structural_column_markers <- function() {
  c(
    "druggability", "ligandability", "pocket", "structural",
    "three_dimensional", "sensitivity_", "alignment", "conservation",
    "centroid_distance", "minimum_tm_score", "predictor_agreement", "plddt",
    "alphafold", "colabfold", "foldseek", "usalign", "tm_align", "model",
    "mmcif", "pdb"
  )
}

prestructure_structural_excluded_columns <- function() {
  c(
    "final_evolutionary_rank", "final_rank", "stringent_rank",
    "boss_review_status", "recommendation_status",
    "grant_aligned_prediction_status", "final_score",
    "grant_aligned_base_pass", "grant_aligned_final_pass",
    "conservation_status", "all_assessed_members_pass_mapping",
    "computational_structure_selected", "lead_computational_structure_selected",
    "mean_pairwise_region_overlap", "mean_chemical_group_conservation"
  )
}

#' Select fields suitable for independent structural-review decisions.
#'
#' @param available Source relation columns in published order.
#' @return Ordered pre-structure evidence and provenance columns.
prestructure_review_columns <- function(available) {
  markers <- paste(prestructure_structural_column_markers(), collapse = "|")
  safe <- available[
    !available %in% prestructure_structural_excluded_columns() &
      !grepl(markers, tolower(available))
  ]
  preferred <- c(
    "prestructure_evolutionary_group_rank", "evolutionary_group_rank",
    "primary_group_id", "prestructure_score", "best_prestructure_score",
    "mean_prestructure_score", "minimum_prestructure_score",
    "grant_aligned_prestructure_pass", "grant_aligned_stringent_pass"
  )
  unique(c(preferred[preferred %in% safe], safe))
}

#' Select an authoritative HOG-level pre-structure ranking source.
#'
#' @param relation_columns Named list of available columns by relation.
#' @return Source metadata or NULL when the required rank is unavailable.
select_prestructure_hog_source <- function(relation_columns) {
  for (relation in prestructure_hog_relation_preference()) {
    columns <- relation_columns[[relation]]
    if (is.null(columns) || !"primary_group_id" %in% columns) next
    ranks <- prestructure_hog_rank_columns()
    ranks <- ranks[ranks %in% columns]
    if (length(ranks) > 0L) {
      passes <- prestructure_hog_pass_columns()
      passes <- passes[passes %in% columns]
      return(list(
        relation = relation,
        rank_column = ranks[[1L]],
        pass_column = if (length(passes) > 0L) passes[[1L]] else NULL,
        columns = columns
      ))
    }
  }
  NULL
}

prestructure_hog_representative_ctes <- function(
  membership_available,
  membership_columns,
  alias = "e3_resource"
) {
  required <- c("group_id", "species", "raw_identifier")
  if (!isTRUE(membership_available) || !all(required %in% membership_columns)) {
    return(paste0(
      "hog_representatives AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, ",
      "CAST(NULL AS VARCHAR) AS human_hog_representatives, ",
      "CAST(NULL AS VARCHAR) AS arabidopsis_hog_representatives WHERE FALSE)"
    ))
  }
  membership <- human_hog_membership_cte(
    membership_columns = membership_columns,
    alias = alias
  )
  paste0(
    membership, ", representative_members AS (SELECT hog_id, species, ",
    "coalesce(nullif(trim(parsed_accession), ''), ",
    "nullif(trim(parsed_entry), ''), nullif(trim(raw_identifier), '')) ",
    "AS representative FROM membership), hog_representatives AS (",
    "SELECT hog_id, coalesce(string_agg(DISTINCT representative, ';' ",
    "ORDER BY representative) FILTER (WHERE species = 'Homo_sapiens' AND ",
    "representative IS NOT NULL), '') AS human_hog_representatives, ",
    "coalesce(string_agg(DISTINCT representative, ';' ORDER BY representative) ",
    "FILTER (WHERE species = 'Arabidopsis_thaliana' AND representative IS NOT ",
    "NULL), '') AS arabidopsis_hog_representatives ",
    "FROM representative_members GROUP BY hog_id)"
  )
}

#' Build the independent structural-review HOG shortlist query.
#'
#' @param relation Ranking relation.
#' @param available Available ranking columns.
#' @param rank_column Authoritative pre-structure HOG rank column.
#' @param max_hogs Number of HOGs to return.
#' @param passes_only Whether to require the recorded pre-structure pass.
#' @param pass_column Optional group-level pre-structure pass field.
#' @param membership_available Whether root HOG membership is available.
#' @param membership_columns Available membership columns.
#' @param alias Attached database alias.
#' @return Bounded DuckDB SQL query.
build_prestructure_ranked_hog_query <- function(
  relation,
  available,
  rank_column,
  max_hogs = 200L,
  passes_only = FALSE,
  pass_column = NULL,
  membership_available = FALSE,
  membership_columns = character(),
  alias = "e3_resource"
) {
  limit <- suppressWarnings(as.integer(max_hogs))
  if (length(limit) != 1L || is.na(limit) || limit < 1L || limit > 10000L) {
    stop("Maximum ranked HOGs must be between 1 and 10000.", call. = FALSE)
  }
  if (!"primary_group_id" %in% available || !rank_column %in% available) {
    stop("The ranking relation lacks the required HOG rank fields.", call. = FALSE)
  }
  if (length(passes_only) != 1L || is.na(passes_only) || !is.logical(passes_only)) {
    stop("passes_only must be a single boolean value.", call. = FALSE)
  }
  if (
    isTRUE(passes_only) &&
      (length(pass_column) != 1L || is.na(pass_column) ||
        !pass_column %in% available)
  ) {
    stop(
      "The source has no group-level recorded pre-structure pass field.",
      call. = FALSE
    )
  }
  source <- qualified_resource_relation(relation = relation, alias = alias)
  order_specification <- c(
    stats::setNames("ASC", rank_column),
    prestructure_score = "DESC",
    best_prestructure_score = "DESC",
    mean_prestructure_score = "DESC",
    lead_computational_rank = "ASC",
    lead_cluster_id = "ASC",
    cluster_id = "ASC",
    candidate_accessions = "ASC"
  )
  order_specification <- order_specification[
    names(order_specification) %in% available
  ]
  row_order <- paste(
    paste0(
      vapply(
        names(order_specification),
        quote_duckdb_identifier,
        character(1L)
      ),
      " ", unname(order_specification), " NULLS LAST"
    ),
    collapse = ", "
  )
  selected <- prestructure_review_columns(available = available)
  if (length(selected) == 0L) {
    stop("No non-structural fields are available for the shortlist.", call. = FALSE)
  }
  source_select <- paste(
    vapply(selected, quote_duckdb_identifier, character(1L)),
    collapse = ", "
  )
  eligibility <- if (isTRUE(passes_only)) {
    paste0(
      " AND coalesce(TRY_CAST(", quote_duckdb_identifier(pass_column),
      " AS BOOLEAN), FALSE)"
    )
  } else {
    ""
  }
  representatives <- prestructure_hog_representative_ctes(
    membership_available = membership_available,
    membership_columns = membership_columns,
    alias = alias
  )
  safe_rank <- quote_duckdb_identifier(rank_column)
  paste0(
    "WITH ranked_source AS (SELECT * EXCLUDE (_e3_hog_row) FROM (SELECT ",
    source_select, ", ",
    "ROW_NUMBER() OVER (PARTITION BY CAST(primary_group_id AS VARCHAR) ",
    "ORDER BY ", row_order, ") AS _e3_hog_row FROM ", source, " WHERE ",
    "primary_group_id IS NOT NULL AND starts_with(trim(CAST(primary_group_id ",
    "AS VARCHAR)), 'N0.HOG') AND TRY_CAST(", safe_rank, " AS BIGINT) IS NOT ",
    "NULL", eligibility, ") WHERE _e3_hog_row = 1), top_hogs AS (SELECT * ",
    "FROM ranked_source ",
    "ORDER BY TRY_CAST(", safe_rank, " AS BIGINT), CAST(primary_group_id AS ",
    "VARCHAR) LIMIT ", limit, "), ", representatives, " SELECT t.*, ",
    "coalesce(h.human_hog_representatives, '') AS human_hog_representatives, ",
    "coalesce(h.arabidopsis_hog_representatives, '') AS ",
    "arabidopsis_hog_representatives FROM top_hogs t LEFT JOIN ",
    "hog_representatives h ON h.hog_id = CAST(t.primary_group_id AS VARCHAR) ",
    "ORDER BY TRY_CAST(t.", safe_rank, " AS BIGINT), ",
    "CAST(t.primary_group_id AS VARCHAR)"
  )
}

#' Filter within an already selected top-N HOG list.
#'
#' @param data Ranked HOG rows.
#' @param query Literal search text.
#' @return Filtered rows without rank recalculation.
filter_prestructure_ranked_hogs <- function(data, query = "") {
  clean <- if (length(query) == 0L || is.na(query[[1L]])) {
    ""
  } else {
    tolower(trimws(as.character(query[[1L]])))
  }
  if (!nzchar(clean) || nrow(data) == 0L) return(data)
  preferred <- c(
    "primary_group_id", "candidate_accessions", "matched_seed_ids_calculated",
    "matched_e3_seeds", "seed_protein_names", "human_hog_representatives",
    "arabidopsis_hog_representatives"
  )
  columns <- intersect(preferred, names(data))
  if (length(columns) == 0L) return(data[0, , drop = FALSE])
  matched <- Reduce(`|`, lapply(columns, function(column) {
    grepl(
      clean,
      tolower(ifelse(is.na(data[[column]]), "", data[[column]])),
      fixed = TRUE
    )
  }))
  data[matched, , drop = FALSE]
}

#' Summarise the visible recorded HOG ranks.
#'
#' @param data Ranked HOG rows after the optional text filter.
#' @param rank_column Authoritative recorded rank field.
#' @return Named list containing row count, best rank and lowest shown rank.
summarise_prestructure_hog_ranks <- function(data, rank_column) {
  count <- nrow(data)
  if (
    count == 0L || length(rank_column) != 1L || is.na(rank_column) ||
      !rank_column %in% names(data)
  ) {
    return(list(
      returned_count = count,
      best_rank = NA_real_,
      lowest_rank = NA_real_
    ))
  }
  values <- suppressWarnings(as.numeric(data[[rank_column]]))
  values <- values[!is.na(values)]
  if (length(values) == 0L) {
    return(list(
      returned_count = count,
      best_rank = NA_real_,
      lowest_rank = NA_real_
    ))
  }
  list(
    returned_count = count,
    best_rank = min(values),
    lowest_rank = max(values)
  )
}
