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
      return(list(
        relation = relation,
        rank_column = ranks[[1L]],
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

#' Build the ungated top-N recorded pre-structure HOG query.
#'
#' @param relation Ranking relation.
#' @param available Available ranking columns.
#' @param rank_column Authoritative pre-structure HOG rank column.
#' @param max_hogs Number of HOGs to return.
#' @param membership_available Whether root HOG membership is available.
#' @param membership_columns Available membership columns.
#' @param alias Attached database alias.
#' @return Bounded DuckDB SQL query.
build_prestructure_ranked_hog_query <- function(
  relation,
  available,
  rank_column,
  max_hogs = 200L,
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
  source <- qualified_resource_relation(relation = relation, alias = alias)
  order_choices <- unique(c(
    rank_column,
    "final_evolutionary_rank",
    "final_rank",
    "lead_cluster_id",
    "cluster_id",
    "candidate_accessions"
  ))
  order_choices <- order_choices[order_choices %in% available]
  row_order <- paste(
    paste0(
      vapply(order_choices, quote_duckdb_identifier, character(1L)),
      " NULLS LAST"
    ),
    collapse = ", "
  )
  representatives <- prestructure_hog_representative_ctes(
    membership_available = membership_available,
    membership_columns = membership_columns,
    alias = alias
  )
  safe_rank <- quote_duckdb_identifier(rank_column)
  paste0(
    "WITH ranked_source AS (SELECT * EXCLUDE (_e3_hog_row) FROM (SELECT *, ",
    "ROW_NUMBER() OVER (PARTITION BY CAST(primary_group_id AS VARCHAR) ",
    "ORDER BY ", row_order, ") AS _e3_hog_row FROM ", source, " WHERE ",
    "primary_group_id IS NOT NULL AND starts_with(trim(CAST(primary_group_id ",
    "AS VARCHAR)), 'N0.HOG') AND TRY_CAST(", safe_rank, " AS BIGINT) IS NOT ",
    "NULL) WHERE _e3_hog_row = 1), top_hogs AS (SELECT * FROM ranked_source ",
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
