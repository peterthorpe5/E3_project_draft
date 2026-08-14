# ARIA E3 app release handover — 14 August 2026

## Coordinated release

- R Shiny reporter: `E3_shiny_app` v0.14.0
- Python Streamlit reporter: `e3_python_app` v0.11.0
- Portable pocket-review producer: `e3_structural_alignment` v0.4.0
- Required workflow resource: the integrated release DuckDB is recommended;
  the apps remain read-only consumers of completed workflow outputs.

This package is an additive application release. It does not change the locked
workflow ranking, scientific thresholds or source database.

## Delivered changes

### Question-mark help throughout both apps

Every top-level tab now begins with a collapsed **❓ How to use this tab** box.
The text is maintained by tab rather than copied into individual pages:

- R: `E3_shiny_app/R/tab_help.R`
- Python: `e3_python_app/src/e3app/tab_help.py`

The guidance describes the main controls, evidence boundary and a relevant
interpretation caution. R tests require all 25 R tabs to be registered; Python
tests require all 23 Python tabs to be registered. This makes omitted guidance
an explicit test failure when future primary tabs are added.

### One-click top-200 pre-structure HOG list

Both apps now include **Pre-structure ranked HOGs** immediately after the
general Threshold explorer. The page defaults to the requested top 200 and is
designed for the team's non-structure-gated follow-up analysis.

The page:

1. requires `primary_group_id` plus an authoritative recorded HOG-level rank;
2. accepts `prestructure_evolutionary_group_rank`, or the equivalent published
   `evolutionary_group_rank` field;
3. deliberately rejects the distinct cluster-level `computational_rank` as a
   surrogate HOG rank;
4. retains root-level `N0.HOG…` groups only;
5. deterministically selects one source row per HOG;
6. sorts and limits by the recorded pre-structure HOG rank;
7. applies no target-species, mandatory-species, domain, expression, pocket,
   druggability, mapping, 3D or structural-assessment gate;
8. adds available human and Arabidopsis representatives from root-level
   hierarchical membership;
9. supports an adjustable top-N count within the configured global row cap;
10. searches only inside the selected top-N set without recalculating or
    renumbering the authoritative ranks; and
11. downloads the visible rich table as TSV or formatted Excel.

If a legacy resource does not publish the required HOG identifier and rank, the
tab reports that limitation. It does not invent a different biological result.

Core implementations:

- R: `R/prestructure_hog_explorer.R` and
  `R/module_prestructure_hog_explorer.R`
- Python: `src/e3app/prestructure_hogs.py` and the corresponding renderer in
  `src/e3app/streamlit_app.py`

### Python runtime-warning fixes

All deprecated `use_container_width=True` calls were replaced by
`width="stretch"`. Streamlit 1.51 or newer is therefore required and is pinned
consistently in `pyproject.toml`, `requirements.txt` and `environment.yml`.

The `recommendation_druggability_group` selector now receives its initial value
only through its keyed Session State entry. It no longer supplies an additional
`index` default, removing the duplicate widget-state warning while preserving
the existing selected-group behaviour.

## Scientific interpretation boundary

The new top-N page is an analysis convenience view, not a new ranking. It uses
the recorded pre-structure evolutionary-group rank exactly as published. It is
expected to include groups that fail one or more candidate gates because the
requested purpose is explicitly to inspect ranked HOGs without those gates.

Root HOG membership represents OrthoFinder hierarchical evolutionary grouping.
It does not by itself prove conserved E3 function, ligand binding or induced
protein degradation. Empty human or Arabidopsis representative fields mean the
loaded membership did not contain that lineage; they are not negative
experimental results.

## Validation status

The user's predecessor suites passed before this additive release. In this
build workspace:

- all Python source and tests compile;
- edited Python files satisfy the 100-character line limit;
- whitespace/error checks pass;
- the Python help catalogue contains all 23 top-level tabs;
- the R application contains help calls for all 25 top-level tabs;
- no Python production source retains `use_container_width`; and
- focused tests were added for ranking authority, deterministic ordering,
  absence of gate filtering, root-HOG restriction, representative annotation,
  rank-preserving search, error/empty states, downloads and help coverage.

The workspace lacks a usable R and full Python app-test environment, so the
complete executable suites have not been claimed here. Both are mandatory
before publication.

### Python release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

### R release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two R `test_script_utils.R` skips are expected only when the session does
not provide a `--file` argument. Any real test failure blocks release.

## Local launch examples

Python:

```bash
./e3_python_app/run_e3_python_app.sh \
  --resource-duckdb /absolute/path/e3_integrated_resource.duckdb \
  --pocket-review-dir /absolute/path/pocket_review_top200_v0_3_1 \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501
```

R:

```bash
Rscript E3_shiny_app/app.R \
  --resource_duckdb_path /absolute/path/e3_integrated_resource.duckdb \
  --pocket_review_dir /absolute/path/pocket_review_top200_v0_3_1 \
  --max_table_rows 1000 \
  --host 127.0.0.1 \
  --port 3838
```

For a university-hosted service, bind the application process to loopback and
place the supported HTTPS reverse proxy in front of it unless local deployment
policy specifies another arrangement. Do not expose DuckDB or source-file
paths through a public directory.

## Maintainer requirements

Future changes must preserve the project's established rules:

- prefer Python when it is the clearest implementation, while maintaining
  equivalent user-facing behaviour in R where both apps expose the feature;
- use UK English in labels and documentation;
- keep applications read-only and all database queries bounded;
- do not silently convert missing annotation or unassessed evidence into a
  biological failure or pass;
- keep HOG, legacy orthogroup and DeepClust concepts explicitly separate;
- preserve source-relation and matched-field provenance in searches;
- provide TSV rather than CSV for analytical text downloads;
- use named function arguments in project code where practical;
- keep Python code PEP 8 compliant with Google-style docstrings, defensive
  validation and useful logging;
- avoid embedded Python inside production shell scripts;
- add or update unit tests for every changed function and regression;
- run both complete suites before release; and
- never change the authoritative production ranking from an exploratory app
  control.

## Recommended next action

Install the updated Python environment so Streamlit 1.51 or newer is active,
run both release gates, launch both apps against the same integrated DuckDB and
visually verify the new top-N table and help box on a representative sample of
tabs. If both suites pass, commit the coordinated versions and publish the
archive checksum with the release.
