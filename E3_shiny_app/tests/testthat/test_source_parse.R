testthat::test_that("all application R files parse", {
  source_files <- c(
    list.files(
      path = file.path(repo_dir, "R"),
      pattern = "[.]R$",
      full.names = TRUE
    ),
    file.path(repo_dir, "app.R"),
    list.files(
      path = file.path(repo_dir, "inst", "scripts"),
      pattern = "[.]R$",
      full.names = TRUE
    )
  )

  testthat::expect_gt(length(source_files), 0L)

  for (source_file in source_files) {
    testthat::expect_error(
      parse(file = source_file, keep.source = TRUE),
      NA,
      info = basename(source_file)
    )
  }
})
