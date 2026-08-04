# ARIA plant E3 Shiny reporter

Version 0.8.0 is the grant-focused R reporter for the PT_E3_8 workflow. It is a
read-only consumer: scientific transformations happen in the workflow packages,
while Shiny sends bounded lazy queries to DuckDB through duckplyr.

## Questions the reporter answers

The main sections follow the evidence path required by the grant:

1. **Grant overview** – authoritative evolutionary-group counts rather than
   earlier DeepClust evidence-row counts.
2. **Glossary** – plain-language definitions for seeds, evolutionary groups,
   gates, strict predictions, assessed denominators, thresholds and result
   labels.
3. **Threshold explorer** – separate pre-structure and structurally informed
   sensitivity-analysis lists, using sliders and exact typed values while the
   primary grant-aligned result remains unchanged.
4. **Final recommendations** – the ordered top-50 review shortlist, strict
   grant-aligned predictions, named gate-sensitivity scenarios, group-level
   scorecard, DeepClust contributors, representative audit and explicit
   exclusion reasons.
5. **Candidates** – combined discovery, conservation, domain, expression and
   structural prioritisation, with inclusion, exclusion and missing-evidence
   reasons.
6. **Orthology** – explicit OrthoFinder orthogroup and hierarchical-group IDs,
   species membership, member accessions and candidate-relevant sequences.
7. **Domains** – catalogued E3-associated domain support and explicit annotation
   unavailable states.
8. **Expression evidence** – identifier mapping and broad Expression Atlas
   support without treating unavailable resources as biological negatives;
   workflow v0.13.0 resources also retain tissue/organism part, developmental
   stage, condition, treatment, experiment and sample context.
9. **Ligandability** – selected fpocket/P2Rank-supported pockets, structure
   availability, pLDDT and mapping quality.
10. **Pocket conservation** – conserved pocket-bearing alignment regions and
   validated pocket-residue-to-FASTA coordinates.
11. **3D alignment** – separate US-align/TM-align conclusions for equivalent 3D
   pocket position and stronger local pocket-structure conservation.
12. **3D structures & pockets** – selected-group, rotatable member structures
    with strict and top-k pocket residues highlighted.
13. **Pocket-aligned sequences** – the published MAFFT alignment, exact pocket
    highlights and the original OrthoFinder-group member sequence identifiers.
14. **Provenance and QC** – release metadata, relation catalogue and source paths.

Every section has its own checkbox column selector. `Grant defaults` restores a
concise scientific view, `Select all` exposes the complete schema and `Clear`
removes all columns. The table remains row-bounded regardless of the selection.
Displayed rows can be downloaded as TSV; analytical comma-separated outputs are
not produced.

## Threshold explorer

The threshold explorer always starts from the current primary-analysis values:

| Gate | Default |
|---|---:|
| Minimum target-species fraction | 0.90 |
| Minimum mandatory-species fraction | 1.00 |
| Minimum domain-supported assessed-species fraction | 0.80 |
| Minimum expression-supported assessed-species fraction | 0.80 |
| Minimum structurally supported species fraction | 0.75 |
| Minimum member druggability score | 0.50 |

“Minimum domain-supported assessed-species fraction” uses only species for
which a usable domain annotation was available as its denominator. At the 0.80
default, at least 80% of those assessed species must support a catalogued
E3-associated domain. Unassessed species are reported separately; they are not
silently counted as domain failures or passes. The explorer shows this
definition directly below the slider.

The structural view also defaults to requiring a conserved pocket-bearing
sequence region, acceptable mapping in every assessed member and a strictly
conserved corresponding 3D pocket. The displayed druggability value is the
minimum across assessed members, so moving that slider directly re-evaluates the
all-member druggability requirement. `Reset current defaults` restores these
values. The app labels groups outside the 200-group structural
analysis as `NOT_STRUCTURALLY_ASSESSED`; it never turns missing assessment into a
structural failure or pass.

`PASS` means that every selected gate is met. `NEAR_MISS` means that one
conceptual gate is not met. The exported TSV includes the selected numeric
thresholds in every row, so an exploratory list remains interpretable after it
leaves the app. Slider-generated results are sensitivity analyses and do not
replace the locked primary analysis.

## Three interchangeable result-source modes

Choose exactly one E3 result source.

| Mode | Option | Intended use |
|---|---|---|
| Integrated DuckDB | `--resource_duckdb_path` | Production default; candidate summaries plus all detailed one-to-many evidence |
| Candidate master Parquet | `--resource_parquet_path` | Portable cluster-level compatibility hand-off |
| Workflow run directory | `--resource_run_dir` | Compatibility mode while stage outputs still exist as many Parquets |

In run-directory mode the app discovers non-superseded `*.parquet` files,
assigns canonical relation names and registers lazy views in a temporary
in-memory DuckDB. It never rewrites the workflow result.

The single master Parquet is deliberately one row per candidate/DeepClust
cluster. It contains prioritisation, additional pre-structure fields, prefixed
discovery evidence and useful detail counts. The definitive
one-row-per-evolutionary-group table is
`final_results/final_evolutionary_candidate_prioritisation.parquet`, available
through integrated-DuckDB and run-directory modes. Protein members, multiple
pockets, domain hits and residue pairs remain normalised relations in the
integrated DuckDB because flattening them into one row would either duplicate
records or lose evidence.

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
- `E3_POCKET_REVIEW_DIR`
- `E3_EXPRESSION_DUCKDB`
- `E3_MAX_TABLE_ROWS`
- `E3_SHINY_HOST`
- `E3_SHINY_PORT`

The raw Expression Atlas summary/table/lookup/plot tabs use the optional
expression DuckDB. The integrated Expression evidence section uses the selected
E3 result source. In workflow v0.13.0 resources, the normalised
`candidate_expression_context_summary` relation supports tissue and context
columns. Older resources remain readable but cannot reconstruct tissue after
the fact; they explicitly label `NOT_MAPPED` zero counts as missing mapping,
not biological zero expression.

## Portable 3D and alignment review

The integrated DuckDB stores structural evidence, residue mappings and original
provenance paths, but it does not embed the model coordinates required by a
browser viewer. The optional pocket-review bundle is therefore copied beside
the DuckDB as a self-contained asset directory. It contains compact C-alpha
coordinates, pocket annotations, published alignments, exact coordinate maps,
member sequence identifiers, checksums and offline HTML/JavaScript.

Configure it explicitly:

```bash
./run_app.sh \
  --resource_duckdb_path /path/to/portable_release/e3_integrated_resource.duckdb \
  --pocket_review_dir /path/to/portable_release/pocket_review \
  --expression_duckdb_path "" \
  --max_table_rows 1000 \
  --host 127.0.0.1 \
  --port 3838
```

If exactly one valid directory beginning with `pocket_review` is beside the
DuckDB, the app discovers it automatically. An explicit path is preferred when
several review bundles are retained. The two review tabs remain visible when no
bundle is configured, but show a clear setup message rather than failing the
whole app.

The embedded 3D view is a rotatable C-alpha trace with mapped pocket residues,
not an atomistic surface or docking result. It can switch between group members
and pocket ranks. The sequence view retains members without structure or pocket
evidence as explicit unassessed records.

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
registration, section classification, group-level grant-overview counts,
threshold validation and SQL, druggability near-miss reclassification, module UI
contracts, portable pocket-review validation, selected-group sequence/model
identifiers and the retained Expression Atlas functionality.

The complete cluster-build, external-drive transfer and local launch procedure
is in `PORTABLE_VISUALISATION_RUNBOOK_v0_6_0.md`.

## Interpretation boundary

OrthoFinder grouping, sequence conservation, domain annotation, expression,
AlphaFold confidence, predicted pockets and structural alignment are
computational evidence. They do not establish E3 activity, compound binding,
selectivity or induced target degradation. Human structural, biological and
chemistry review remains required.
