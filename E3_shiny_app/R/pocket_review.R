#' Offline pocket-review bundle discovery and validation helpers.

#' Return the required files for a portable pocket-review bundle.
#'
#' @param review_dir Candidate pocket-review directory.
#' @return Named character vector of required paths.
pocket_review_required_paths <- function(review_dir) {
  root <- normalizePath(review_dir, mustWork = FALSE)
  c(
    index = file.path(root, "index.html"),
    evidence_matrix = file.path(root, "evidence_matrix.html"),
    report_index = file.path(root, "tables", "review_report_index.tsv"),
    sequences = file.path(root, "tables", "prioritised_group_sequences.tsv"),
    model_inventory = file.path(root, "tables", "protein_model_inventory.tsv"),
    groups = file.path(root, "groups"),
    manifest = file.path(root, "provenance", "run_manifest.json")
  )
}

#' Test whether a portable pocket-review bundle is complete enough to serve.
#'
#' @param review_dir Candidate pocket-review directory.
#' @return TRUE when all required files and directories are present.
pocket_review_available <- function(review_dir) {
  if (is.null(review_dir) || length(review_dir) != 1L) {
    return(FALSE)
  }
  review_dir <- trimws(as.character(review_dir))
  if (!nzchar(review_dir) || !dir.exists(review_dir)) {
    return(FALSE)
  }
  paths <- pocket_review_required_paths(review_dir = review_dir)
  file_keys <- setdiff(names(paths), "groups")
  all(file.exists(paths[file_keys])) && dir.exists(paths[["groups"]])
}

#' Resolve an explicit or uniquely discoverable pocket-review bundle.
#'
#' An explicit path always takes precedence. If it is empty, the function looks
#' for exactly one valid direct child beginning with `pocket_review` beside the
#' selected resource. Multiple bundles are not guessed between.
#'
#' @param explicit_dir Explicit command-line or environment path.
#' @param resource_source Resolved E3 result-source specification.
#' @return Normalised directory path, or an empty string when unavailable or
#'   ambiguous.
resolve_pocket_review_dir <- function(explicit_dir = "", resource_source = NULL) {
  explicit_dir <- as.character(explicit_dir %||% "")
  if (length(explicit_dir) != 1L) {
    stop("Pocket-review directory must be one path.", call. = FALSE)
  }
  explicit_dir <- trimws(explicit_dir)
  if (nzchar(explicit_dir)) {
    return(normalizePath(explicit_dir, mustWork = FALSE))
  }
  if (is.null(resource_source)) {
    return("")
  }
  source <- coerce_resource_source(resource_source = resource_source)
  if (source$mode == "unconfigured" || !nzchar(source$path)) {
    return("")
  }
  search_root <- if (source$mode == "run_directory") {
    source$path
  } else {
    dirname(source$path)
  }
  if (!dir.exists(search_root)) {
    return("")
  }
  children <- list.dirs(search_root, recursive = FALSE, full.names = TRUE)
  candidates <- children[grepl(
    "^pocket_review",
    basename(children),
    ignore.case = TRUE
  )]
  candidates <- candidates[vapply(
    candidates,
    pocket_review_available,
    logical(1L)
  )]
  if (length(candidates) != 1L) {
    return("")
  }
  normalizePath(candidates[[1L]], mustWork = TRUE)
}

#' Read one trusted tab-separated pocket-review table.
#'
#' @param path Existing TSV path.
#' @param required_columns Required column names.
#' @return Data frame preserving source column names.
read_pocket_review_tsv <- function(path, required_columns) {
  if (!file.exists(path) || dir.exists(path)) {
    stop(paste0("Pocket-review table was not found: ", path), call. = FALSE)
  }
  table <- utils::read.delim(
    file = path,
    header = TRUE,
    sep = "\t",
    quote = "",
    comment.char = "",
    stringsAsFactors = FALSE,
    check.names = FALSE,
    na.strings = c("", "NA")
  )
  missing_columns <- setdiff(required_columns, names(table))
  if (length(missing_columns) > 0L) {
    stop(
      paste0(
        "Pocket-review table is missing required columns: ",
        paste(missing_columns, collapse = ", ")
      ),
      call. = FALSE
    )
  }
  table
}

#' Test whether a child path remains inside a trusted directory.
#'
#' @param child Existing child file.
#' @param parent Existing parent directory.
#' @return TRUE when the normalised child is below the parent.
path_is_within <- function(child, parent) {
  child_path <- normalizePath(child, mustWork = TRUE)
  parent_path <- normalizePath(parent, mustWork = TRUE)
  identical(child_path, parent_path) || startsWith(
    child_path,
    paste0(parent_path, .Platform$file.sep)
  )
}

#' Load and validate the ranked pocket-review index.
#'
#' @param review_dir Valid pocket-review directory.
#' @return Rank-ordered report-index data frame.
load_pocket_review_index <- function(review_dir) {
  path <- file.path(review_dir, "tables", "review_report_index.tsv")
  required <- c(
    "review_rank",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "reference_accession",
    "protein_count",
    "alignment_sequence_count",
    "group_review_html"
  )
  index <- read_pocket_review_tsv(path = path, required_columns = required)
  index$review_rank <- suppressWarnings(as.integer(index$review_rank))
  if (
    nrow(index) == 0L ||
      anyNA(index$review_rank) ||
      anyDuplicated(index$review_rank) > 0L ||
      anyDuplicated(index$group_review_html) > 0L
  ) {
    stop(
      "Pocket-review index must contain unique integer ranks and group pages.",
      call. = FALSE
    )
  }
  for (relative_path in index$group_review_html) {
    path_components <- strsplit(relative_path, "/", fixed = TRUE)[[1L]]
    if (
      is.na(relative_path) ||
        !nzchar(relative_path) ||
        startsWith(relative_path, "/") ||
        startsWith(relative_path, "\\") ||
        grepl("^[A-Za-z][A-Za-z0-9+.-]*:", relative_path) ||
        ".." %in% path_components
    ) {
      stop("Pocket-review index contains an unsafe group page.", call. = FALSE)
    }
    page <- file.path(review_dir, relative_path)
    if (!file.exists(page) || !path_is_within(page, review_dir)) {
      stop(
        paste0("Pocket-review group page was not found: ", relative_path),
        call. = FALSE
      )
    }
  }
  index[order(index$review_rank), , drop = FALSE]
}

#' Load the portable member-sequence and model inventories.
#'
#' @param review_dir Valid pocket-review directory.
#' @return Named list containing sequence and model data frames.
load_pocket_review_members <- function(review_dir) {
  sequences <- read_pocket_review_tsv(
    path = file.path(
      review_dir,
      "tables",
      "prioritised_group_sequences.tsv"
    ),
    required_columns = c(
      "review_rank",
      "primary_group_type",
      "primary_group_id",
      "lead_cluster_id",
      "fasta_identifier",
      "candidate_accession",
      "species_column",
      "is_reference",
      "has_ranked_pocket_evidence",
      "sequence_length",
      "alignment_length"
    )
  )
  models <- read_pocket_review_tsv(
    path = file.path(review_dir, "tables", "protein_model_inventory.tsv"),
    required_columns = c(
      "review_rank",
      "primary_group_type",
      "primary_group_id",
      "lead_cluster_id",
      "candidate_accession",
      "species_column",
      "is_reference",
      "model_status",
      "ca_atom_count",
      "mapped_pocket_ca_count",
      "retained_pocket_count"
    )
  )
  sequences$review_rank <- suppressWarnings(as.integer(sequences$review_rank))
  models$review_rank <- suppressWarnings(as.integer(models$review_rank))
  list(sequences = sequences, models = models)
}

#' Build the validated configuration used by both review tabs.
#'
#' @param explicit_dir Optional explicit pocket-review directory.
#' @param resource_source Resolved E3 result source.
#' @param resource_prefix Shiny static-resource prefix.
#' @return Pocket-review configuration list.
prepare_pocket_review <- function(
  explicit_dir = "",
  resource_source = NULL,
  resource_prefix = "e3-pocket-review"
) {
  review_dir <- resolve_pocket_review_dir(
    explicit_dir = explicit_dir,
    resource_source = resource_source
  )
  if (!pocket_review_available(review_dir)) {
    reason <- if (nzchar(review_dir)) {
      paste0("The configured pocket-review bundle is incomplete: ", review_dir)
    } else {
      paste(
        "No unique pocket-review bundle was found.",
        "Start the app with --pocket_review_dir /path/to/pocket_review_bundle."
      )
    }
    return(list(
      available = FALSE,
      path = review_dir,
      resource_prefix = resource_prefix,
      reason = reason,
      index = data.frame(),
      sequences = data.frame(),
      models = data.frame()
    ))
  }
  index <- load_pocket_review_index(review_dir = review_dir)
  members <- load_pocket_review_members(review_dir = review_dir)
  list(
    available = TRUE,
    path = normalizePath(review_dir, mustWork = TRUE),
    resource_prefix = resource_prefix,
    reason = "",
    index = index,
    sequences = members$sequences,
    models = members$models
  )
}

#' Register the validated report directory as a read-only Shiny resource.
#'
#' @param review_config Prepared pocket-review configuration.
#' @return Configuration unchanged.
register_pocket_review_resource <- function(review_config) {
  if (!isTRUE(review_config$available)) {
    return(review_config)
  }
  prefix <- review_config$resource_prefix
  current <- shiny::resourcePaths()
  if (prefix %in% names(current)) {
    if (identical(
      normalizePath(current[[prefix]], mustWork = TRUE),
      review_config$path
    )) {
      return(review_config)
    }
    shiny::removeResourcePath(prefix = prefix)
  }
  shiny::addResourcePath(prefix = prefix, directoryPath = review_config$path)
  review_config
}

#' Build searchable labels for ranked review groups.
#'
#' @param index Validated review-index data frame.
#' @return Named character vector mapping page paths to labels.
pocket_review_group_choices <- function(index) {
  labels <- sprintf(
    "Rank %03d | %s | lead %s | reference %s",
    index$review_rank,
    index$primary_group_id,
    index$lead_cluster_id,
    index$reference_accession
  )
  stats::setNames(index$group_review_html, labels)
}

#' Convert a trusted report-relative path into a Shiny resource URL.
#'
#' @param resource_prefix Registered resource prefix.
#' @param relative_path Trusted report-relative path.
#' @return Browser-safe relative URL.
pocket_review_url <- function(resource_prefix, relative_path) {
  components <- strsplit(relative_path, "/", fixed = TRUE)[[1L]]
  encoded <- vapply(
    components,
    utils::URLencode,
    character(1L),
    reserved = TRUE
  )
  paste0(resource_prefix, "/", paste(encoded, collapse = "/"))
}
