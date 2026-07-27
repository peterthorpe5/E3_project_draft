# ARIA plant E3 Python reporter

Version 0.2.0 is the tested Streamlit companion to `E3_shiny_app` 0.4.0. Both
applications use the same release contract and answer the same grant-facing
questions across candidate prioritisation, OrthoFinder grouping, domains,
expression, ligandability, pocket conservation, 3D alignment and provenance.

The app is read-only. It opens a completed DuckDB directly or registers Parquet
files as views in an in-memory DuckDB. Every table query has a hard row cap and
only the columns selected by the user are collected into Pandas.

## Result-source modes

Choose exactly one:

```bash
# Recommended complete release
./run_e3_python_app.sh \
  --resource-duckdb /path/to/e3_integrated_resource.duckdb \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501

# One candidate-level hand-off
./run_e3_python_app.sh \
  --resource-parquet /path/to/e3_candidate_master_results.parquet \
  --max-rows 1000

# Current workflow stage Parquets
./run_e3_python_app.sh \
  --resource-run-dir /path/to/completed_workflow_run \
  --max-rows 1000
```

Run-directory mode excludes hidden and `superseded` paths, discovers all
remaining Parquets recursively and assigns deterministic relation names.

Environment equivalents are `E3_RESOURCE_DUCKDB`, `E3_RESOURCE_PARQUET`,
`E3_RESOURCE_RUN_DIR`, `E3_EXPRESSION_DUCKDB` and `E3_MAX_TABLE_ROWS`.

## Interface

The reporter provides:

- a grant overview separating Milestone 1 conservation evidence from Milestone
  2 conserved structural/chemical starting space;
- focused Candidates, Orthology, Domains, Expression, Ligandability, Pocket
  conservation and 3D alignment sections;
- a separate column multiselect and row limit for every section;
- exact accession search across recognised scalar and semicolon-delimited
  candidate/member fields;
- a schema-agnostic all-results browser;
- provenance and QC views; and
- TSV downloads of the displayed result.

The integrated DuckDB remains the complete authority. The single master Parquet
contains one wide row per candidate group, while one-to-many group members,
pockets, domain hits and residue matches remain detailed DuckDB relations.

## Install and validate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

`run_tests.sh` also puts this checkout's `src/` directory on `PYTHONPATH`, so its
source tests can run before editable installation. The editable install remains
required for the `e3-python-app` command.

The current quality gate comprises 22 tests at 98% branch-aware coverage,
including DuckDB, master-Parquet, run-directory and headless Streamlit checks.

## Interpretation boundary

These are computational recommendations. OrthoFinder membership, E3-domain
support, RNA expression, predicted cavities, pocket-region conservation and
US-align/TM-align agreement do not prove E3 activity, compound binding or
induced degradation.
