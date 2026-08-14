#' Queries for human-containing and plant-and-human root-level HOGs.

human_hog_ranking_relations <- function() {
  c(
    "final_evolutionary_candidate_prioritisation",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "evolutionary_candidate_group_ranking",
    "prestructure_ranking"
  )
}

human_hog_rank_columns <- function() {
  c(
    "final_evolutionary_rank",
    "final_rank",
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank"
  )
}

#' Validate one human-HOG view.
#'
#' @param view `human` or `plant_and_human`.
#' @return Validated view.
validate_human_hog_view <- function(view) {
  if (
    length(view) != 1L ||
      is.na(view) ||
      !view %in% c("human", "plant_and_human")
  ) {
    stop("Unsupported human-HOG view.", call. = FALSE)
  }
  view
}

#' Return the 12 curated target-plant source labels.
#'
#' @return Character vector of source species names.
human_hog_target_plants <- function() {
  taxonomy <- load_species_taxonomy()
  plants <- taxonomy$source_species_name[taxonomy$role == "target_plant"]
  sort(unique(plants[!is.na(plants) & nzchar(trimws(plants))]))
}

#' Select the strongest available HOG-linked ranking relation.
#'
#' @param relation_columns Named list of available columns by relation.
#' @return Relation name or NULL.
select_human_hog_ranking_relation <- function(relation_columns) {
  for (relation in human_hog_ranking_relations()) {
    columns <- relation_columns[[relation]]
    if (
      !is.null(columns) &&
        "primary_group_id" %in% columns &&
        any(human_hog_rank_columns() %in% columns)
    ) {
      return(relation)
    }
  }
  NULL
}

human_hog_first_column <- function(columns, choices) {
  present <- choices[choices %in% columns]
  if (length(present) == 0L) NULL else present[[1L]]
}

human_hog_text_expression <- function(columns, column, prefix = NULL) {
  if (is.null(column) || !column %in% columns) {
    return("CAST(NULL AS VARCHAR)")
  }
  qualified <- quote_duckdb_identifier(column)
  if (!is.null(prefix)) {
    qualified <- paste0(prefix, ".", qualified)
  }
  paste0("CAST(", qualified, " AS VARCHAR)")
}

human_hog_typed_expression <- function(
  columns,
  choices,
  type
) {
  column <- human_hog_first_column(columns, choices)
  if (is.null(column)) {
    return(paste0("CAST(NULL AS ", type, ")"))
  }
  paste0(
    "TRY_CAST(", quote_duckdb_identifier(column), " AS ", type, ")"
  )
}

human_hog_text_aggregate <- function(expression, alias) {
  paste0(
    "string_agg(DISTINCT ", expression, ", ';' ORDER BY ", expression, ") ",
    "FILTER (WHERE ", expression, " IS NOT NULL AND trim(", expression,
    ") != '') AS ", quote_duckdb_identifier(alias)
  )
}

human_hog_membership_cte <- function(
  membership_columns,
  alias = "e3_resource"
) {
  required <- c("group_id", "species", "raw_identifier")
  missing <- setdiff(required, membership_columns)
  if (length(missing) > 0L) {
    stop(
      paste("hierarchical_membership is missing:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  optional <- c(
    "record_type", "orthogroup_id", "gene_tree_parent_clade",
    "parsed_accession", "parsed_entry", "review_status", "identifier_format",
    "mapping_status", "mapping_reason", "source_file", "source_row"
  )
  optional_sql <- vapply(optional, function(column) {
    paste0(
      human_hog_text_expression(membership_columns, column),
      " AS ", quote_duckdb_identifier(column)
    )
  }, character(1L))
  source <- qualified_resource_relation("hierarchical_membership", alias)
  paste0(
    "membership AS (SELECT CAST(group_id AS VARCHAR) AS hog_id, ",
    "CAST(species AS VARCHAR) AS species, ",
    "CAST(raw_identifier AS VARCHAR) AS raw_identifier, ",
    paste(optional_sql, collapse = ", "), " FROM ", source,
    " WHERE group_id IS NOT NULL AND ",
    "starts_with(trim(CAST(group_id AS VARCHAR)), 'N0.HOG') AND ",
    "trim(CAST(group_id AS VARCHAR)) != '')"
  )
}

human_hog_ranking_cte <- function(
  ranking_relation,
  ranking_columns,
  alias = "e3_resource"
) {
  if (is.null(ranking_relation)) {
    return(paste0(
      "ranked AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, ",
      "CAST(NULL AS BIGINT) AS ranking_position, ",
      "CAST(NULL AS VARCHAR) AS ranking_statuses, ",
      "CAST(NULL AS VARCHAR) AS linked_clusters, ",
      "CAST(NULL AS VARCHAR) AS candidate_accessions, ",
      "CAST(NULL AS VARCHAR) AS matched_e3_seeds, ",
      "CAST(NULL AS VARCHAR) AS seed_protein_names, ",
      "CAST(NULL AS DOUBLE) AS final_score, ",
      "CAST(NULL AS BOOLEAN) AS prestructure_pass, ",
      "CAST(NULL AS BOOLEAN) AS final_pass WHERE FALSE)"
    ))
  }
  rank <- human_hog_typed_expression(
    ranking_columns,
    human_hog_rank_columns(),
    "BIGINT"
  )
  status <- human_hog_text_expression(
    ranking_columns,
    human_hog_first_column(
      ranking_columns,
      c(
        "recommendation_status", "custom_status",
        "grant_aligned_criteria_status", "criteria_status"
      )
    )
  )
  cluster <- human_hog_text_expression(
    ranking_columns,
    human_hog_first_column(ranking_columns, c("lead_cluster_id", "cluster_id"))
  )
  accessions <- human_hog_text_expression(
    ranking_columns,
    human_hog_first_column(
      ranking_columns,
      c("candidate_accessions", "candidate_accession")
    )
  )
  seeds <- human_hog_text_expression(
    ranking_columns,
    human_hog_first_column(
      ranking_columns,
      c("discovery_matched_seed_ids_calculated", "matched_seed_ids_calculated")
    )
  )
  seed_names <- human_hog_text_expression(
    ranking_columns,
    human_hog_first_column(
      ranking_columns,
      c("discovery_seed_protein_names", "seed_protein_names")
    )
  )
  score <- human_hog_typed_expression(
    ranking_columns,
    c("final_score", "prestructure_score"),
    "DOUBLE"
  )
  prestructure <- human_hog_typed_expression(
    ranking_columns,
    c("grant_aligned_prestructure_pass", "grant_aligned_stringent_pass"),
    "BOOLEAN"
  )
  final <- human_hog_typed_expression(
    ranking_columns,
    "grant_aligned_final_pass",
    "BOOLEAN"
  )
  source <- qualified_resource_relation(ranking_relation, alias)
  type_filter <- if ("primary_group_type" %in% ranking_columns) {
    paste0(
      " AND (upper(CAST(primary_group_type AS VARCHAR)) IN ",
      "('HIERARCHICAL_ORTHOGROUP', 'HOG') OR ",
      "starts_with(CAST(primary_group_id AS VARCHAR), 'N0.HOG'))"
    )
  } else {
    ""
  }
  paste0(
    "ranked AS (SELECT CAST(primary_group_id AS VARCHAR) AS hog_id, ",
    "min(", rank, ") AS ranking_position, ",
    human_hog_text_aggregate(status, "ranking_statuses"), ", ",
    human_hog_text_aggregate(cluster, "linked_clusters"), ", ",
    human_hog_text_aggregate(accessions, "candidate_accessions"), ", ",
    human_hog_text_aggregate(seeds, "matched_e3_seeds"), ", ",
    human_hog_text_aggregate(seed_names, "seed_protein_names"), ", ",
    "max(", score, ") AS final_score, ",
    "bool_or(coalesce(", prestructure, ", FALSE)) AS prestructure_pass, ",
    "bool_or(coalesce(", final, ", FALSE)) AS final_pass FROM ", source,
    " WHERE primary_group_id IS NOT NULL ", type_filter,
    " GROUP BY CAST(primary_group_id AS VARCHAR))"
  )
}

human_hog_base_ctes <- function(
  view,
  membership_columns,
  ranking_relation = NULL,
  ranking_columns = character(),
  alias = "e3_resource"
) {
  view <- validate_human_hog_view(view)
  plants <- human_hog_target_plants()
  if (length(plants) == 0L) {
    stop("The taxonomy manifest has no target plants.", call. = FALSE)
  }
  plant_values <- paste0("('", vapply(
    plants,
    escape_sql_literal,
    character(1L)
  ), "')", collapse = ", ")
  plant_gate <- if (view == "plant_and_human") {
    " AND plant_member_count > 0"
  } else {
    ""
  }
  representative <- paste0(
    "coalesce(nullif(trim(parsed_accession), ''), ",
    "nullif(trim(parsed_entry), ''), nullif(trim(raw_identifier), ''))"
  )
  paste(
    human_hog_membership_cte(membership_columns, alias),
    "human_species(species) AS (VALUES ('Homo_sapiens'))",
    paste0("target_plants(species) AS (VALUES ", plant_values, ")"),
    paste0(
      "member_classes AS (SELECT m.*, m.species = h.species AS is_human, ",
      "EXISTS (SELECT 1 FROM target_plants p WHERE p.species = m.species) ",
      "AS is_target_plant FROM membership m CROSS JOIN human_species h)"
    ),
    paste0(
      "representative_members AS (SELECT hog_id, species, is_human, ",
      representative, " AS representative FROM member_classes)"
    ),
    paste0(
      "hog_representatives AS (SELECT hog_id, ",
      "coalesce(string_agg(DISTINCT representative, ';' ORDER BY ",
      "representative) FILTER (WHERE is_human AND representative IS NOT NULL), ",
      "'') AS human_hog_representatives, ",
      "coalesce(string_agg(DISTINCT representative, ';' ORDER BY ",
      "representative) FILTER (WHERE species = 'Arabidopsis_thaliana' AND ",
      "representative IS NOT NULL), '') AS arabidopsis_hog_representatives ",
      "FROM representative_members GROUP BY hog_id)"
    ),
    paste0(
      "hog_counts AS (SELECT hog_id, count(*) AS member_count, ",
      "count(DISTINCT species) AS species_count, ",
      "count(*) FILTER (WHERE is_human) AS human_member_count, ",
      "count(*) FILTER (WHERE is_target_plant) AS plant_member_count, ",
      "count(DISTINCT species) FILTER (WHERE is_target_plant) ",
      "AS plant_species_count FROM member_classes GROUP BY hog_id)"
    ),
    paste0(
      "eligible_hogs AS (SELECT * FROM hog_counts ",
      "WHERE human_member_count > 0", plant_gate, ")"
    ),
    human_hog_ranking_cte(ranking_relation, ranking_columns, alias),
    sep = ", "
  )
}

#' Build one-row-per-HOG summary SQL.
#'
#' @param view Human-HOG view.
#' @param membership_columns Available membership columns.
#' @param ranking_relation Optional ranking relation.
#' @param ranking_columns Available ranking columns.
#' @param max_rows Defensive maximum rows.
#' @param alias Attached database alias.
#' @return DuckDB SQL query.
build_human_hog_summary_query <- function(
  view,
  membership_columns,
  ranking_relation = NULL,
  ranking_columns = character(),
  max_rows = 10000L,
  alias = "e3_resource"
) {
  max_rows <- max(1L, min(100000L, as.integer(max_rows)))
  ctes <- human_hog_base_ctes(
    view,
    membership_columns,
    ranking_relation,
    ranking_columns,
    alias
  )
  source_label <- if (is.null(ranking_relation)) "" else ranking_relation
  paste0(
    "WITH ", ctes, ", summaries AS (SELECT c.hog_id, c.member_count, ",
    "c.species_count, c.human_member_count, c.plant_member_count, ",
    "c.plant_species_count, ",
    "string_agg(DISTINCT m.species, ';' ORDER BY m.species) AS species_present, ",
    "string_agg(DISTINCT m.species, ';' ORDER BY m.species) ",
    "FILTER (WHERE m.is_target_plant) AS plant_species_present, ",
    "string_agg(DISTINCT m.parsed_accession, ';' ORDER BY m.parsed_accession) ",
    "FILTER (WHERE m.is_human AND coalesce(m.parsed_accession, '') != '') ",
    "AS human_accessions, string_agg(DISTINCT m.parsed_entry, ';' ",
    "ORDER BY m.parsed_entry) FILTER (WHERE m.is_human AND ",
    "coalesce(m.parsed_entry, '') != '') AS human_entries, ",
    "string_agg(DISTINCT m.raw_identifier, ';' ORDER BY m.raw_identifier) ",
    "FILTER (WHERE m.is_human) AS human_raw_identifiers FROM eligible_hogs c ",
    "INNER JOIN member_classes m USING (hog_id) GROUP BY c.hog_id, ",
    "c.member_count, c.species_count, c.human_member_count, ",
    "c.plant_member_count, c.plant_species_count) SELECT s.hog_id, ",
    "h.human_hog_representatives, h.arabidopsis_hog_representatives, ",
    "s.member_count, s.species_count, s.human_member_count, ",
    "s.plant_member_count, s.plant_species_count, s.species_present, ",
    "s.plant_species_present, s.human_accessions, s.human_entries, ",
    "s.human_raw_identifiers, ",
    "CASE WHEN r.hog_id IS NULL THEN 'NOT_IN_CANDIDATE_RANKING' ",
    "ELSE 'RANKED' END AS ranking_availability, r.ranking_position, ",
    "r.ranking_statuses, r.linked_clusters, r.candidate_accessions, ",
    "r.matched_e3_seeds, r.seed_protein_names, r.final_score, ",
    "r.prestructure_pass, r.final_pass, '",
    escape_sql_literal(source_label), "' AS ranking_source FROM summaries s ",
    "INNER JOIN hog_representatives h USING (hog_id) ",
    "LEFT JOIN ranked r USING (hog_id) ORDER BY r.ranking_position NULLS LAST, ",
    "s.hog_id LIMIT ", max_rows
  )
}

human_hog_sequence_cte <- function(
  sequence_columns,
  sequence_available,
  alias = "e3_resource"
) {
  required <- c("group_id", "species", "raw_identifier")
  if (!isTRUE(sequence_available) || !all(required %in% sequence_columns)) {
    return(paste0(
      "sequence_annotations AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, ",
      "CAST(NULL AS VARCHAR) AS species, CAST(NULL AS VARCHAR) AS raw_identifier, ",
      "CAST(NULL AS VARCHAR) AS linked_clusters, ",
      "CAST(NULL AS VARCHAR) AS candidate_accessions, ",
      "CAST(NULL AS VARCHAR) AS internal_ids, ",
      "CAST(NULL AS BOOLEAN) AS is_input_candidate, ",
      "CAST(NULL AS BIGINT) AS sequence_length, ",
      "CAST(NULL AS VARCHAR) AS protein_sequence WHERE FALSE)"
    ))
  }
  text <- function(column) {
    human_hog_text_expression(sequence_columns, column)
  }
  length_expression <- if ("sequence_length" %in% sequence_columns) {
    "TRY_CAST(sequence_length AS BIGINT)"
  } else {
    "CAST(NULL AS BIGINT)"
  }
  input_expression <- if ("is_input_candidate" %in% sequence_columns) {
    "TRY_CAST(is_input_candidate AS BOOLEAN)"
  } else {
    "CAST(NULL AS BOOLEAN)"
  }
  record_filter <- if ("record_type" %in% sequence_columns) {
    " WHERE upper(CAST(record_type AS VARCHAR)) = 'HIERARCHICAL_ORTHOGROUP'"
  } else {
    ""
  }
  source <- qualified_resource_relation(
    "candidate_group_member_sequences",
    alias
  )
  paste0(
    "sequence_annotations AS (SELECT CAST(group_id AS VARCHAR) AS hog_id, ",
    "CAST(species AS VARCHAR) AS species, ",
    "CAST(raw_identifier AS VARCHAR) AS raw_identifier, ",
    human_hog_text_aggregate(text("cluster_id"), "linked_clusters"), ", ",
    human_hog_text_aggregate(
      text("candidate_accessions_for_cluster"),
      "candidate_accessions"
    ), ", ",
    human_hog_text_aggregate(text("internal_id"), "internal_ids"), ", ",
    "bool_or(coalesce(", input_expression, ", FALSE)) AS is_input_candidate, ",
    "max(", length_expression, ") AS sequence_length, ",
    "max(", text("protein_sequence"), ") AS protein_sequence FROM ", source,
    record_filter, " GROUP BY CAST(group_id AS VARCHAR), ",
    "CAST(species AS VARCHAR), CAST(raw_identifier AS VARCHAR))"
  )
}

human_hog_alias_cte <- function(
  alias_columns,
  alias_available,
  alias = "e3_resource"
) {
  required <- c("primary_group_id", "member_accession", "identifier_value")
  if (!isTRUE(alias_available) || !all(required %in% alias_columns)) {
    return(paste0(
      "aliases AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, ",
      "CAST(NULL AS VARCHAR) AS member_accession, ",
      "CAST(NULL AS VARCHAR) AS alias_species, ",
      "CAST(NULL AS VARCHAR) AS identifier_types, ",
      "CAST(NULL AS VARCHAR) AS identifier_values WHERE FALSE)"
    ))
  }
  text <- function(column) human_hog_text_expression(alias_columns, column)
  source <- qualified_resource_relation("candidate_identifier_aliases", alias)
  paste0(
    "aliases AS (SELECT CAST(primary_group_id AS VARCHAR) AS hog_id, ",
    "upper(CAST(member_accession AS VARCHAR)) AS member_accession, ",
    human_hog_text_aggregate(text("species_column"), "alias_species"), ", ",
    human_hog_text_aggregate(text("identifier_type"), "identifier_types"), ", ",
    human_hog_text_aggregate(text("identifier_value"), "identifier_values"),
    " FROM ", source, " WHERE primary_group_id IS NOT NULL AND ",
    "member_accession IS NOT NULL GROUP BY CAST(primary_group_id AS VARCHAR), ",
    "upper(CAST(member_accession AS VARCHAR)))"
  )
}

#' Build complete or human-only member annotation SQL.
#'
#' @param view Human-HOG view.
#' @param member_scope `human` or `all`.
#' @param membership_columns Available membership columns.
#' @param ranking_relation Optional ranking relation.
#' @param ranking_columns Available ranking columns.
#' @param sequence_available Whether sequence annotations exist.
#' @param sequence_columns Available sequence columns.
#' @param alias_available Whether identifier aliases exist.
#' @param alias_columns Available alias columns.
#' @param max_rows Defensive maximum rows.
#' @param alias Attached database alias.
#' @return DuckDB SQL query.
build_human_hog_member_query <- function(
  view,
  member_scope,
  membership_columns,
  ranking_relation = NULL,
  ranking_columns = character(),
  sequence_available = FALSE,
  sequence_columns = character(),
  alias_available = FALSE,
  alias_columns = character(),
  max_rows = 10000L,
  alias = "e3_resource"
) {
  validate_human_hog_view(view)
  if (!member_scope %in% c("human", "all")) {
    stop("Unsupported human-HOG member scope.", call. = FALSE)
  }
  max_rows <- max(1L, min(100000L, as.integer(max_rows)))
  ctes <- human_hog_base_ctes(
    view,
    membership_columns,
    ranking_relation,
    ranking_columns,
    alias
  )
  sequence_cte <- human_hog_sequence_cte(
    sequence_columns,
    sequence_available,
    alias
  )
  alias_cte <- human_hog_alias_cte(alias_columns, alias_available, alias)
  member_filter <- if (member_scope == "human") " WHERE m.is_human" else ""
  paste0(
    "WITH ", ctes, ", ", sequence_cte, ", ", alias_cte,
    " SELECT m.hog_id, ",
    "h.human_hog_representatives, h.arabidopsis_hog_representatives, ",
    "CASE WHEN r.hog_id IS NULL THEN 'NOT_IN_CANDIDATE_RANKING' ",
    "ELSE 'RANKED' END AS ranking_availability, r.ranking_position, ",
    "r.ranking_statuses, r.final_score, r.prestructure_pass, r.final_pass, ",
    "r.linked_clusters AS ranked_linked_clusters, ",
    "r.candidate_accessions AS ranked_candidate_accessions, ",
    "r.matched_e3_seeds, r.seed_protein_names, ",
    "CASE WHEN m.is_human THEN 'HUMAN' WHEN m.is_target_plant THEN ",
    "'TARGET_PLANT' ELSE 'OTHER_ORTHOFINDER_INPUT' END AS member_class, ",
    "m.species, m.raw_identifier, m.parsed_accession, m.parsed_entry, ",
    "m.review_status, m.identifier_format, m.mapping_status, m.mapping_reason, ",
    "m.orthogroup_id, m.gene_tree_parent_clade, m.source_file, m.source_row, ",
    "s.linked_clusters AS sequence_linked_clusters, ",
    "s.candidate_accessions AS sequence_candidate_accessions, s.internal_ids, ",
    "s.is_input_candidate, s.sequence_length, s.protein_sequence, ",
    "a.alias_species, a.identifier_types AS available_alias_types, ",
    "a.identifier_values AS available_aliases FROM ",
    "member_classes m INNER JOIN eligible_hogs e USING (hog_id) ",
    "INNER JOIN hog_representatives h USING (hog_id) ",
    "LEFT JOIN ranked r USING (hog_id) LEFT JOIN sequence_annotations s ",
    "ON s.hog_id = m.hog_id AND s.species = m.species AND ",
    "s.raw_identifier = m.raw_identifier LEFT JOIN aliases a ON ",
    "a.hog_id = m.hog_id AND a.member_accession = ",
    "upper(coalesce(m.parsed_accession, ''))", member_filter,
    " ORDER BY r.ranking_position NULLS LAST, m.hog_id, ",
    "CASE WHEN m.is_human THEN 0 WHEN m.is_target_plant THEN 1 ELSE 2 END, ",
    "m.species, m.raw_identifier LIMIT ", max_rows
  )
}

#' Filter HOG results while retaining every row of a matched HOG.
#'
#' @param summary HOG summary rows.
#' @param human_members Human member rows.
#' @param all_members Complete member rows.
#' @param query Literal search text.
#' @return Named list of consistently filtered tables.
filter_human_hog_results <- function(
  summary,
  human_members,
  all_members,
  query = ""
) {
  clean <- tolower(trimws(as.character(query[[1L]])))
  if (!nzchar(clean)) {
    return(list(
      summary = summary,
      human_members = human_members,
      all_members = all_members
    ))
  }
  matching_hogs <- function(data, columns) {
    columns <- intersect(columns, names(data))
    if (nrow(data) == 0L || length(columns) == 0L) return(character())
    matched <- Reduce(`|`, lapply(columns, function(column) {
      grepl(clean, tolower(ifelse(is.na(data[[column]]), "", data[[column]])),
        fixed = TRUE
      )
    }))
    as.character(data$hog_id[matched])
  }
  hogs <- unique(c(
    matching_hogs(
      summary,
      c(
        "hog_id", "human_hog_representatives",
        "arabidopsis_hog_representatives", "human_accessions", "human_entries",
        "human_raw_identifiers", "matched_e3_seeds", "seed_protein_names"
      )
    ),
    matching_hogs(
      human_members,
      c(
        "hog_id", "human_hog_representatives",
        "arabidopsis_hog_representatives", "parsed_accession", "parsed_entry",
        "raw_identifier",
        "matched_e3_seeds", "seed_protein_names", "available_aliases"
      )
    )
  ))
  list(
    summary = summary[summary$hog_id %in% hogs, , drop = FALSE],
    human_members = human_members[
      human_members$hog_id %in% hogs,
      ,
      drop = FALSE
    ],
    all_members = all_members[all_members$hog_id %in% hogs, , drop = FALSE]
  )
}
