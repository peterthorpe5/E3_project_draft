testthat::test_that("Plotly PDF export validates dimensions and renderer output", {
  path <- tempfile(fileext = ".pdf")
  fake_save <- function(p, file, format, scale, width, height) {
    testthat::expect_identical(p, "plot")
    testthat::expect_identical(format, "pdf")
    testthat::expect_identical(scale, 1)
    testthat::expect_identical(width, 1400L)
    testthat::expect_identical(height, 900L)
    writeBin(charToRaw("%PDF-1.4 test"), con = file)
  }
  testthat::expect_invisible(write_plotly_pdf(
    plot = "plot",
    path = path,
    save_function = fake_save
  ))
  testthat::expect_error(
    write_plotly_pdf(
      plot = "plot",
      path = tempfile(fileext = ".pdf"),
      width = 10L,
      save_function = fake_save
    ),
    "dimensions"
  )
})

testthat::test_that("PDF validation rejects missing and corrupt files", {
  missing <- tempfile(fileext = ".pdf")
  testthat::expect_error(validate_pdf_file(missing), "valid file")
  corrupt <- tempfile(fileext = ".pdf")
  writeBin(charToRaw("not-a-pdf"), con = corrupt)
  testthat::expect_error(validate_pdf_file(corrupt), "invalid PDF")
})
