test_that("command-line parser handles named values and flags", {
  parsed_args <- parse_cli_args(
    args = c("--species_file=data/species.txt", "--force_download")
  )

  expect_equal(parsed_args$species_file, "data/species.txt")
  expect_true(parsed_args$force_download)
  expect_equal(
    get_cli_arg(parsed_args = parsed_args, name = "missing", default = "fallback"),
    "fallback"
  )
})

test_that("logical command-line conversion is robust", {
  expect_true(as_cli_logical(value = "true"))
  expect_true(as_cli_logical(value = "YES"))
  expect_false(as_cli_logical(value = "false", default = TRUE))
  expect_false(as_cli_logical(value = NULL, default = FALSE))
})
