# Loaded automatically by testthat::test_dir(). Prefer the checked-out source
# tree so tests do not depend on an older or absent installed package.

candidate_roots <- unique(normalizePath(
  path = c(
    getwd(),
    file.path(getwd(), "expression_downloader"),
    file.path(getwd(), ".."),
    file.path(getwd(), "..", "..")
  ),
  mustWork = FALSE
))

is_source_package <- vapply(
  X = candidate_roots,
  FUN = function(candidate) {
    description <- file.path(candidate, "DESCRIPTION")
    if (!file.exists(description) || !dir.exists(file.path(candidate, "R"))) {
      return(FALSE)
    }
    package_name <- tryCatch(
      read.dcf(description, fields = "Package")[[1L]],
      error = function(error) ""
    )
    identical(package_name, "E3AtlasDuckplyr")
  },
  FUN.VALUE = logical(1L)
)

if (any(is_source_package)) {
  package_root <- candidate_roots[is_source_package][[1L]]
  r_files <- list.files(
    path = file.path(package_root, "R"),
    pattern = "[.]R$",
    full.names = TRUE
  )
  for (r_file in sort(r_files)) {
    source(file = r_file)
  }
} else if (requireNamespace("E3AtlasDuckplyr", quietly = TRUE)) {
  suppressPackageStartupMessages(library(E3AtlasDuckplyr))
} else {
  stop(
    "Could not find the E3AtlasDuckplyr source tree or installed package.",
    call. = FALSE
  )
}
