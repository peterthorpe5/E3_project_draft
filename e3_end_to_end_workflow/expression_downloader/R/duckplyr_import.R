#' Detect likely gene identifier columns in an Atlas expression matrix.
#'
#' Expression Atlas files can differ slightly between experiments. This function
#' reads only the header and infers likely gene ID and gene name columns.
#'
#' @param expression_tsv Path to an Expression Atlas TSV file.
#' @return A list containing gene ID column, gene name column and expression columns.
detect_expression_columns <- function(expression_tsv) {
  if (!local_file_is_usable(file_path = expression_tsv)) {
    stop(
      stringr::str_c(
        "Expression TSV is missing or empty: ",
        expression_tsv
      ),
      call. = FALSE
    )
  }

  # Use base R for the header rather than readr/vroom. Some Expression
  # Atlas matrices have very wide headers, and vroom can fail before it has
  # read any data unless VROOM_CONNECTION_SIZE is increased. We only need
  # the first line here, so base readLines is more robust and avoids loading
  # the full matrix into memory.
  connection <- file(description = expression_tsv, open = "r")
  on.exit(expr = close(con = connection), add = TRUE)

  header_line <- readLines(
    con = connection,
    n = 1L,
    warn = FALSE
  )

  if (length(header_line) == 0L || is.na(header_line[[1L]])) {
    stop(
      stringr::str_c(
        "Expression TSV does not contain a readable header: ",
        expression_tsv
      ),
      call. = FALSE
    )
  }

  column_names <- strsplit(
    x = header_line[[1L]],
    split = "\t",
    fixed = TRUE
  )[[1L]]

  column_names <- stringr::str_replace_all(
    string = column_names,
    pattern = '^["\']|["\']$',
    replacement = ""
  )

  gene_id_candidates <- column_names[
    stringr::str_detect(
      string = stringr::str_to_lower(column_names),
      pattern = "gene.*id|ensembl|identifier|^id$"
    )
  ]

  gene_name_candidates <- column_names[
    stringr::str_detect(
      string = stringr::str_to_lower(column_names),
      pattern = "gene.*name|gene.*symbol|symbol|name"
    )
  ]

  gene_id_column <- dplyr::first(gene_id_candidates)

  if (is.na(gene_id_column)) {
    gene_id_column <- column_names[[1L]]
  }

  gene_name_column <- dplyr::first(gene_name_candidates)

  metadata_columns <- unique(
    x = stats::na.omit(object = c(gene_id_column, gene_name_column))
  )

  expression_columns <- setdiff(x = column_names, y = metadata_columns)

  return(
    list(
      gene_id_column = gene_id_column,
      gene_name_column = gene_name_column,
      expression_columns = expression_columns
    )
  )
}


#' Import one Atlas expression matrix into long Parquet using DuckDB SQL.
#'
#' Uses `duckplyr::db_exec()` to run DuckDB SQL over the TSV file. The full wide
#' expression matrix is not read into R memory. The output is a long Parquet file
#' containing one row per gene-by-sample-or-condition expression value.
#'
#' @param expression_tsv Path to the Expression Atlas expression TSV.
#' @param output_parquet Output Parquet file path.
#' @param experiment_accession Expression Atlas experiment accession.
#' @param species_column Internal species column name.
#' @param expression_unit Expression unit, usually TPM or FPKM.
#' @param force Logical value controlling whether to overwrite usable output.
#' @return A tibble describing the import status.
normalise_expression_to_parquet <- function(
  expression_tsv,
  output_parquet,
  experiment_accession,
  species_column,
  expression_unit,
  force = FALSE
) {
  if (!local_file_is_usable(file_path = expression_tsv)) {
    return(
      tibble::tibble(
        expression_tsv = expression_tsv,
        output_parquet = output_parquet,
        experiment_accession = experiment_accession,
        species_column = species_column,
        expression_unit = expression_unit,
        action = "skipped_missing_or_empty_input",
        success = FALSE
      )
    )
  }

  if (!force && local_file_is_usable(file_path = output_parquet)) {
    return(
      tibble::tibble(
        expression_tsv = expression_tsv,
        output_parquet = output_parquet,
        experiment_accession = experiment_accession,
        species_column = species_column,
        expression_unit = expression_unit,
        action = "skipped_existing_parquet",
        success = TRUE
      )
    )
  }

  ensure_directory(directory_path = dirname(output_parquet))

  column_info <- detect_expression_columns(expression_tsv = expression_tsv)

  if (length(column_info$expression_columns) == 0L) {
    return(
      tibble::tibble(
        expression_tsv = expression_tsv,
        output_parquet = output_parquet,
        experiment_accession = experiment_accession,
        species_column = species_column,
        expression_unit = expression_unit,
        action = "skipped_no_expression_columns",
        success = FALSE
      )
    )
  }

  expression_file_sql <- normalise_sql_path(
    file_path = expression_tsv,
    must_work = TRUE
  )
  output_file_sql <- normalise_sql_path(
    file_path = output_parquet,
    must_work = FALSE
  )

  gene_id_sql <- quote_duckdb_identifier(
    identifier = column_info$gene_id_column
  )

  if (!is.na(column_info$gene_name_column)) {
    gene_name_sql <- quote_duckdb_identifier(
      identifier = column_info$gene_name_column
    )
  } else {
    gene_name_sql <- "NULL"
  }

  excluded_columns <- stats::na.omit(
    object = c(column_info$gene_id_column, column_info$gene_name_column)
  )

  excluded_columns_sql <- stringr::str_c(
    purrr::map_chr(
      .x = excluded_columns,
      .f = quote_duckdb_identifier
    ),
    collapse = ", "
  )

  expression_columns_sql <- stringr::str_c(
    purrr::map_chr(
      .x = column_info$expression_columns,
      .f = quote_duckdb_identifier
    ),
    collapse = ", "
  )

  sql_statement <- stringr::str_c(
    "COPY (",
    " SELECT ",
    "'", escape_sql_literal(value = experiment_accession), "' AS experiment_accession, ",
    "'", escape_sql_literal(value = species_column), "' AS species_column, ",
    "CAST(gene_id AS TEXT) AS gene_id, ",
    "CAST(gene_name AS TEXT) AS gene_name, ",
    "CAST(sample_or_condition AS TEXT) AS sample_or_condition, ",
    "TRY_CAST(expression_value AS DOUBLE) AS expression_value, ",
    "'", escape_sql_literal(value = expression_unit), "' AS expression_unit, ",
    "'", escape_sql_literal(value = expression_tsv), "' AS source_file ",
    "FROM (",
    " SELECT ", gene_id_sql, " AS gene_id, ", gene_name_sql, " AS gene_name, * EXCLUDE (", excluded_columns_sql, ") ",
    " FROM read_csv('", expression_file_sql, "', delim = '\t', header = TRUE, ignore_errors = TRUE, union_by_name = TRUE)",
    ") ",
    "UNPIVOT (expression_value FOR sample_or_condition IN (", expression_columns_sql, ")) ",
    "WHERE TRY_CAST(expression_value AS DOUBLE) IS NOT NULL",
    ") TO '", output_file_sql, "' (FORMAT PARQUET)"
  )

  import_result <- tryCatch(
    expr = {
      duckplyr::db_exec(sql = sql_statement)
      TRUE
    },
    error = function(error) {
      warning(
        stringr::str_c(
          "DuckDB import failed for ",
          expression_tsv,
          ": ",
          conditionMessage(error)
        ),
        call. = FALSE
      )
      FALSE
    }
  )

  action <- dplyr::if_else(
    condition = import_result,
    true = "imported_to_parquet",
    false = "import_failed"
  )

  return(
    tibble::tibble(
      expression_tsv = expression_tsv,
      output_parquet = output_parquet,
      experiment_accession = experiment_accession,
      species_column = species_column,
      expression_unit = expression_unit,
      action = action,
      success = import_result
    )
  )
}


#' Convert downloaded Atlas TPM and FPKM files into long Parquet files.
#'
#' @param atlas_files_tbl Downloaded Atlas file manifest with local paths.
#' @param parquet_dir Directory for Parquet outputs.
#' @param force Logical value controlling whether to overwrite usable outputs.
#' @return Import summary tibble.
import_expression_files_to_parquet <- function(
  atlas_files_tbl,
  parquet_dir,
  force = FALSE
) {
  expression_files_tbl <- atlas_files_tbl |>
    dplyr::filter(.data$file_type %in% c("tpms", "fpkms")) |>
    dplyr::filter(
      purrr::map_lgl(
        .x = .data$local_path,
        .f = local_file_is_usable
      )
    ) |>
    dplyr::mutate(
      expression_unit = dplyr::case_when(
        .data$file_type == "tpms" ~ "TPM",
        .data$file_type == "fpkms" ~ "FPKM",
        TRUE ~ "unknown"
      ),
      output_parquet = file.path(
        parquet_dir,
        "atlas_expression_long",
        stringr::str_c("species_column=", .data$species_column),
        stringr::str_c("experiment_accession=", .data$experiment_accession),
        stringr::str_c(.data$file_type, ".parquet")
      )
    )

  if (nrow(expression_files_tbl) == 0L) {
    return(
      tibble::tibble(
        expression_tsv = character(),
        output_parquet = character(),
        experiment_accession = character(),
        species_column = character(),
        expression_unit = character(),
        action = character(),
        success = logical()
      )
    )
  }

  import_summary_tbl <- purrr::pmap_dfr(
    .l = list(
      expression_tsv = expression_files_tbl$local_path,
      output_parquet = expression_files_tbl$output_parquet,
      experiment_accession = expression_files_tbl$experiment_accession,
      species_column = expression_files_tbl$species_column,
      expression_unit = expression_files_tbl$expression_unit
    ),
    .f = function(
      expression_tsv,
      output_parquet,
      experiment_accession,
      species_column,
      expression_unit
    ) {
      normalise_expression_to_parquet(
        expression_tsv = expression_tsv,
        output_parquet = output_parquet,
        experiment_accession = experiment_accession,
        species_column = species_column,
        expression_unit = expression_unit,
        force = force
      )
    }
  )

  return(import_summary_tbl)
}


#' Convert a small TSV file to Parquet using DuckDB SQL.
#'
#' This helper is intended for manifests and metadata tables, not the large wide
#' expression matrices.
#'
#' @param input_tsv Input TSV file.
#' @param output_parquet Output Parquet file.
#' @param force Logical value controlling whether to overwrite usable output.
#' @return A tibble describing the conversion status.
copy_tsv_to_parquet_duckdb <- function(input_tsv, output_parquet, force = FALSE) {
  if (!local_file_is_usable(file_path = input_tsv)) {
    return(
      tibble::tibble(
        input_tsv = input_tsv,
        output_parquet = output_parquet,
        action = "skipped_missing_or_empty_input",
        success = FALSE
      )
    )
  }

  if (!force && local_file_is_usable(file_path = output_parquet)) {
    return(
      tibble::tibble(
        input_tsv = input_tsv,
        output_parquet = output_parquet,
        action = "skipped_existing_parquet",
        success = TRUE
      )
    )
  }

  ensure_directory(directory_path = dirname(output_parquet))

  input_sql <- normalise_sql_path(file_path = input_tsv, must_work = TRUE)
  output_sql <- normalise_sql_path(file_path = output_parquet, must_work = FALSE)

  sql_statement <- stringr::str_c(
    "COPY (SELECT * FROM read_csv('",
    input_sql,
    "', delim = '\t', header = TRUE, ignore_errors = TRUE, union_by_name = TRUE)) TO '",
    output_sql,
    "' (FORMAT PARQUET)"
  )

  conversion_result <- tryCatch(
    expr = {
      duckplyr::db_exec(sql = sql_statement)
      TRUE
    },
    error = function(error) {
      warning(
        stringr::str_c(
          "TSV to Parquet conversion failed for ",
          input_tsv,
          ": ",
          conditionMessage(error)
        ),
        call. = FALSE
      )
      FALSE
    }
  )

  action <- dplyr::if_else(
    condition = conversion_result,
    true = "converted_to_parquet",
    false = "conversion_failed"
  )

  return(
    tibble::tibble(
      input_tsv = input_tsv,
      output_parquet = output_parquet,
      action = action,
      success = conversion_result
    )
  )
}
