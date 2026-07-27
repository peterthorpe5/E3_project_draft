testthat::test_that("result-source resolution requires zero or one source", {
  unconfigured <- resolve_resource_source()
  testthat::expect_equal(unconfigured$mode, "unconfigured")
  duckdb <- resolve_resource_source(resource_duckdb_path = "/tmp/result.duckdb")
  testthat::expect_equal(duckdb$mode, "duckdb")
  parquet <- resolve_resource_source(resource_parquet_path = "/tmp/result.parquet")
  testthat::expect_equal(parquet$mode, "master_parquet")
  run <- resolve_resource_source(resource_run_dir = "/tmp/run")
  testthat::expect_equal(run$mode, "run_directory")
  testthat::expect_error(
    resolve_resource_source(
      resource_duckdb_path = "/tmp/result.duckdb",
      resource_parquet_path = "/tmp/result.parquet"
    ),
    "exactly one"
  )
})

testthat::test_that("unknown Parquet names become safe deterministic relations", {
  root <- file.path(tempdir(), "run")
  name <- safe_parquet_relation_name(
    file.path(root, "06_domains", "tables", "odd result.parquet"),
    root
  )
  testthat::expect_equal(name, "06_domains_tables_odd_result")
  testthat::expect_equal(
    coerce_resource_source("/tmp/resource.duckdb")$mode,
    "duckdb"
  )
  testthat::expect_error(coerce_resource_source(42), "Invalid")
})

testthat::test_that("master Parquet and run-directory modes expose canonical views", {
  testthat::skip_if_not_installed("DBI")
  testthat::skip_if_not_installed("duckdb")
  testthat::skip_if_not_installed("duckplyr")

  parquet <- tempfile(fileext = ".parquet")
  connection <- DBI::dbConnect(duckdb::duckdb(), dbdir = ":memory:")
  DBI::dbExecute(
    connection,
    paste0(
      "COPY (SELECT 1 AS final_rank, 'cluster_1' AS cluster_id, ",
      "TRUE AS grant_aligned_prestructure_pass, ",
      "TRUE AS grant_aligned_final_pass, ",
      "'NOT_ASSESSED' AS three_dimensional_alignment_status) TO '",
      escape_sql_literal(parquet),
      "' (FORMAT PARQUET)"
    )
  )
  DBI::dbDisconnect(connection, shutdown = TRUE)

  master_source <- resolve_resource_source(resource_parquet_path = parquet)
  testthat::expect_true(resource_source_available(master_source))
  views <- collect_resource_view_names(master_source)
  testthat::expect_true("candidate_master_results" %in% views)
  testthat::expect_equal(
    collect_resource_row_count(master_source, "candidate_master_results"),
    1
  )
  selected <- collect_selected_result(
    master_source,
    "candidate_master_results",
    c("final_rank", "cluster_id"),
    10
  )
  testthat::expect_equal(names(selected), c("final_rank", "cluster_id"))
  overview <- collect_grant_overview(master_source)
  testthat::expect_equal(overview$candidate_count[[1L]], 1)
  testthat::expect_equal(overview$final_pass_count[[1L]], 1)

  run_dir <- tempfile("e3_run_")
  destination <- file.path(
    run_dir,
    "10_integrated_resource",
    "tables",
    "e3_candidate_master_results.parquet"
  )
  dir.create(dirname(destination), recursive = TRUE)
  testthat::expect_true(file.copy(parquet, destination))
  run_source <- resolve_resource_source(resource_run_dir = run_dir)
  discovered <- discover_result_parquets(run_dir)
  testthat::expect_equal(names(discovered), "candidate_master_results")
  testthat::expect_true("resource_relation_catalog" %in%
    collect_resource_view_names(run_source))
})
