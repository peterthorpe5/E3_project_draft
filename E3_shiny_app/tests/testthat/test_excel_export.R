testthat::test_that("Excel format selection preserves scientific meaning", {
  testthat::expect_equal(
    excel_format_kind(
      column_name = "candidate_accession",
      column = c("Q9SA03")
    ),
    "text"
  )
  testthat::expect_equal(
    excel_format_kind(column_name = "final_rank", column = 1:2),
    "integer"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "final_score",
      column = c(0.91, 0.80)
    ),
    "decimal"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "member_count",
      column = c(1, NA_real_, 3)
    ),
    "integer"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "same_pocket_position_support_fraction",
      column = c(0, 0.5, 1)
    ),
    "decimal"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "adjusted_p_value",
      column = c(1e-08, 0.05)
    ),
    "scientific"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "supported",
      column = c(TRUE, FALSE)
    ),
    "logical"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "review_date",
      column = as.Date("2026-08-12")
    ),
    "date"
  )
  testthat::expect_equal(
    excel_format_kind(
      column_name = "updated_at",
      column = as.POSIXct("2026-08-12", tz = "UTC")
    ),
    "datetime"
  )
  testthat::expect_error(
    excel_format_kind(column_name = "", column = 1:2),
    "non-empty"
  )
})

testthat::test_that("export file stems remain portable", {
  testthat::expect_identical(
    safe_export_stem("all results: relation/name"),
    "all_results_relation_name"
  )
  testthat::expect_error(safe_export_stem("///"), "cannot be empty")
  testthat::expect_error(safe_export_stem(1), "character scalar")
})

testthat::test_that("Excel widths remain readable and bounded", {
  testthat::expect_equal(
    excel_column_width(column_name = "rank", column = 1:2),
    12
  )
  testthat::expect_equal(
    excel_column_width(
      column_name = "description",
      column = paste(rep("x", 200), collapse = "")
    ),
    50
  )
  testthat::expect_error(
    excel_column_width(column_name = "", column = 1:2),
    "non-empty"
  )
})

testthat::test_that("long Excel text is identified without changing values", {
  values <- c(paste(rep("x", 81), collapse = ""), paste(rep("x", 80), collapse = ""), NA)
  testthat::expect_identical(excel_long_text_rows(values), 2L)
  testthat::expect_error(excel_long_text_rows(values, threshold = 0), "positive")
})

testthat::test_that("Excel preparation validates and flattens data safely", {
  source <- data.frame(
    factor_value = factor(c("a", "b")),
    stringsAsFactors = FALSE
  )
  source$list_value <- list(c("x", "y"), character())
  prepared <- prepare_excel_data(data = source)
  testthat::expect_type(prepared$factor_value, "character")
  testthat::expect_equal(prepared$list_value[[1L]], "x; y")
  testthat::expect_true(is.na(prepared$list_value[[2L]]))
  testthat::expect_error(
    prepare_excel_data(data = list(a = 1)),
    "data frame"
  )
  testthat::expect_error(
    prepare_excel_data(data = data.frame()),
    "at least one"
  )

  duplicated <- data.frame(a = 1, b = 2)
  names(duplicated) <- c("score", "score")
  testthat::expect_error(prepare_excel_data(data = duplicated), "unique")
})

testthat::test_that("formatted Excel has filters, frozen headers and formats", {
  testthat::skip_if_not_installed("openxlsx")
  output <- tempfile(fileext = ".xlsx")
  data <- data.frame(
    candidate_accession = c("Q9SA03", "=2+2"),
    final_rank = 1:2,
    final_score = c(0.91234, 0.2),
    adjusted_p_value = c(1e-08, 0.05),
    supported = c(TRUE, FALSE),
    notes = c(paste(rep("x", 120), collapse = ""), "short"),
    stringsAsFactors = FALSE
  )
  returned <- write_formatted_excel(data = data, path = output)
  testthat::expect_identical(returned, output)
  testthat::expect_true(file.exists(output))

  extracted <- tempfile(pattern = "e3_excel_")
  dir.create(extracted)
  utils::unzip(zipfile = output, exdir = extracted)
  sheet_xml <- paste(
    readLines(file.path(extracted, "xl", "worksheets", "sheet1.xml")),
    collapse = ""
  )
  table_files <- list.files(
    file.path(extracted, "xl", "tables"),
    pattern = "^table[0-9]+[.]xml$",
    full.names = TRUE
  )
  testthat::expect_length(table_files, 1L)
  table_xml <- paste(readLines(table_files[[1L]], warn = FALSE), collapse = "")
  styles_xml <- paste(
    readLines(file.path(extracted, "xl", "styles.xml")),
    collapse = ""
  )
  testthat::expect_match(sheet_xml, "state=\"frozen\"")
  testthat::expect_match(sheet_xml, "ySplit=\"1\"")
  testthat::expect_match(sheet_xml, "ht=\"60\"")
  testthat::expect_match(sheet_xml, "customHeight=\"1\"")
  testthat::expect_false(grepl("showGridLines=\"0\"", sheet_xml, fixed = TRUE))
  testthat::expect_match(table_xml, "autoFilter")
  testthat::expect_match(table_xml, "TableStyleMedium2")
  testthat::expect_match(styles_xml, "0.000", fixed = TRUE)
  testthat::expect_match(styles_xml, "0.00E+00", fixed = TRUE)
  testthat::expect_match(styles_xml, "horizontal=\"center\"", fixed = TRUE)
  testthat::expect_match(styles_xml, "vertical=\"center\"", fixed = TRUE)
  testthat::expect_match(styles_xml, "val=\"10\"", fixed = TRUE)
  testthat::expect_false(grepl("<f>", sheet_xml, fixed = TRUE))

  testthat::expect_error(
    write_formatted_excel(data = data, path = file.path(output, "bad.xlsx")),
    "writable destination"
  )
  testthat::expect_error(
    write_formatted_excel(data = data, path = output, sheet_name = "bad/name"),
    "worksheet name"
  )
})

testthat::test_that("paired download UI retains TSV and adds Excel", {
  ui <- paste(
    as.character(tabular_download_buttons(
      ns = shiny::NS("test"),
      tsv_id = "download_tsv",
      excel_id = "download_excel",
      tsv_label = "Download TSV",
      excel_label = "Download Excel"
    )),
    collapse = "\n"
  )
  testthat::expect_match(ui, "test-download_tsv", fixed = TRUE)
  testthat::expect_match(ui, "test-download_excel", fixed = TRUE)
  testthat::expect_match(ui, "Download Excel", fixed = TRUE)
  testthat::expect_error(
    tabular_download_buttons(
      ns = NULL,
      tsv_id = "tsv",
      excel_id = "excel",
      tsv_label = "TSV",
      excel_label = "Excel"
    ),
    "namespace"
  )
})
