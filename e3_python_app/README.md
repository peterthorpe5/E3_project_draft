# ARIA plant E3 Python reporter

Version 0.3.0 is the tested Streamlit companion to `E3_shiny_app` 0.6.0. Both
applications use the same release contract and answer the same grant-facing
questions across candidate prioritisation, OrthoFinder grouping, domains,
expression, ligandability, pocket conservation, 3D alignment and provenance.

The app is read-only. It opens a completed DuckDB directly or registers Parquet
files as views in an in-memory DuckDB. Every table query has a hard row cap and
only the selected, bounded result is collected into pandas. The Python app uses
the native `duckdb` Python client for SQL execution; it does not use `duckplyr`,
which is an R-specific dplyr translation layer.

## Result-source modes

Choose exactly one:

```bash
# Recommended complete release
./run_e3_python_app.sh \
  --resource-duckdb /path/to/e3_integrated_resource.duckdb \
  --pocket-review-dir /path/to/portable_release/pocket_review \
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
`E3_RESOURCE_RUN_DIR`, `E3_EXPRESSION_DUCKDB`, `E3_POCKET_REVIEW_DIR` and
`E3_MAX_TABLE_ROWS`.

The pocket-review option is additive and optional. When it is omitted, the app
auto-discovers the bundle only if exactly one valid direct child beginning with
`pocket_review` is beside the selected DuckDB/Parquet, or inside the selected
run directory. It never guesses between multiple bundles.

## Interface

The reporter provides:

- a dedicated Computational recommendations view containing the ordered top-50 review
  shortlist, strict grant-aligned predictions, named gate-sensitivity
  scenarios, evolutionary-group scorecard, contributors, representative audit
  and exclusion reasons;
- a grant overview separating Milestone 1 conservation evidence from Milestone
  2 conserved structural/chemical starting space;
- focused Candidates, Orthology, Domains, Expression, Ligandability, Pocket
  conservation and 3D alignment sections;
- a separate Threshold explorer with the completed analysis defaults, paired
  sliders and typed values, pre-structure and structurally informed modes,
  explicit `PASS`, `NEAR_MISS`, `FAIL` and `NOT_STRUCTURALLY_ASSESSED` labels,
  expanded candidate evidence and TSV export;
- selected-group 3D structure/pocket and pocket-annotated MAFFT alignment tabs
  backed by the self-contained top-200 review bundle;
- searchable HOG/orthogroup, DeepClust cluster, rank and accession choices,
  alongside downloadable OrthoFinder member sequence/model identifiers;
- a separate column multiselect and row limit for every section;
- exact accession search across recognised scalar and semicolon-delimited
  candidate/member fields;
- a schema-agnostic all-results browser;
- provenance and QC views; and
- TSV downloads of the displayed result.

The integrated DuckDB remains the complete relational authority. The single
master Parquet is a portable wide compatibility summary. The definitive
one-row-per-evolutionary-group table is
`final_results/final_evolutionary_candidate_prioritisation.parquet`, available
through integrated-DuckDB and run-directory modes, while one-to-many group
members, pockets, domain hits and residue matches remain detailed DuckDB
relations.
The structural-completion release also publishes the decision-facing workbook
and normalised tables under `10_integrated_resource/final_results`.

## Install and validate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

`run_tests.sh` also puts this checkout's `src/` directory on `PYTHONPATH`, so its
source tests can run before editable installation. The editable install remains
required for the `e3-python-app` command.

The v0.3.0 quality gate comprises 36 passing tests at 98% branch-aware coverage
of DuckDB, master-Parquet, run-directory, threshold, portable-review and
headless Streamlit behaviour.

## Portable top-200 visualisation release

The expected local layout is:

```text
portable_visualisation_release_top200_20260803/
├── e3_integrated_resource.duckdb
├── e3_candidate_master_results.parquet
├── pocket_review/
│   ├── groups/
│   ├── sequences/
│   ├── tables/
│   ├── provenance/
│   └── index.html
└── SHA256SUMS.txt
```

Launch it on macOS with:

```bash
PORTABLE_ROOT="/Volumes/One Touch/2026_E3_protac/portable_visualisation_release_top200_20260803"

./run_e3_python_app.sh \
  --resource-duckdb "${PORTABLE_ROOT}/e3_integrated_resource.duckdb" \
  --pocket-review-dir "${PORTABLE_ROOT}/pocket_review" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501
```

The portable HTML pages embed the C-alpha traces, pocket mappings, alignment,
CSS and JavaScript. The app does not need cluster access or a remote structure
service after the release has been copied.

## Interpretation boundary

These are computational recommendations. OrthoFinder membership, E3-domain
support, RNA expression, predicted cavities, pocket-region conservation and
US-align/TM-align agreement do not prove E3 activity, compound binding or
induced degradation.
