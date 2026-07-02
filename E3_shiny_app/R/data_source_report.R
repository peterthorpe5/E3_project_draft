#' Data-source reporting helpers for the source-first E3 PROTAC resource.
#'
#' These functions write a human-readable Markdown file documenting which source
#' files were used to generate the Parquet/DuckDB layer. The report is separate
#' from the Shiny app UI so it can be regenerated on the cluster or Mac whenever
#' source files are added.

#' Read a TSV file if it exists.
#'
#' @param path TSV path.
#' @return Tibble. Missing files return an empty tibble with a `message` column.
read_optional_tsv <- function(path) {
  if (is.null(path) || !file.exists(path)) {
    return(tibble::tibble(message = paste("Missing:", path)))
  }

  utils::read.delim(
    file = path,
    sep = "\t",
    header = TRUE,
    quote = "",
    comment.char = "",
    stringsAsFactors = FALSE,
    check.names = FALSE
  ) |>
    tibble::as_tibble()
}

#' Infer a derived directory from a resource DuckDB path.
#'
#' @param resource_duckdb_path Path such as derived/duckdb/e3_protac_resource.duckdb.
#' @return Derived directory path.
infer_derived_dir <- function(resource_duckdb_path) {
  if (is.null(resource_duckdb_path) || !nzchar(resource_duckdb_path)) {
    return("")
  }

  path <- normalizePath(resource_duckdb_path, mustWork = FALSE)
  parent <- dirname(path)

  if (basename(parent) == "duckdb") {
    return(dirname(parent))
  }

  dirname(path)
}

#' Build expected QC catalog paths.
#'
#' @param derived_dir Derived output directory from the source-to-Parquet pipeline.
#' @return Named list of paths.
resource_catalog_paths <- function(derived_dir) {
  qc_dir <- file.path(derived_dir, "qc")

  list(
    source_manifest = file.path(qc_dir, "source_file_manifest.tsv"),
    tabular_catalog = file.path(qc_dir, "tabular_table_catalog.tsv"),
    fasta_catalog = file.path(qc_dir, "fasta_table_catalog.tsv"),
    text_catalog = file.path(qc_dir, "text_file_catalog.tsv"),
    inherited_parquet_catalog = file.path(qc_dir, "copied_existing_parquet_catalog.tsv"),
    duckdb_view_catalog = file.path(qc_dir, "duckdb_view_catalog.tsv")
  )
}

#' Summarise a source-file manifest by high-level folder.
#'
#' @param manifest Source-file manifest tibble.
#' @return Summary tibble.
summarise_manifest_by_folder <- function(manifest) {
  if (is.null(manifest) || nrow(manifest) == 0L || !"relative_path" %in% names(manifest)) {
    return(tibble::tibble(top_level_folder = character(), files = integer()))
  }

  manifest |>
    dplyr::mutate(
      top_level_folder = sub("/.*$", "", .data$relative_path),
      top_level_folder = dplyr::if_else(
        is.na(.data$top_level_folder) | .data$top_level_folder == "",
        "unknown",
        .data$top_level_folder
      )
    ) |>
    dplyr::count(.data$top_level_folder, name = "files") |>
    dplyr::arrange(dplyr::desc(.data$files), .data$top_level_folder)
}

#' Write a Markdown table from a data frame.
#'
#' @param dataframe Data frame.
#' @param max_rows Maximum rows to include.
#' @return Character vector of Markdown lines.
dataframe_to_markdown_table <- function(dataframe, max_rows = 50L) {
  if (is.null(dataframe) || nrow(dataframe) == 0L) {
    return("_No rows available._")
  }

  dataframe <- utils::head(as.data.frame(dataframe), max_rows)
  dataframe[] <- lapply(dataframe, function(column) {
    column <- as.character(column)
    column[is.na(column)] <- ""
    gsub("\\|", "\\\\|", column)
  })

  header <- paste0("| ", paste(names(dataframe), collapse = " | "), " |")
  rule <- paste0("| ", paste(rep("---", length(dataframe)), collapse = " | "), " |")
  rows <- apply(dataframe, 1L, function(row) paste0("| ", paste(row, collapse = " | "), " |"))

  c(header, rule, rows)
}

#' Write a data-source Markdown report.
#'
#' @param derived_dir Derived output directory.
#' @param output_path Output Markdown path.
#' @param max_rows Maximum source rows to include in long tables.
#' @return Output path invisibly.
write_data_sources_report <- function(
  derived_dir,
  output_path = file.path(derived_dir, "docs", "FILES_USED.md"),
  max_rows = 200L
) {
  paths <- resource_catalog_paths(derived_dir)
  output_dir <- dirname(output_path)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  manifest <- read_optional_tsv(paths$source_manifest)
  tabular <- read_optional_tsv(paths$tabular_catalog)
  fasta <- read_optional_tsv(paths$fasta_catalog)
  text <- read_optional_tsv(paths$text_catalog)
  inherited_parquet <- read_optional_tsv(paths$inherited_parquet_catalog)
  duckdb_views <- read_optional_tsv(paths$duckdb_view_catalog)
  manifest_summary <- summarise_manifest_by_folder(manifest)

  lines <- c(
    "# E3 PROTAC source files used in the current resource build",
    "",
    paste0("Generated: ", format(Sys.time(), "%Y-%m-%d %H:%M:%S %Z")),
    "",
    "This document records the files used to build the source-first Parquet/DuckDB layer for the E3 PROTAC resource. It is intentionally provenance-heavy. The current stage is an audit/rebuild layer, not yet the final biological schema.",
    "",
    "## Derived directory",
    "",
    paste0("`", normalizePath(derived_dir, mustWork = FALSE), "`"),
    "",
    "## Source-file summary by top-level copied folder",
    "",
    dataframe_to_markdown_table(manifest_summary, max_rows = max_rows),
    "",
    "## Tabular files converted to source-preserving Parquet",
    "",
    dataframe_to_markdown_table(tabular, max_rows = max_rows),
    "",
    "## FASTA files converted or deliberately skipped",
    "",
    dataframe_to_markdown_table(fasta, max_rows = max_rows),
    "",
    "## Text files preserved as line-level Parquet",
    "",
    dataframe_to_markdown_table(text, max_rows = max_rows),
    "",
    "## Inherited Parquet files copied into the resource layer",
    "",
    dataframe_to_markdown_table(inherited_parquet, max_rows = max_rows),
    "",
    "## DuckDB views created over Parquet files",
    "",
    dataframe_to_markdown_table(duckdb_views, max_rows = max_rows),
    "",
    "## Full source manifest preview",
    "",
    dataframe_to_markdown_table(manifest, max_rows = max_rows),
    "",
    "## Notes",
    "",
    "- Original inherited relative paths are retained in source/provenance columns.",
    "- macOS AppleDouble sidecar files such as `._file.parquet` should not be used as biological data.",
    "- Orthofinder/HOG outputs are deliberately deferred to a separate import step because those folders are large and need a focused schema.",
    "- The inherited SQLite database should be used as a regression/reference target, not as the only source of truth."
  )

  writeLines(unlist(lines), con = output_path)
  invisible(output_path)
}
