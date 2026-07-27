#!/usr/bin/env Rscript

# This script is retained for convenience, but conda/mamba installation is the
# recommended route on the cluster. It sets a CRAN mirror explicitly to avoid
# the common "trying to use CRAN without setting a mirror" error.
#
# Preferred cluster setup:
#   mamba install -c conda-forge -c bioconda r-dplyr r-duckplyr r-duckdb \
#     r-fs r-httr2 r-purrr r-readr r-rlang r-stringr r-tibble r-tidyr \
#     r-xml2 r-testthat bioconductor-expressionatlas

options(repos = c(CRAN = "https://cloud.r-project.org"))

cran_packages <- c(
  "dplyr",
  "duckplyr",
  "fs",
  "httr2",
  "purrr",
  "readr",
  "rlang",
  "stringr",
  "tibble",
  "tidyr",
  "xml2",
  "testthat"
)

missing_cran_packages <- cran_packages[!vapply(
  X = cran_packages,
  FUN = requireNamespace,
  FUN.VALUE = logical(length = 1L),
  quietly = TRUE
)]

if (length(missing_cran_packages) > 0L) {
  message("Installing missing CRAN packages from https://cloud.r-project.org")
  install.packages(pkgs = missing_cran_packages)
}

if (!requireNamespace(package = "ExpressionAtlas", quietly = TRUE)) {
  message(
    paste(
      "ExpressionAtlas is not installed.",
      "On the cluster, prefer conda/bioconda:",
      "mamba install -c conda-forge -c bioconda bioconductor-expressionatlas"
    )
  )
}

message("Dependency installation/check step finished.")
