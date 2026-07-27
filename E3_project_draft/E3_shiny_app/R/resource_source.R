#' Flexible read-only result-source handling.
#'
#' The reporter can consume a completed integrated DuckDB, one candidate-level
#' master Parquet, or all Parquet results below a current workflow run. Parquet
#' sources are exposed as views in a temporary in-memory DuckDB so duckplyr stays
#' lazy and the source files remain unchanged.

canonical_result_relations <- c(
  e3_candidate_master_results = "candidate_master_results",
  final_candidate_prioritisation = "final_candidate_prioritisation",
  computational_prestructure_ranking = "prestructure_ranking",
  e3_cluster_candidate_evidence = "candidate_evidence",
  candidate_membership_mapping = "candidate_orthology",
  candidate_cluster_orthology_summary = "candidate_orthology_summary",
  candidate_group_member_sequences = "candidate_group_member_sequences",
  orthogroup_membership = "orthogroup_membership",
  hierarchical_membership = "hierarchical_membership",
  domain_summary = "domain_summary",
  domain_hits = "domain_hits",
  candidate_identifier_aliases = "candidate_identifier_aliases",
  candidate_expression_mapping = "candidate_expression_mapping",
  candidate_expression_summary = "candidate_expression_summary",
  structural_analysis_accessions = "structural_analysis_accessions",
  selected_pockets = "selected_pockets",
  structural_prediction_status = "structural_prediction_status",
  pocket_conservation_summary = "pocket_conservation_summary",
  pocket_conservation_members = "pocket_conservation_members",
  pocket_sequence_coordinates = "pocket_sequence_coordinates",
  structural_alignments = "structural_alignments",
  pocket_comparisons = "structural_pocket_comparisons",
  pocket_residue_matches = "structural_pocket_residue_matches",
  structural_alignment_summary = "structural_alignment_summary"
)

#' Resolve exactly one E3 result source.
#'
#' @param resource_duckdb_path Optional integrated DuckDB path.
#' @param resource_parquet_path Optional candidate master Parquet path.
#' @param resource_run_dir Optional current workflow run directory.
#' @return Result-source specification.
resolve_resource_source <- function(
  resource_duckdb_path = "",
  resource_parquet_path = "",
  resource_run_dir = ""
) {
  values <- c(
    duckdb = resource_duckdb_path,
    master_parquet = resource_parquet_path,
    run_directory = resource_run_dir
  )
  active <- !is.na(values) & nzchar(trimws(values))
  if (sum(active) > 1L) {
    stop(
      paste(
        "Configure exactly one E3 result source:",
        "DuckDB, master Parquet, or workflow run directory."
      ),
      call. = FALSE
    )
  }
  if (!any(active)) {
    return(list(mode = "unconfigured", path = ""))
  }
  mode <- names(values)[active][[1L]]
  list(
    mode = mode,
    path = normalizePath(values[active][[1L]], mustWork = FALSE)
  )
}

#' Test whether a resolved result source is available.
#'
#' @param resource_source Result-source specification or legacy DuckDB path.
#' @return TRUE when the selected source exists and has the expected type.
resource_source_available <- function(resource_source) {
  source <- coerce_resource_source(resource_source)
  if (source$mode == "duckdb" || source$mode == "master_parquet") {
    return(file.exists(source$path) && !dir.exists(source$path))
  }
  if (source$mode == "run_directory") {
    return(dir.exists(source$path) && length(discover_result_parquets(source$path)) > 0L)
  }
  FALSE
}

#' Coerce a legacy DuckDB path into a result-source specification.
#'
#' @param resource_source Result-source list or character DuckDB path.
#' @return Result-source specification.
coerce_resource_source <- function(resource_source) {
  if (is.list(resource_source) && all(c("mode", "path") %in% names(resource_source))) {
    return(resource_source)
  }
  if (is.character(resource_source) && length(resource_source) == 1L) {
    return(resolve_resource_source(resource_duckdb_path = resource_source))
  }
  stop("Invalid E3 result-source specification.", call. = FALSE)
}

#' Create a safe relation name for an unknown Parquet result.
#'
#' @param parquet_path Parquet path.
#' @param run_dir Workflow run directory.
#' @return DuckDB-safe relation name.
safe_parquet_relation_name <- function(parquet_path, run_dir) {
  relative <- substring(
    normalizePath(parquet_path, mustWork = FALSE),
    nchar(normalizePath(run_dir, mustWork = FALSE)) + 2L
  )
  relative <- tools::file_path_sans_ext(relative)
  parts <- strsplit(relative, .Platform$file.sep, fixed = TRUE)[[1L]]
  parts <- tail(parts, 3L)
  name <- tolower(gsub("[^A-Za-z0-9_]", "_", paste(parts, collapse = "_")))
  name <- gsub("_+", "_", name)
  name <- gsub("^_+|_+$", "", name)
  if (!grepl("^[A-Za-z]", name)) {
    name <- paste0("result_", name)
  }
  name
}

#' Discover current, non-superseded Parquet results.
#'
#' @param run_dir Workflow run directory.
#' @return Named character vector mapping relation names to Parquet paths.
discover_result_parquets <- function(run_dir) {
  if (!dir.exists(run_dir)) {
    return(stats::setNames(character(), character()))
  }
  paths <- list.files(
    path = run_dir,
    pattern = "\\.parquet$",
    recursive = TRUE,
    full.names = TRUE
  )
  paths <- paths[!grepl(
    paste0("(^|", .Platform$file.sep, ")(superseded|\\.[^", .Platform$file.sep, "]+)"),
    paths
  )]
  relations <- character()
  selected_paths <- character()
  for (path in sort(paths)) {
    stem <- tools::file_path_sans_ext(basename(path))
    relation <- unname(canonical_result_relations[[stem]])
    if (is.null(relation) || is.na(relation) || !nzchar(relation)) {
      relation <- safe_parquet_relation_name(path, run_dir)
    }
    base <- relation
    suffix <- 2L
    while (relation %in% relations) {
      relation <- paste0(base, "_", suffix)
      suffix <- suffix + 1L
    }
    relations <- c(relations, relation)
    selected_paths <- c(selected_paths, normalizePath(path, mustWork = TRUE))
  }
  stats::setNames(selected_paths, relations)
}

#' Attach or register a result source in duckplyr's default DuckDB.
#'
#' @param resource_source Result-source specification or legacy DuckDB path.
#' @param alias Attached database alias.
#' @return Sanitised database alias.
initialise_resource_source <- function(resource_source, alias = "e3_resource") {
  source <- coerce_resource_source(resource_source)
  safe_alias <- sanitise_duckdb_alias(alias)
  try(
    duckplyr::db_exec(paste0("DETACH DATABASE IF EXISTS ", safe_alias)),
    silent = TRUE
  )
  if (source$mode == "duckdb") {
    if (!file.exists(source$path) || dir.exists(source$path)) {
      stop(
        paste0("E3 resource DuckDB database was not found: ", source$path),
        call. = FALSE
      )
    }
    safe_path <- escape_sql_literal(normalizePath(source$path, mustWork = TRUE))
    duckplyr::db_exec(paste0(
      "ATTACH DATABASE '", safe_path, "' AS ", safe_alias, " (READ_ONLY)"
    ))
    return(safe_alias)
  }
  if (source$mode == "master_parquet") {
    if (!file.exists(source$path) || dir.exists(source$path)) {
      stop(
        paste0("E3 candidate master Parquet was not found: ", source$path),
        call. = FALSE
      )
    }
    relations <- stats::setNames(
      normalizePath(source$path, mustWork = TRUE),
      "candidate_master_results"
    )
  } else if (source$mode == "run_directory") {
    relations <- discover_result_parquets(source$path)
    if (length(relations) == 0L) {
      stop(
        paste0("No current Parquet results were found below: ", source$path),
        call. = FALSE
      )
    }
  } else {
    stop(
      paste(
        "No E3 result source is configured. Set E3_RESOURCE_DUCKDB,",
        "E3_RESOURCE_PARQUET, or E3_RESOURCE_RUN_DIR."
      ),
      call. = FALSE
    )
  }
  duckplyr::db_exec(paste0("ATTACH ':memory:' AS ", safe_alias))
  for (relation in names(relations)) {
    safe_relation <- quote_duckdb_identifier(relation)
    safe_path <- escape_sql_literal(relations[[relation]])
    duckplyr::db_exec(paste0(
      "CREATE VIEW ", safe_alias, ".main.", safe_relation,
      " AS SELECT * FROM read_parquet('", safe_path, "')"
    ))
  }
  duckplyr::db_exec(paste0(
    "CREATE TABLE ", safe_alias, ".main.resource_relation_catalog (",
    "relation_name VARCHAR, app_section VARCHAR, row_granularity VARCHAR, ",
    "source_parquet VARCHAR)"
  ))
  for (relation in names(relations)) {
    safe_relation_value <- escape_sql_literal(relation)
    safe_path <- escape_sql_literal(relations[[relation]])
    duckplyr::db_exec(paste0(
      "INSERT INTO ", safe_alias, ".main.resource_relation_catalog VALUES ('",
      safe_relation_value, "', '", infer_result_section(relation),
      "', 'source_defined', '", safe_path, "')"
    ))
  }
  duckplyr::db_exec(paste0(
    "INSERT INTO ", safe_alias, ".main.resource_relation_catalog VALUES (",
    "'resource_relation_catalog', 'provenance', 'relation', ",
    "'generated_in_memory')"
  ))
  safe_alias
}
