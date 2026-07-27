testthat::test_that("script path helper returns an existing Rscript file when available", {
  script_path <- tryCatch(
    get_current_script_path(),
    error = function(error) NA_character_
  )

  testthat::skip_if(is.na(script_path), "No --file argument available in this R session")
  testthat::expect_true(file.exists(script_path))
})

testthat::test_that("repository root helper finds the package DESCRIPTION when script path is available", {
  root <- tryCatch(
    get_repo_dir_from_script(),
    error = function(error) NA_character_
  )

  testthat::skip_if(is.na(root), "No --file argument available in this R session")
  testthat::expect_true(file.exists(file.path(root, "DESCRIPTION")))
  testthat::expect_true(file.exists(file.path(root, "R", "utils.R")))
})
