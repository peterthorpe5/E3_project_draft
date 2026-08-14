#' Known-E3 seed catalogue reconstructed from the loaded resource.

seed_catalogue_authority_relation <- function() "known_e3_seeds"

seed_catalogue_summary_relation_preference <- function() {
  c("candidate_evidence", "e3_cluster_candidate_evidence")
}

seed_catalogue_id_columns <- function() {
  c(
    "matched_seed_ids_calculated", "discovery_matched_seed_ids_calculated",
    "known_e3_seed_ids", "matched_e3_seeds"
  )
}

seed_catalogue_cluster_columns <- function() c("cluster_id", "representative_id")

seed_catalogue_annotation_fields <- function() {
  list(
    associated_seed_protein_names = c(
      "seed_protein_names", "discovery_seed_protein_names"
    ),
    associated_seed_categories = c(
      "seed_categories", "discovery_seed_categories"
    ),
    associated_seed_review_statuses = c(
      "seed_review_statuses", "discovery_seed_review_statuses"
    ),
    associated_seed_ubiquitin_go_statuses = c(
      "seed_ubiquitin_go_statuses", "discovery_seed_ubiquitin_go_statuses"
    ),
    associated_seed_organisms = c(
      "seed_organisms", "discovery_seed_organisms"
    )
  )
}

seed_catalogue_exact_annotation_fields <- function() {
  c(
    "seed_protein_names", "seed_category", "seed_review_status",
    "seed_ubiquitin_go_status", "seed_exclusion_go_term", "seed_organism",
    "seed_taxon_id", "seed_sequence_md5", "seed_evidence_type", "seed_source"
  )
}

seed_catalogue_first_column <- function(available, choices) {
  selected <- choices[choices %in% available]
  if (length(selected) == 0L) return(NULL)
  selected[[1L]]
}

#' Resolve seed evidence and optional sequence sources.
#'
#' @param relation_columns Named source columns by relation.
#' @return Capability metadata.
seed_catalogue_capability <- function(relation_columns) {
  summary_relation <- NULL
  summary_columns <- character()
  summary_seed_column <- NULL
  summary_cluster_column <- NULL
  for (relation in seed_catalogue_summary_relation_preference()) {
    columns <- relation_columns[[relation]]
    if (is.null(columns)) next
    seed_column <- seed_catalogue_first_column(
      available = columns,
      choices = seed_catalogue_id_columns()
    )
    if (is.null(seed_column)) next
    cluster_column <- seed_catalogue_first_column(
      available = columns,
      choices = seed_catalogue_cluster_columns()
    )
    summary_relation <- relation
    summary_columns <- columns
    summary_seed_column <- seed_column
    summary_cluster_column <- cluster_column
    break
  }
  sequence_columns <- relation_columns[["candidate_group_member_sequences"]]
  sequence_columns <- sequence_columns %||% character()
  authority <- seed_catalogue_authority_relation()
  authority_columns <- relation_columns[[authority]] %||% character()
  if ("seed_id" %in% authority_columns) {
    return(list(
      available = TRUE,
      mode = "authority",
      relation = authority,
      columns = authority_columns,
      seed_id_column = "seed_id",
      cluster_column = NULL,
      summary_relation = summary_relation,
      summary_columns = summary_columns,
      summary_seed_column = summary_seed_column,
      summary_cluster_column = summary_cluster_column,
      sequence_available = all(
        c("raw_identifier", "protein_sequence") %in% sequence_columns
      ),
      sequence_columns = sequence_columns
    ))
  }
  if (!is.null(summary_relation)) {
    return(list(
      available = TRUE,
      mode = "cluster_summary",
      relation = summary_relation,
      columns = summary_columns,
      seed_id_column = summary_seed_column,
      cluster_column = summary_cluster_column,
      summary_relation = summary_relation,
      summary_columns = summary_columns,
      summary_seed_column = summary_seed_column,
      summary_cluster_column = summary_cluster_column,
      sequence_available = all(
        c("raw_identifier", "protein_sequence") %in% sequence_columns
      ),
      sequence_columns = sequence_columns
    ))
  }
  list(
    available = FALSE,
    mode = NULL,
    relation = NULL,
    columns = character(),
    seed_id_column = NULL,
    cluster_column = NULL,
    summary_relation = NULL,
    summary_columns = character(),
    summary_seed_column = NULL,
    summary_cluster_column = NULL,
    sequence_available = FALSE,
    sequence_columns = character()
  )
}

seed_catalogue_aggregate <- function(available, choices, alias) {
  column <- seed_catalogue_first_column(available = available, choices = choices)
  if (is.null(column)) {
    return(paste0("CAST('' AS VARCHAR) AS ", quote_duckdb_identifier(alias)))
  }
  expression <- paste0(
    "nullif(trim(CAST(", quote_duckdb_identifier(column), " AS VARCHAR)), '')"
  )
  paste0(
    "coalesce(string_agg(DISTINCT ", expression, ", ';' ORDER BY ", expression,
    ") FILTER (WHERE ", expression, " IS NOT NULL), '') AS ",
    quote_duckdb_identifier(alias)
  )
}

seed_catalogue_sequence_cte <- function(capability, alias = "e3_resource") {
  if (!isTRUE(capability$sequence_available)) {
    return(paste0(
      "seed_sequences AS (SELECT CAST(NULL AS VARCHAR) AS seed_id, ",
      "CAST(NULL AS BIGINT) AS sequence_match_count, CAST(NULL AS BIGINT) AS ",
      "distinct_sequence_count, CAST(NULL AS VARCHAR) AS sequence_species, ",
      "CAST(NULL AS VARCHAR) AS sequence_identifiers, CAST(NULL AS VARCHAR) AS ",
      "protein_sequence WHERE FALSE)"
    ))
  }
  columns <- capability$sequence_columns
  accession <- if ("parsed_accession" %in% columns) {
    "CAST(parsed_accession AS VARCHAR)"
  } else {
    "CAST(NULL AS VARCHAR)"
  }
  species <- if ("species" %in% columns) {
    "CAST(species AS VARCHAR)"
  } else {
    "CAST('' AS VARCHAR)"
  }
  relation <- qualified_resource_relation(
    relation = "candidate_group_member_sequences",
    alias = alias
  )
  paste0(
    "sequence_rows AS (SELECT coalesce(nullif(trim(", accession, "), ''), ",
    "nullif(trim(CAST(raw_identifier AS VARCHAR)), '')) AS seed_id, ", species,
    " AS species, CAST(raw_identifier AS VARCHAR) AS raw_identifier, ",
    "nullif(trim(CAST(protein_sequence AS VARCHAR)), '') AS protein_sequence ",
    "FROM ", relation, "), seed_sequences AS (SELECT seed_id, ",
    "count(*) AS sequence_match_count, count(DISTINCT protein_sequence) FILTER ",
    "(WHERE protein_sequence IS NOT NULL) AS distinct_sequence_count, coalesce(",
    "string_agg(DISTINCT species, ';' ORDER BY species) FILTER (WHERE ",
    "nullif(trim(species), '') IS NOT NULL), '') AS sequence_species, coalesce(",
    "string_agg(DISTINCT raw_identifier, ';' ORDER BY raw_identifier) FILTER ",
    "(WHERE nullif(trim(raw_identifier), '') IS NOT NULL), '') AS ",
    "sequence_identifiers, min(protein_sequence) FILTER (WHERE protein_sequence ",
    "IS NOT NULL) AS protein_sequence FROM sequence_rows WHERE seed_id IS NOT ",
    "NULL GROUP BY seed_id)"
  )
}

seed_catalogue_json_text <- function(keys, available) {
  if (!"seed_metadata_json" %in% available) return("CAST('' AS VARCHAR)")
  candidates <- vapply(keys, function(key) {
    paste0(
      "nullif(trim(json_extract_string(TRY_CAST(seed_metadata_json AS JSON), '$.",
      key,
      "')), '')"
    )
  }, character(1L))
  paste0("coalesce(", paste(candidates, collapse = ", "), ", '')")
}

seed_catalogue_authority_source <- function(column, available) {
  if (!column %in% available) return("CAST('' AS VARCHAR)")
  paste0(
    "coalesce(CAST(", quote_duckdb_identifier(column), " AS VARCHAR), '')"
  )
}

seed_catalogue_cluster_summary_cte <- function(
  capability,
  alias = "e3_resource"
) {
  relation <- capability$summary_relation
  seed_column <- capability$summary_seed_column
  cluster_column <- capability$summary_cluster_column
  if (is.null(relation) || is.null(seed_column) || is.null(cluster_column)) {
    return(paste0(
      "cluster_summary AS (SELECT CAST(NULL AS VARCHAR) AS seed_id, ",
      "CAST(NULL AS BIGINT) AS source_cluster_count, CAST(NULL AS VARCHAR) AS ",
      "source_cluster_ids WHERE FALSE)"
    ))
  }
  source <- qualified_resource_relation(relation = relation, alias = alias)
  paste0(
    "cluster_links AS (SELECT DISTINCT trim(seed_id) AS seed_id, CAST(",
    quote_duckdb_identifier(cluster_column), " AS VARCHAR) AS source_cluster_id ",
    "FROM ", source, ", UNNEST(string_split(coalesce(CAST(",
    quote_duckdb_identifier(seed_column), " AS VARCHAR), ''), ';')) AS ",
    "seeds(seed_id) WHERE trim(seed_id) != ''), cluster_summary AS (SELECT ",
    "seed_id, count(DISTINCT nullif(trim(source_cluster_id), '')) AS ",
    "source_cluster_count, coalesce(string_agg(DISTINCT source_cluster_id, ';' ",
    "ORDER BY source_cluster_id) FILTER (WHERE nullif(trim(source_cluster_id), ",
    "'') IS NOT NULL), '') AS source_cluster_ids FROM cluster_links GROUP BY ",
    "seed_id)"
  )
}

build_seed_catalogue_authority_query <- function(
  capability,
  max_rows,
  alias = "e3_resource"
) {
  metadata <- list(
    seed_protein_names = c("protein_names", "protein_name", "name"),
    seed_category = c("category", "e3_category"),
    seed_review_status = c("reviewed", "review_status"),
    seed_ubiquitin_go_status = "ubiquitin_go_term",
    seed_exclusion_go_term = "exclusion_go_term",
    seed_organism = "organism",
    seed_taxon_id = c("organism_id", "taxon_id"),
    seed_sequence_md5 = "sequence_md5",
    seed_evidence_type = "evidence_type",
    seed_source = "source"
  )
  annotations <- vapply(names(metadata), function(output) {
    paste0(
      seed_catalogue_json_text(
        keys = metadata[[output]],
        available = capability$columns
      ),
      " AS ", quote_duckdb_identifier(output)
    )
  }, character(1L))
  provenance_columns <- c(
    "source_value", "source_column", "source_row", "source_path",
    "seed_metadata_json"
  )
  provenance <- vapply(provenance_columns, function(column) {
    paste0(
      seed_catalogue_authority_source(
        column = column,
        available = capability$columns
      ),
      " AS ", quote_duckdb_identifier(column)
    )
  }, character(1L))
  exact_projection <- paste0(
    "authority.",
    vapply(
      seed_catalogue_exact_annotation_fields(),
      quote_duckdb_identifier,
      character(1L)
    ),
    collapse = ", "
  )
  associated_blanks <- vapply(
    names(seed_catalogue_annotation_fields()),
    function(column) paste0(
      "CAST('' AS VARCHAR) AS ", quote_duckdb_identifier(column)
    ),
    character(1L)
  )
  authority <- qualified_resource_relation(
    relation = seed_catalogue_authority_relation(),
    alias = alias
  )
  clusters <- seed_catalogue_cluster_summary_cte(
    capability = capability,
    alias = alias
  )
  sequences <- seed_catalogue_sequence_cte(capability = capability, alias = alias)
  paste0(
    "WITH authority_rows AS (SELECT trim(CAST(seed_id AS VARCHAR)) AS seed_id, ",
    paste(annotations, collapse = ", "), ", ", paste(provenance, collapse = ", "),
    ", ROW_NUMBER() OVER (PARTITION BY trim(CAST(seed_id AS VARCHAR)) ORDER BY ",
    "trim(CAST(seed_id AS VARCHAR))) AS seed_row FROM ", authority,
    " WHERE nullif(trim(CAST(seed_id AS VARCHAR)), '') IS NOT NULL), authority ",
    "AS (SELECT * EXCLUDE (seed_row) FROM authority_rows WHERE seed_row = 1), ",
    clusters, ", ", sequences, " SELECT authority.seed_id, ", exact_projection,
    ", ", paste(associated_blanks, collapse = ", "), ", coalesce(clusters.",
    "source_cluster_count, 0) AS source_cluster_count, coalesce(clusters.",
    "source_cluster_ids, '') AS source_cluster_ids, coalesce(sequences.",
    "distinct_sequence_count, 0) > 0 AS sequence_available, coalesce(sequences.",
    "sequence_match_count, 0) AS sequence_match_count, coalesce(sequences.",
    "distinct_sequence_count, 0) AS distinct_sequence_count, coalesce(sequences.",
    "sequence_species, '') AS sequence_species, coalesce(sequences.",
    "sequence_identifiers, '') AS sequence_identifiers, coalesce(sequences.",
    "protein_sequence, '') AS protein_sequence, length(coalesce(sequences.",
    "protein_sequence, '')) AS protein_sequence_length, authority.source_value, ",
    "authority.source_column, authority.source_row, authority.source_path, ",
    "authority.seed_metadata_json, 'exact seed authority row' AS annotation_scope, ",
    "'known_e3_seeds' AS catalogue_source FROM authority LEFT JOIN ",
    "cluster_summary clusters USING (seed_id) LEFT JOIN seed_sequences sequences ",
    "USING (seed_id) ORDER BY lower(authority.seed_id), authority.seed_id LIMIT ",
    max_rows
  )
}

#' Build a bounded E3 seed catalogue query.
#'
#' @param capability Seed-catalogue capability metadata.
#' @param max_rows Hard row limit.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_seed_catalogue_query <- function(
  capability,
  max_rows = 10000L,
  alias = "e3_resource"
) {
  if (!isTRUE(capability$available)) {
    stop("No E3 seed evidence relation is available.", call. = FALSE)
  }
  limit <- suppressWarnings(as.integer(max_rows))
  if (length(limit) != 1L || is.na(limit) || limit < 1L || limit > 100000L) {
    stop("Maximum seed rows must be between 1 and 100000.", call. = FALSE)
  }
  if (identical(capability$mode, "authority")) {
    return(build_seed_catalogue_authority_query(
      capability = capability,
      max_rows = limit,
      alias = alias
    ))
  }
  source <- qualified_resource_relation(
    relation = capability$relation,
    alias = alias
  )
  seed_column <- quote_duckdb_identifier(capability$seed_id_column)
  cluster <- if (is.null(capability$cluster_column)) {
    "CAST('' AS VARCHAR)"
  } else {
    paste0(
      "CAST(", quote_duckdb_identifier(capability$cluster_column), " AS VARCHAR)"
    )
  }
  annotations <- vapply(
    names(seed_catalogue_annotation_fields()),
    function(output) {
      seed_catalogue_aggregate(
        available = capability$columns,
        choices = seed_catalogue_annotation_fields()[[output]],
        alias = output
      )
    },
    character(1L)
  )
  sequences <- seed_catalogue_sequence_cte(capability = capability, alias = alias)
  exact_blanks <- vapply(
    seed_catalogue_exact_annotation_fields(),
    function(column) paste0(
      "CAST('' AS VARCHAR) AS ", quote_duckdb_identifier(column)
    ),
    character(1L)
  )
  paste0(
    "WITH exploded AS (SELECT DISTINCT trim(seed_id) AS seed_id, ", cluster,
    " AS source_cluster_id, * EXCLUDE (", seed_column, ") FROM ", source,
    ", UNNEST(string_split(coalesce(CAST(", seed_column,
    " AS VARCHAR), ''), ';')) AS seeds(seed_id) WHERE trim(seed_id) != ''), ",
    "seed_annotations AS (SELECT seed_id, count(DISTINCT nullif(trim(",
    "source_cluster_id), '')) AS source_cluster_count, coalesce(string_agg(",
    "DISTINCT source_cluster_id, ';' ORDER BY source_cluster_id) FILTER (WHERE ",
    "nullif(trim(source_cluster_id), '') IS NOT NULL), '') AS source_cluster_ids, ",
    paste(annotations, collapse = ", "), " FROM exploded GROUP BY seed_id), ",
    sequences, " SELECT annotations.seed_id, ",
    paste(exact_blanks, collapse = ", "), ", ",
    "annotations.associated_seed_protein_names, annotations.associated_seed_categories, ",
    "annotations.associated_seed_review_statuses, ",
    "annotations.associated_seed_ubiquitin_go_statuses, ",
    "annotations.associated_seed_organisms, annotations.source_cluster_count, ",
    "annotations.source_cluster_ids, coalesce(sequences.distinct_sequence_count, ",
    "0) > 0 AS sequence_available, coalesce(sequences.sequence_match_count, 0) ",
    "AS sequence_match_count, coalesce(sequences.distinct_sequence_count, 0) AS ",
    "distinct_sequence_count, coalesce(sequences.sequence_species, '') AS ",
    "sequence_species, coalesce(sequences.sequence_identifiers, '') AS ",
    "sequence_identifiers, coalesce(sequences.protein_sequence, '') AS ",
    "protein_sequence, length(coalesce(sequences.protein_sequence, '')) AS ",
    "protein_sequence_length, CAST('' AS VARCHAR) AS source_value, ",
    "CAST('' AS VARCHAR) AS source_column, CAST('' AS VARCHAR) AS source_row, ",
    "CAST('' AS VARCHAR) AS source_path, CAST('' AS VARCHAR) AS ",
    "seed_metadata_json, 'cluster-associated annotation; exact per-seed ",
    "linkage retained only where published by the source' AS annotation_scope, '",
    escape_sql_literal(capability$relation), "' AS catalogue_source FROM ",
    "seed_annotations annotations LEFT JOIN seed_sequences sequences USING ",
    "(seed_id) ORDER BY lower(annotations.seed_id), annotations.seed_id LIMIT ",
    limit
  )
}

#' Filter a seed catalogue using pasted literal terms.
#'
#' @param data Seed catalogue.
#' @param query One or several terms separated by common delimiters.
#' @return Filtered catalogue.
filter_seed_catalogue <- function(data, query = "") {
  terms <- unlist(strsplit(as.character(query %||% ""), "[\\n\\r\\t,;]+"))
  terms <- unique(tolower(trimws(terms[nzchar(trimws(terms))])))
  if (length(terms) == 0L || nrow(data) == 0L) return(data)
  columns <- setdiff(names(data), "protein_sequence")
  combined <- apply(data[, columns, drop = FALSE], 1L, function(row) {
    paste(ifelse(is.na(row), "", as.character(row)), collapse = " ")
  })
  keep <- vapply(combined, function(value) {
    any(vapply(terms, grepl, logical(1L), x = tolower(value), fixed = TRUE))
  }, logical(1L))
  data[keep, , drop = FALSE]
}
