#!/usr/bin/env Rscript

# Run package tests from the repository root. The script first finds its own
# location, then changes to the repository root so relative test paths are
# stable whether the script is launched from the repo, a parent directory, or an
# interactive shell.

source(file.path(dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1L]]), mustWork = TRUE)), "script_utils.R"))

repo_dir <- get_repo_dir_from_script()
setwd(repo_dir)

message("Running tests from: ", repo_dir)
testthat::test_dir("tests/testthat")
