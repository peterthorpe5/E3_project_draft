# ARIA plant E3 Python reporter

Version 0.7.4 is the tested Streamlit companion to `E3_shiny_app` 0.10.3. Both
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

- a responsive Workflow schematic tracing the complete method from validated
  inputs through sequence discovery, OrthoFinder reconciliation, biological
  evidence, structure and pocket analysis, 3D comparison, integrated ranking
  and app-ready recommendations;
- a searchable, substantially expanded Glossary combining project-wide
  technical terms with the complete 218-field final-candidate data dictionary,
  recorded gates, thresholds, result labels and interpretation cautions;
- a dedicated Computational recommendations view containing the ordered top-50 review
  shortlist, strict grant-aligned predictions, named gate-sensitivity
  scenarios, evolutionary-group scorecard, contributors, representative audit
  and exclusion reasons. A focused final-gate slider varies only the inclusive
  all-members druggability threshold while preserving the recorded 0.50 result,
  with member-level box plots for every lead cluster reaching that last gate,
  followed by a full methods-style explanation of every recorded score,
  missing-data rule, effective weight and deterministic tie-break;
- a grant overview separating Milestone 1 conservation evidence from Milestone
  2 conserved structural/chemical starting space;
- focused Candidates, Orthology, Domains, Expression, Ligandability, Pocket
  conservation and 3D alignment sections. Expression embeds the same heatmap
  and scientifically gated volcano views as the Visual explorer;
- species, tissue/organism-part and identifier filters for the normalised
  candidate-by-expression-context relation, when supplied by workflow v0.13.0
  or later;
- a separate Threshold explorer with the completed analysis defaults, paired
  sliders and typed values, pre-structure and structurally informed modes,
  explicit `PASS`, `NEAR_MISS`, `FAIL` and `NOT_STRUCTURALLY_ASSESSED` labels,
  expanded candidate evidence plus TSV and formatted Excel export;
- a linked Visual explorer containing a selectable multi-axis candidate
  landscape, a cross-species expression heatmap, exact species-by-tissue
  profiles and the bounded evidence tables behind every selected candidate;
- a scientifically gated Volcano eligibility view, which activates only when a
  relation contains both a recognised differential-expression effect size and
  a P/FDR/Q-value field; the current absolute Expression Atlas release is not
  misrepresented as a differential analysis;
- an interactive 3D-alignment evidence map with hover, zoom and threshold
  references, plus selected-group rotatable structure/pocket and
  pocket-annotated MAFFT alignment tabs backed by the self-contained top-200
  review bundle;
- searchable HOG/orthogroup, DeepClust cluster, rank and accession choices,
  alongside downloadable OrthoFinder member sequence/model identifiers;
- a separate column multiselect and row limit for every section;
- exact accession search across recognised scalar and semicolon-delimited
  candidate/member fields;
- a schema-agnostic all-results browser with paired TSV and Excel downloads;
- provenance and QC views; and
- paired TSV and formatted Excel downloads of every downloadable result table.
  Excel contains the same bounded rows and selected columns, with visible cell
  gridlines, explicit borders, filter arrows, frozen headers, banded rows,
  centred body values, 10-point wrapped narrative text, bounded readable widths
  and capped long-text row heights, plus data-appropriate display formats.
  Numeric source values remain exact;
  only their display is shortened.

Wide in-app result tables give every column an explicit readable minimum width,
then use a horizontal scrollbar and a bounded vertical viewport with a
stationary header. Numeric display is shortened to three
decimal places (or three significant figures for P/E/FDR/Q values) without
changing the exported data. The main navigation labels wrap across as many rows
as the window requires, so sections are visible without tab-scroll arrows.

The Computational recommendations view points readers from the top of the page
to a detailed methodology below the authoritative table. The explanation
records every discovery, orthology, domain, expression, pre-structure,
ligandability, pocket-conservation, structural and final-score equation,
including production defaults, neutral unavailable-denominator handling,
hard-gate separation, tie-breaks and evolutionary-group consolidation. An
expandable slider panel normalises alternative weights within each layer and
can download an explicitly non-authoritative what-if ranking as TSV or Excel.
It never changes the recorded rank, mandatory gates, database or pipeline.

The same page includes a focused final-gate sensitivity card. Its slider starts
at the recorded inclusive rule, `minimum_druggability_score >= 0.50`, and changes
only that one requirement while every other recorded gate remains fixed. The
app shows the selected passing list, recorded-versus-selected counts, and groups
entering or leaving the strict intersection. The source authority and recorded
recommendation table are unchanged, and the sensitivity list can be downloaded
as paired TSV and Excel files.

Directly above that list, horizontal box plots show the retained selected-pocket
scores for assessed members in each lead cluster that passes every other final
gate. Individual member points remain visible, the shared axis is fixed from
zero to one, and the dashed threshold line moves with the slider.

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

The v0.7.4 quality gate includes branch-aware coverage at or above 95%
of DuckDB, master-Parquet, run-directory, glossary, expression-context,
visualisation, threshold, portable-review, Excel export and headless Streamlit
behaviour.

Legacy resources without `candidate_expression_context_summary` remain
readable. The Expression tab then shows the older candidate summary plus a
warning that zero count fields on `NOT_MAPPED` rows mean absent mapping, not
measured zero expression.

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

The structure control is labelled **Fit and centre**. It restores the default
orientation and auto-fit zoom and displays a confirmation, including for older
portable pages upgraded in memory by this app.

## Interpretation boundary

These are computational recommendations. OrthoFinder membership, E3-domain
support, RNA expression, predicted cavities, pocket-region conservation and
US-align/TM-align agreement do not prove E3 activity, compound binding or
induced degradation.
