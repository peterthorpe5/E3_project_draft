#!/usr/bin/env Rscript

# Run package unit tests in a way that works both after R CMD INSTALL and
# from an unpacked source tree.

if (!requireNamespace(package = "testthat", quietly = TRUE)) {
  stop("The testthat package is required to run tests.", call. = FALSE)
}

if (requireNamespace(package = "E3AtlasDuckplyr", quietly = TRUE)) {
  suppressPackageStartupMessages(library(E3AtlasDuckplyr))
}

testthat::test_dir(
  path = "tests/testthat",
  reporter = "summary"
)
