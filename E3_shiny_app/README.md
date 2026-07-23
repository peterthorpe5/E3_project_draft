# ARIA plant E3 Shiny reporter

Version 0.4.0 is the grant-focused R reporter for the PT_E3_6 workflow. It is a
read-only consumer: scientific transformations happen in the workflow packages,
while Shiny sends bounded lazy queries to DuckDB through duckplyr.

## Questions the reporter answers

The main sections follow the evidence path required by the grant:

1. **Candidates** – combined discovery, conservation, domain, expression and
   structural prioritisation, with inclusion, exclusion and missing-evidence
   reasons.
2. **Orthology** – explicit OrthoFinder orthogroup and hierarchical-group IDs,
   species membership, member accessions and candidate-relevant sequences.
3. **Domains** – catalogued E3-associated domain support and explicit annotation
   unavailable states.
4. **Expression evidence** – identifier mapping and broad Expression Atlas
   support without treating unavailable resources as biological negatives.
5. **Ligandability** – selected fpocket/P2Rank-supported pockets, structure
   availability, pLDDT and mapping quality.
6. **Pocket conservation** – conserved pocket-bearing alignment regions and
   validated pocket-residue-to-FASTA coordinates.
7. **3D alignment** – separate US-align/TM-align conclusions for equivalent 3D
   pocket position and stronger local pocket-structure conservation.
8. **Provenance and QC** – release metadata, relation catalogue and source paths.

Every section has its own checkbox column selector. `Grant defaults` restores a
concise scientific view, `Select all` exposes the complete schema and `Clear`
removes all columns. The table remains row-bounded regardless of the selection.
Displayed rows can be downloaded as TSV; analytical comma-separated outputs are
not produced.

## Three interchangeable result-source modes

Choose exactly one E3 result source.

| Mode | Option | Intended use |
|---|---|---|
| Integrated DuckDB | `--resource_duckdb_path` | Production default; candidate summaries plus all detailed one-to-many evidence |
| Candidate master Parquet | `--resource_parquet_path` | One-file candidate-level hand-off requested by the project lead |
| Workflow run directory | `--resource_run_dir` | Compatibility mode while stage outputs still exist as many Parquets |

In run-directory mode the app discovers non-superseded `*.parquet` files,
assigns canonical relation names and registers lazy views in a temporary
in-memory DuckDB. It never rewrites the workflow result.

The single master Parquet is deliberately one row per candidate group. It
contains the final ranking, additional pre-structure fields, all prefixed
discovery evidence and useful detail counts. Protein members, multiple pockets,
domain hits and residue pairs remain normalised relations in the integrated
DuckDB because flattening them into one row would either duplicate candidates or
lose evidence.

## Start the app

### Recommended integrated DuckDB

```bash
./run_app.sh \
  --resource_duckdb_path /path/to/10_integrated_resource/duckdb/e3_integrated_resource.duckdb \
  --expression_duckdb_path /path/to/e3_expression.duckdb \
  --max_table_rows 1000 \
  --host 127.0.0.1 \
  --port 3838
```

### One master Parquet

```bash
./run_app.sh \
  --resource_parquet_path /path/to/e3_candidate_master_results.parquet \
  --max_table_rows 1000 \
  --host 127.0.0.1 \
  --port 3838
```

### Current multi-Parquet workflow run

```bash
./run_app.sh \
  --resource_run_dir /path/to/completed_workflow_run \
  --max_table_rows 1000 \
  --host 127.0.0.1 \
  --port 3838
```

Equivalent environment variables are:

- `E3_RESOURCE_DUCKDB`
- `E3_RESOURCE_PARQUET`
- `E3_RESOURCE_RUN_DIR`
- `E3_EXPRESSION_DUCKDB`
- `E3_MAX_TABLE_ROWS`
- `E3_SHINY_HOST`
- `E3_SHINY_PORT`

The raw Expression Atlas summary/table/lookup/plot tabs use the optional
expression DuckDB. The integrated Expression evidence section uses the selected
E3 result source.

## Dependencies and tests

```bash
conda install -c conda-forge \
  r-base r-shiny r-bslib r-dplyr r-dt r-ggplot2 r-plotly \
  r-rlang r-shinycssloaders r-stringr r-tibble r-testthat \
  r-duckdb r-duckplyr

Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The test suite covers source selection, run-directory discovery, lazy Parquet
registration, section classification, selected-column SQL, grant-overview
queries, module UI contracts and the retained Expression Atlas functionality.

## Interpretation boundary

OrthoFinder grouping, sequence conservation, domain annotation, expression,
AlphaFold confidence, predicted pockets and structural alignment are
computational evidence. They do not establish E3 activity, compound binding,
selectivity or induced target degradation. Human structural, biological and
chemistry review remains required.
