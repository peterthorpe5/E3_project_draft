#!/usr/bin/env Rscript

required_packages <- c(
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

optional_packages <- c(
  "ExpressionAtlas"
)

check_packages <- function(package_names) {
  present <- vapply(
    X = package_names,
    FUN = requireNamespace,
    FUN.VALUE = logical(length = 1L),
    quietly = TRUE
  )

  data.frame(
    package = package_names,
    installed = unname(present),
    stringsAsFactors = FALSE
  )
}

required_status <- check_packages(required_packages)
optional_status <- check_packages(optional_packages)

message("Required package status:")
print(required_status, row.names = FALSE)

message("\nOptional package status:")
print(optional_status, row.names = FALSE)

missing_required <- required_status$package[!required_status$installed]
missing_optional <- optional_status$package[!optional_status$installed]

if (length(missing_required) > 0L) {
  message("\nMissing required packages:")
  message(paste(missing_required, collapse = ", "))
  message("\nSuggested conda/mamba install into the current environment:")
  message(
    paste(
      "mamba install -c conda-forge -c bioconda",
      paste(
        c(
          "r-dplyr",
          "r-duckplyr",
          "r-duckdb",
          "r-fs",
          "r-httr2",
          "r-purrr",
          "r-readr",
          "r-rlang",
          "r-stringr",
          "r-tibble",
          "r-tidyr",
          "r-xml2",
          "r-testthat",
          "bioconductor-expressionatlas"
        ),
        collapse = " "
      )
    )
  )
  quit(status = 1L)
}

if (length(missing_optional) > 0L) {
  message("\nOptional packages missing:")
  message(paste(missing_optional, collapse = ", "))
  message("ExpressionAtlas is optional only if you supply manual experiment accessions.")
}


python_status <- system2(
  command = "python",
  args = c("-c", "import pyarrow; print(pyarrow.__version__)"),
  stdout = TRUE,
  stderr = TRUE
)
python_ok <- attr(python_status, "status")
if (is.null(python_ok)) {
  python_ok <- 0L
}

message("\nPython pyarrow status:")
if (identical(python_ok, 0L)) {
  message("pyarrow installed: ", paste(python_status, collapse = " "))
} else {
  message("pyarrow is missing or Python could not import it.")
  message("Suggested conda/mamba install:")
  message("mamba install -c conda-forge pyarrow")
  quit(status = 1L)
}

message("\nDependency check finished.")
