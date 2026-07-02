test_that("default expression Parquet glob uses fixed partition structure", {
  glob <- build_expression_parquet_glob(parquet_dir = "analysis/parquet")

  expect_match(glob, "species_column=\\*")
  expect_match(glob, "experiment_accession=\\*")
  expect_false(grepl("\\*\\*", glob))
})


test_that("sample metadata Parquet globs use fixed partition structure", {
  long_glob <- build_sample_metadata_long_parquet_glob(parquet_dir = "analysis/parquet")
  wide_glob <- build_sample_metadata_wide_parquet_glob(parquet_dir = "analysis/parquet")

  expect_match(long_glob, "atlas_sample_metadata_long")
  expect_match(wide_glob, "atlas_sample_metadata_wide")
  expect_match(long_glob, "species_column=\\*")
  expect_match(wide_glob, "experiment_accession=\\*")
  expect_false(grepl("\\*\\*", long_glob))
  expect_false(grepl("\\*\\*", wide_glob))
})
