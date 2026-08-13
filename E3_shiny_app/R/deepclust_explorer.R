#' DeepClust and 1KP sequence-neighbourhood query helpers.

deepclust_required_columns <- function() {
  c(
    "representative_id",
    "matched_seed_ids_calculated",
    "raw_member_count",
    "strict_member_count",
    "raw_onekp_sample_count",
    "raw_onekp_species_count",
    "strict_onekp_sample_count",
    "strict_onekp_species_count"
  )
}

deepclust_preferred_columns <- function() {
  c(
    "representative_id",
    "representative_original_id",
    "representative_entry",
    "representative_source_file_sample_id",
    "representative_sample_id",
    "representative_species",
    "representative_onekp_sample_code",
    "matched_seed_ids_calculated",
    "seed_categories",
    "seed_protein_names",
    "raw_member_count",
    "strict_member_count",
    "strict_member_fraction",
    "raw_onekp_sample_count",
    "raw_onekp_species_count",
    "strict_onekp_sample_count",
    "strict_onekp_species_count",
    "raw_named_proteome_count",
    "raw_named_species_count",
    "strict_named_proteome_count",
    "strict_named_species_count",
    "strict_named_proteome_ids",
    "minimum_observed_pident",
    "median_observed_pident",
    "minimum_member_coverage",
    "median_member_coverage"
  )
}

#' Parse pasted inherited-seed identifiers.
#'
#' @param values Character input separated by whitespace, commas or semicolons.
#' @return Unique non-empty identifiers in first-seen order.
parse_deepclust_seed_queries <- function(values) {
  tokens <- unlist(
    strsplit(paste(as.character(values), collapse = " "), "[[:space:],;]+"),
    use.names = FALSE
  )
  tokens <- trimws(tokens)
  unique(tokens[!is.na(tokens) & nzchar(tokens)])
}

#' Build release-level DeepClust/1KP metric SQL.
#'
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_deepclust_metrics_query <- function(alias = "e3_resource") {
  source <- qualified_resource_relation(
    relation = "candidate_evidence",
    alias = alias
  )
  paste0(
    "SELECT COUNT(*)::BIGINT AS cluster_count, ",
    "COALESCE(SUM(raw_member_count), 0)::BIGINT AS raw_cluster_member_links, ",
    "COALESCE(SUM(strict_member_count), 0)::BIGINT ",
    "AS strict_cluster_member_links, COUNT(*) FILTER ",
    "(WHERE raw_onekp_sample_count > 0)::BIGINT AS clusters_with_raw_onekp, ",
    "COUNT(*) FILTER (WHERE strict_onekp_sample_count > 0)::BIGINT ",
    "AS clusters_with_strict_onekp, ",
    "COALESCE(SUM(strict_onekp_sample_count), 0)::BIGINT ",
    "AS strict_onekp_cluster_sample_links, ",
    "COALESCE(SUM(strict_onekp_species_count), 0)::BIGINT ",
    "AS strict_onekp_cluster_species_links FROM ",
    source
  )
}

#' Build strict parsed-1KP coverage-distribution SQL.
#'
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_deepclust_distribution_query <- function(alias = "e3_resource") {
  source <- qualified_resource_relation(
    relation = "candidate_evidence",
    alias = alias
  )
  paste0(
    "SELECT strict_onekp_species_count, COUNT(*)::BIGINT AS cluster_count, ",
    "COALESCE(SUM(strict_member_count), 0)::BIGINT ",
    "AS strict_cluster_member_links FROM ", source,
    " GROUP BY strict_onekp_species_count ORDER BY strict_onekp_species_count"
  )
}

#' Build a bounded filtered sequence-neighbourhood summary query.
#'
#' @param available_columns Candidate-evidence columns.
#' @param seed_queries Optional inherited E3 seed identifiers.
#' @param match_mode Match any or all supplied seeds.
#' @param onekp_mode All clusters, raw 1KP coverage or strict 1KP coverage.
#' @param minimum_strict_onekp_species Minimum parsed strict 1KP species count.
#' @param cluster_query Optional representative-ID substring.
#' @param max_rows Maximum rows.
#' @param contributor_relation Optional group-contributor relation.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_deepclust_summary_query <- function(
  available_columns,
  seed_queries = character(),
  match_mode = c("any", "all"),
  onekp_mode = c("all", "raw", "strict"),
  minimum_strict_onekp_species = 0L,
  cluster_query = "",
  max_rows = 1000L,
  contributor_relation = NULL,
  alias = "e3_resource"
) {
  match_mode <- match.arg(match_mode)
  onekp_mode <- match.arg(onekp_mode)
  missing <- setdiff(deepclust_required_columns(), available_columns)
  if (length(missing) > 0L) {
    stop(
      paste0("Candidate evidence lacks 1KP fields: ", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  minimum <- suppressWarnings(as.integer(minimum_strict_onekp_species))
  if (is.na(minimum) || minimum < 0L || minimum > 1000000L) {
    stop("Minimum strict 1KP species must be between 0 and 1,000,000.", call. = FALSE)
  }
  max_rows <- suppressWarnings(as.integer(max_rows))
  if (is.na(max_rows) || max_rows < 1L || max_rows > 100000L) {
    stop("Maximum DeepClust rows must be between 1 and 100,000.", call. = FALSE)
  }
  source <- qualified_resource_relation(
    relation = "candidate_evidence",
    alias = alias
  )
  selected <- intersect(deepclust_preferred_columns(), available_columns)
  selection <- paste0(
    "evidence.",
    vapply(selected, quote_duckdb_identifier, character(1L)),
    collapse = ", "
  )
  filters <- paste0(
    "COALESCE(evidence.strict_onekp_species_count, 0) >= ",
    minimum
  )
  if (onekp_mode == "raw") {
    filters <- c(filters, "COALESCE(evidence.raw_onekp_sample_count, 0) > 0")
  } else if (onekp_mode == "strict") {
    filters <- c(filters, "COALESCE(evidence.strict_onekp_sample_count, 0) > 0")
  }
  cluster_query <- trimws(as.character(cluster_query %||% ""))
  if (nzchar(cluster_query)) {
    filters <- c(
      filters,
      paste0(
        "strpos(lower(evidence.representative_id), lower('",
        escape_sql_literal(cluster_query),
        "')) > 0"
      )
    )
  }
  seeds <- parse_deepclust_seed_queries(seed_queries)
  if (length(seeds) > 0L) {
    clauses <- vapply(
      seeds,
      function(seed) {
        paste0(
          "list_contains(string_split(lower(COALESCE(",
          "evidence.matched_seed_ids_calculated, '')), ';'), lower('",
          escape_sql_literal(seed),
          "'))"
        )
      },
      character(1L)
    )
    operator <- if (match_mode == "all") " AND " else " OR "
    filters <- c(filters, paste0("(", paste(clauses, collapse = operator), ")"))
  }
  linked_selection <- ""
  linked_join <- ""
  if (!is.null(contributor_relation) && nzchar(contributor_relation)) {
    contributor <- qualified_resource_relation(
      relation = contributor_relation,
      alias = alias
    )
    linked_selection <- paste0(
      ", linked.linked_evolutionary_groups, linked.linked_group_types"
    )
    linked_join <- paste0(
      " LEFT JOIN (SELECT cluster_id, string_agg(DISTINCT ",
      "evolutionary_group_key, ';' ORDER BY evolutionary_group_key) ",
      "AS linked_evolutionary_groups, string_agg(DISTINCT primary_group_type, ",
      "';' ORDER BY primary_group_type) AS linked_group_types FROM ",
      contributor, " GROUP BY cluster_id) AS linked ",
      "ON linked.cluster_id = evidence.representative_id"
    )
  }
  paste0(
    "SELECT ", selection, linked_selection, " FROM ", source, " AS evidence",
    linked_join, " WHERE ", paste(filters, collapse = " AND "),
    " ORDER BY evidence.strict_onekp_species_count DESC, ",
    "evidence.strict_member_count DESC, evidence.representative_id LIMIT ",
    max_rows
  )
}
