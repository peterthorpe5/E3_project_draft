#' Choose a conservative Excel format for one scientific column.
#'
#' @param column_name Non-empty source column name.
#' @param column Source vector.
#' @return Stable format category used by `write_formatted_excel()`.

excel_format_kind <- function(column_name, column) {
  if (
    length(column_name) != 1L ||
      is.na(column_name) ||
      !nzchar(column_name)
  ) {
    stop("Excel columns must have non-empty names.", call. = FALSE)
  }
  if (grepl(
    "(^|_)(accession|checksum|digest|identifier|id)(_|$)",
    column_name,
    ignore.case = TRUE
  )) {
    return("text")
  }
  if (is.logical(column)) {
    return("logical")
  }
  if (inherits(column, "POSIXt")) {
    return("datetime")
  }
  if (inherits(column, "Date")) {
    return("date")
  }
  if (
    is.integer(column) ||
      grepl(
        "(^|_)(count|index|length|number|position|rank)(_|$)",
        column_name,
        ignore.case = TRUE
      )
  ) {
    return("integer")
  }
  if (is.numeric(column)) {
    if (grepl(
      "(^|_)(e_?value|fdr|p_?value|q_?value)(_|$)",
      column_name,
      ignore.case = TRUE
    )) {
      return("scientific")
    }
    return("decimal")
  }
  "text"
}

#' Calculate one bounded Excel column width.
#'
#' @param column_name Non-empty source column name.
#' @param column Source vector.
#' @return Numeric Excel width between 12 and 50 character units.
excel_column_width <- function(column_name, column) {
  if (
    length(column_name) != 1L ||
      is.na(column_name) ||
      !nzchar(column_name)
  ) {
    stop("Excel columns must have non-empty names.", call. = FALSE)
  }
  values <- utils::head(column, 500L)
  values <- vapply(
    X = values,
    FUN = function(value) {
      if (length(value) == 0L || all(is.na(value))) {
        return("")
      }
      paste(as.character(value), collapse = "; ")
    },
    FUN.VALUE = character(1)
  )
  max(12, min(50, max(nchar(c(column_name, values)), na.rm = TRUE) + 2))
}

#' Prepare a flat data frame for safe Excel serialisation.
#'
#' @param data Tabular object.
#' @return Data frame with stable names and supported atomic columns.
prepare_excel_data <- function(data) {
  if (!is.data.frame(data)) {
    stop("Excel export requires a data frame.", call. = FALSE)
  }
  if (ncol(data) == 0L) {
    stop("Excel export requires at least one column.", call. = FALSE)
  }
  column_names <- names(data)
  if (
    any(is.na(column_names)) ||
      any(!nzchar(column_names)) ||
      anyDuplicated(column_names) > 0L
  ) {
    stop("Excel export requires unique, non-empty column names.", call. = FALSE)
  }
  prepared <- as.data.frame(data, stringsAsFactors = FALSE, check.names = FALSE)
  prepared[] <- lapply(prepared, function(column) {
    if (is.factor(column)) {
      return(as.character(column))
    }
    if (inherits(column, "integer64")) {
      return(as.character(column))
    }
    if (is.list(column) && !inherits(column, "POSIXlt")) {
      return(vapply(
        X = column,
        FUN = function(value) {
          if (length(value) == 0L || all(is.na(value))) {
            return(NA_character_)
          }
          paste(as.character(value), collapse = "; ")
        },
        FUN.VALUE = character(1)
      ))
    }
    column
  })
  prepared
}

#' Write a filterable and formatted Excel workbook.
#'
#' @param data Exact displayed or filtered data frame.
#' @param path Destination XLSX path.
#' @param sheet_name Worksheet name, limited to Excel's 31-character maximum.
#' @return Destination path, invisibly.
write_formatted_excel <- function(data, path, sheet_name = "Selection") {
  if (!requireNamespace("openxlsx", quietly = TRUE)) {
    stop(
      "The openxlsx package is required for Excel downloads.",
      call. = FALSE
    )
  }
  if (
    length(path) != 1L ||
      is.na(path) ||
      !nzchar(path) ||
      !dir.exists(dirname(path))
  ) {
    stop("Excel export requires a writable destination directory.", call. = FALSE)
  }
  if (
    length(sheet_name) != 1L ||
      is.na(sheet_name) ||
      !nzchar(sheet_name) ||
      nchar(sheet_name) > 31L ||
      grepl("[][\\:*?/]", sheet_name)
  ) {
    stop("The Excel worksheet name is invalid.", call. = FALSE)
  }
  prepared <- prepare_excel_data(data = data)
  workbook <- openxlsx::createWorkbook(
    creator = "Peter Thorpe and collaborators",
    title = "ARIA plant E3 displayed results",
    subject = "Filterable export from the ARIA plant E3 reporter"
  )
  openxlsx::addWorksheet(
    wb = workbook,
    sheetName = sheet_name,
    gridLines = FALSE,
    tabColour = "#1F4E78",
    zoom = 90
  )
  header_style <- openxlsx::createStyle(
    fontColour = "#FFFFFF",
    fgFill = "#1F4E78",
    textDecoration = "bold",
    halign = "left",
    valign = "center"
  )

  if (nrow(prepared) > 0L) {
    openxlsx::writeDataTable(
      wb = workbook,
      sheet = sheet_name,
      x = prepared,
      startRow = 1L,
      startCol = 1L,
      tableStyle = "TableStyleMedium2",
      tableName = "SelectionTable",
      withFilter = TRUE,
      keepNA = FALSE
    )
  } else {
    openxlsx::writeData(
      wb = workbook,
      sheet = sheet_name,
      x = t(names(prepared)),
      startRow = 1L,
      startCol = 1L,
      colNames = FALSE,
      rowNames = FALSE
    )
    openxlsx::addFilter(
      wb = workbook,
      sheet = sheet_name,
      rows = 1L,
      cols = seq_len(ncol(prepared))
    )
  }
  openxlsx::addStyle(
    wb = workbook,
    sheet = sheet_name,
    style = header_style,
    rows = 1L,
    cols = seq_len(ncol(prepared)),
    gridExpand = TRUE,
    stack = TRUE
  )
  openxlsx::setRowHeights(
    wb = workbook,
    sheet = sheet_name,
    rows = 1L,
    heights = 24
  )
  openxlsx::freezePane(
    wb = workbook,
    sheet = sheet_name,
    firstActiveRow = 2L
  )
  widths <- vapply(
    X = seq_along(prepared),
    FUN = function(index) {
      excel_column_width(
        column_name = names(prepared)[[index]],
        column = prepared[[index]]
      )
    },
    FUN.VALUE = numeric(1)
  )
  openxlsx::setColWidths(
    wb = workbook,
    sheet = sheet_name,
    cols = seq_along(prepared),
    widths = widths
  )

  if (nrow(prepared) > 0L) {
    format_codes <- c(
      integer = "#,##0",
      decimal = "0.000",
      scientific = "0.00E+00",
      date = "yyyy-mm-dd",
      datetime = "yyyy-mm-dd hh:mm"
    )
    for (index in seq_along(prepared)) {
      kind <- excel_format_kind(
        column_name = names(prepared)[[index]],
        column = prepared[[index]]
      )
      style <- if (kind %in% names(format_codes)) {
        openxlsx::createStyle(
          numFmt = unname(format_codes[[kind]]),
          valign = "top"
        )
      } else if (identical(kind, "logical")) {
        openxlsx::createStyle(halign = "center", valign = "top")
      } else {
        openxlsx::createStyle(wrapText = TRUE, valign = "top")
      }
      openxlsx::addStyle(
        wb = workbook,
        sheet = sheet_name,
        style = style,
        rows = seq.int(2L, nrow(prepared) + 1L),
        cols = index,
        gridExpand = TRUE,
        stack = TRUE
      )
    }
  }
  openxlsx::saveWorkbook(
    wb = workbook,
    file = path,
    overwrite = TRUE
  )
  invisible(path)
}

#' Build neighbouring TSV and Excel download buttons.
#'
#' @param ns Shiny namespace function.
#' @param tsv_id TSV output identifier.
#' @param excel_id Excel output identifier.
#' @param tsv_label User-facing TSV label.
#' @param excel_label User-facing Excel label.
#' @return Shiny UI containing paired download buttons.
tabular_download_buttons <- function(
  ns,
  tsv_id,
  excel_id,
  tsv_label,
  excel_label
) {
  if (!is.function(ns)) {
    stop("A Shiny namespace function is required.", call. = FALSE)
  }
  identifiers <- c(tsv_id, excel_id, tsv_label, excel_label)
  if (any(is.na(identifiers)) || any(!nzchar(identifiers))) {
    stop("Download identifiers and labels must be non-empty.", call. = FALSE)
  }
  shiny::div(
    class = "download-actions",
    shiny::downloadButton(
      outputId = ns(tsv_id),
      label = tsv_label
    ),
    shiny::downloadButton(
      outputId = ns(excel_id),
      label = excel_label
    )
  )
}
