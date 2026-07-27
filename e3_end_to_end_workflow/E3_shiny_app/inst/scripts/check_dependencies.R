#!/usr/bin/env Rscript

# Check that the R packages needed by the Shiny app and its tests are available
# in the active R/conda environment. This script deliberately does not install
# packages; on the cluster and on macOS it is safer to install with conda/mamba
# or the user's chosen package-management route.

required_packages <- c(
  "bslib",
  "dplyr",
  "DT",
  "duckplyr",
  "ggplot2",
  "plotly",
  "rlang",
  "shiny",
  "shinycssloaders",
  "stringr",
  "testthat",
  "tibble"
)

optional_test_packages <- c(
  "DBI",
  "duckdb"
)

missing_packages <- required_packages[!vapply(
  X = required_packages,
  FUN = requireNamespace,
  FUN.VALUE = logical(1),
  quietly = TRUE
)]

missing_optional_test_packages <- optional_test_packages[!vapply(
  X = optional_test_packages,
  FUN = requireNamespace,
  FUN.VALUE = logical(1),
  quietly = TRUE
)]

if (length(missing_packages) > 0L) {
  stop(
    paste0(
      "Missing required R packages: ",
      paste(missing_packages, collapse = ", ")
    ),
    call. = FALSE
  )
}

message("All required R packages are available.")

if (length(missing_optional_test_packages) > 0L) {
  message(
    "Optional packages missing; some tests will be skipped: ",
    paste(missing_optional_test_packages, collapse = ", ")
  )
}
