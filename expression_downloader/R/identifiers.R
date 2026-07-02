#' Split a gene-names field into individual aliases.
#'
#' @param gene_names Character vector of gene-name fields.
#' @return A list of character vectors.
split_gene_names <- function(gene_names) {
  split_values <- stringr::str_split(
    string = gene_names,
    pattern = "[;|,[:space:]]+"
  )

  cleaned_values <- purrr::map(
    .x = split_values,
    .f = function(values) {
      values <- values[!is.na(values)]
      values <- values[values != ""]
      unique(values)
    }
  )

  return(cleaned_values)
}


#' Build identifier aliases from an E3 ligase table.
#'
#' Captures common identifier formats such as entry, accession, entry name and
#' gene-name tokens. The input table may come from TSV, SQLite extraction or a
#' duckplyr query collected into R.
#'
#' @param e3_tbl E3 ligase table containing available identifier columns.
#' @return Identifier alias tibble.
build_e3_identifier_aliases <- function(e3_tbl) {
  required_columns <- c("entry", "accession", "entry_name", "gene_names", "organism")
  missing_columns <- setdiff(x = required_columns, y = names(e3_tbl))

  if (length(missing_columns) > 0L) {
    stop(
      stringr::str_c(
        "E3 table is missing required columns: ",
        stringr::str_c(missing_columns, collapse = ", ")
      ),
      call. = FALSE
    )
  }

  base_tbl <- e3_tbl |>
    dplyr::mutate(
      species_column = species_name_to_column(species_name = .data$organism)
    )

  direct_alias_tbl <- dplyr::bind_rows(
    base_tbl |>
      dplyr::transmute(
        source_table = "e3_ligases",
        source_record_id = .data$entry,
        species_column = .data$species_column,
        identifier_type = "e3_entry",
        identifier_value = .data$entry,
        preferred = TRUE
      ),
    base_tbl |>
      dplyr::transmute(
        source_table = "e3_ligases",
        source_record_id = .data$entry,
        species_column = .data$species_column,
        identifier_type = "protein_accession",
        identifier_value = .data$accession,
        preferred = TRUE
      ),
    base_tbl |>
      dplyr::transmute(
        source_table = "e3_ligases",
        source_record_id = .data$entry,
        species_column = .data$species_column,
        identifier_type = "entry_name",
        identifier_value = .data$entry_name,
        preferred = FALSE
      )
  ) |>
    dplyr::filter(!is.na(.data$identifier_value)) |>
    dplyr::filter(.data$identifier_value != "")

  gene_alias_tbl <- base_tbl |>
    dplyr::select(
      .data$entry,
      .data$gene_names,
      .data$species_column
    ) |>
    dplyr::filter(!is.na(.data$gene_names)) |>
    dplyr::mutate(gene_name_token = split_gene_names(gene_names = .data$gene_names)) |>
    tidyr::unnest(cols = "gene_name_token") |>
    dplyr::filter(.data$gene_name_token != "") |>
    dplyr::transmute(
      source_table = "e3_ligases",
      source_record_id = .data$entry,
      species_column = .data$species_column,
      identifier_type = "gene_name",
      identifier_value = .data$gene_name_token,
      preferred = FALSE
    )

  alias_tbl <- dplyr::bind_rows(direct_alias_tbl, gene_alias_tbl) |>
    dplyr::distinct()

  return(alias_tbl)
}


#' Read an E3 ligase TSV and build identifier aliases.
#'
#' @param e3_tsv Path to an E3 ligase TSV.
#' @return Identifier alias tibble.
read_e3_aliases_from_tsv <- function(e3_tsv) {
  e3_tbl <- readr::read_tsv(file = e3_tsv, show_col_types = FALSE)
  alias_tbl <- build_e3_identifier_aliases(e3_tbl = e3_tbl)

  return(alias_tbl)
}


#' Extract E3 aliases from an inherited SQLite database using DuckDB SQL.
#'
#' This uses DuckDB's SQLite scanner via `duckplyr::db_exec()` and
#' `duckplyr::read_sql_duckdb()`. If the SQLite extension is not already
#' available, `install_extension = TRUE` may attempt to install it.
#'
#' @param sqlite_path Path to the inherited SQLite database.
#' @param table_name Name of the E3 table in the SQLite database.
#' @param install_extension Logical value controlling whether to install the
#'   DuckDB SQLite extension.
#' @return Identifier alias tibble.
extract_e3_aliases_from_sqlite_duckdb <- function(
  sqlite_path,
  table_name = "e3_ligases",
  install_extension = FALSE
) {
  if (install_extension) {
    duckplyr::db_exec(sql = "INSTALL sqlite")
  }

  duckplyr::db_exec(sql = "LOAD sqlite")

  sqlite_sql_path <- normalise_sql_path(file_path = sqlite_path, must_work = TRUE)
  safe_table_name <- escape_sql_literal(value = table_name)

  e3_query <- stringr::str_c(
    "SELECT entry, accession, entry_name, gene_names, organism ",
    "FROM sqlite_scan('",
    sqlite_sql_path,
    "', '",
    safe_table_name,
    "')"
  )

  e3_tbl <- duckplyr::read_sql_duckdb(sql = e3_query) |>
    dplyr::collect()

  alias_tbl <- build_e3_identifier_aliases(e3_tbl = e3_tbl)

  return(alias_tbl)
}


#' Write identifier aliases to TSV and optionally Parquet.
#'
#' @param alias_tbl Identifier alias tibble.
#' @param output_tsv Output TSV path.
#' @param output_parquet Optional output Parquet path.
#' @param force Logical value controlling whether to overwrite usable Parquet.
#' @return Invisibly returns a list of output paths.
write_identifier_aliases <- function(
  alias_tbl,
  output_tsv,
  output_parquet = NULL,
  force = FALSE
) {
  ensure_directory(directory_path = dirname(output_tsv))

  readr::write_tsv(
    x = alias_tbl,
    file = output_tsv
  )

  if (!is.null(output_parquet)) {
    copy_tsv_to_parquet_duckdb(
      input_tsv = output_tsv,
      output_parquet = output_parquet,
      force = force
    )
  }

  return(
    invisible(
      list(
        output_tsv = output_tsv,
        output_parquet = output_parquet
      )
    )
  )
}
