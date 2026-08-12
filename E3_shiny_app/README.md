# ARIA plant E3 Shiny reporter

Version 0.10.5 is the grant-focused R reporter for the end-to-end workflow. It is a
read-only consumer: scientific transformations happen in the workflow packages,
while Shiny sends bounded lazy queries to DuckDB through duckplyr.

## Questions the reporter answers

The main sections follow the evidence path required by the grant:

1. **Grant overview** – authoritative evolutionary-group counts rather than
   earlier DeepClust evidence-row counts.
2. **Workflow schematic** – the complete evidence path from controlled inputs
   through DeepClust and OrthoFinder, domains and expression, pocket and 3D
   evidence, integrated scoring, group consolidation and app-ready reporting.
3. **Glossary** – project-wide technical terms plus the complete 218-field
   final-candidate data dictionary, plain-language definitions, units,
   interpretation cautions, gates, thresholds and result labels.
4. **Threshold explorer** – separate pre-structure and structurally informed
   sensitivity-analysis lists, using sliders and exact typed values while the
   primary grant-aligned result remains unchanged.
5. **Visual explorer** – a selectable multi-axis candidate landscape linked to
   the exact evidence tables, a cross-species expression heatmap and every
   available species-by-tissue Expression Atlas profile for the selected group.
   The volcano view remains inactive unless a real differential-expression
   relation supplies both effect sizes and P/FDR/Q values.
6. **Final recommendations** – the ordered top-50 review shortlist, strict
   grant-aligned predictions, named gate-sensitivity scenarios, group-level
   scorecard, DeepClust contributors, representative audit and explicit
   exclusion reasons. A focused slider varies only the final inclusive
   all-members druggability threshold while preserving the recorded 0.50 result,
   with member-level box plots for lead clusters reaching that last gate,
   followed by the full methods-style account of score construction, unavailable
   denominators, effective weights and tie-breaks.
7. **Candidates** – combined discovery, conservation, domain, expression and
   structural prioritisation, with inclusion, exclusion and missing-evidence
   reasons.
8. **Orthology** – explicit OrthoFinder orthogroup and hierarchical-group IDs,
   species membership, member accessions and candidate-relevant sequences.
9. **Domains** – catalogued E3-associated domain support and explicit annotation
   unavailable states.
10. **Expression evidence** – identifier mapping and broad Expression Atlas
   support without treating unavailable resources as biological negatives;
   workflow v0.13.0 resources also retain tissue/organism part, developmental
   stage, condition, treatment, experiment and sample context. Direct controls
   open the matching heatmap and volcano-eligibility views.
11. **Ligandability** – selected fpocket/P2Rank-supported pockets, structure
   availability, pLDDT and mapping quality.
12. **Pocket conservation** – conserved pocket-bearing alignment regions and
   validated pocket-residue-to-FASTA coordinates.
13. **3D alignment** – separate US-align/TM-align conclusions for equivalent 3D
   pocket position and stronger local pocket-structure conservation, with an
   interactive TM-score/pocket-overlap evidence map and recorded threshold
   references.
14. **3D structures & pockets** – selected-group, rotatable member structures
    with strict and top-k pocket residues highlighted.
15. **Pocket-aligned sequences** – the published MAFFT alignment, exact pocket
    highlights and the original OrthoFinder-group member sequence identifiers.
16. **Provenance and QC** – release metadata, relation catalogue and source paths.
17. **Computational chemistry** – chemistry hand-off decisions, review tiers,
    sensitivity analysis, residue-derived pharmacophore features and optional
    fragment-ranking evidence.

Every section has its own checkbox column selector. `Grant defaults` restores a
concise scientific view, `Select all` exposes the complete schema and `Clear`
removes all columns. The table remains row-bounded regardless of the selection.
Displayed rows can be downloaded as either TSV or a formatted Excel workbook;
analytical comma-separated outputs are not produced. Each Excel download uses
the exact same bounded rows and selected columns as its neighbouring TSV. It
opens as a filterable, banded table with a frozen header, readable bounded
column widths, visible gridlines and explicit borders, centred body values,
10-point wrapped narrative text, capped long-text row heights and
data-appropriate numeric formats. Numeric
source values remain exact; only their display is shortened. The **All results**
browser includes the same paired downloads.

Wide in-app tables now use a horizontal scrollbar and a bounded vertical body,
so the header remains stationary while rows scroll. Numeric display is limited
to three decimal places, or three significant figures for P/E/FDR/Q values,
without changing the underlying data or downloads. Identifier and narrative
columns receive deliberate wider widths instead of being squeezed into the
visible page.

The Glossary opens with the complete glossary in one vertically scrollable
browser table. Its section selector remains available for shorter focused
views; the download buttons are optional exports rather than the only way to
read the full dictionary.

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

The explorer now calculates two matched lists at the same time. The
**Pre-structure candidate list** applies the target-species,
mandatory-species, E3-domain and expression gates. The **Structurally informed
candidate list** applies those same gates plus the selected pocket conservation,
mapping, structural coverage, member druggability and strict 3D requirements.
There is no hidden mode switch, and moving a structural control affects only
the second table. Each list has its own TSV and formatted Excel downloads.

A multiple-selection control can optionally add post-hoc
gates for recorded aggregate scores such as evidence completeness, mean pocket
pLDDT support, predictor agreement, pocket-region overlap, cross-aligner
TM-score, 3D pocket overlap and structural chemical-group conservation. Those
additional gates are off by default and never rerun the underlying scientific
calculations.

“Minimum domain-supported assessed-species fraction” uses only species for
which a usable domain annotation was available as its denominator. At the 0.80
default, at least 80% of those assessed species must support a catalogued
E3-associated domain. Unassessed species are reported separately; they are not
silently counted as domain failures or passes. The explorer shows this
definition directly below the slider.

The structurally informed list also defaults to requiring a conserved pocket-bearing
sequence region, acceptable mapping in every assessed member and a strictly
conserved corresponding 3D pocket. The displayed druggability value is the
minimum across assessed members, so moving that slider directly re-evaluates the
all-member druggability requirement. `Reset current defaults` restores these
values. The app labels groups outside the 200-group structural
analysis as `NOT_STRUCTURALLY_ASSESSED`; it never turns missing assessment into a
structural failure or pass.

`PASS` means that every gate for that table is met. `NEAR_MISS` means that one
conceptual gate is not met. Each exported TSV includes the selected numeric
thresholds in every row; its companion Excel download contains the same data,
so either exploratory list remains interpretable after it leaves the app.
Slider-generated results are sensitivity analyses and do not replace the
locked primary analysis.

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

The retired raw Expression Atlas sidebar and its four legacy tabs are no longer
part of the application. Candidate-level and tissue-context expression evidence
is read from the integrated E3 result source. In workflow v0.13.0 resources, the normalised
`candidate_expression_context_summary` relation supports tissue and context
columns. Older resources remain readable but cannot reconstruct tissue after
the fact; they explicitly label `NOT_MAPPED` zero counts as missing mapping,
not biological zero expression.

## Linked visual explorer

The Visual explorer uses the definitive one-row-per-evolutionary-group relation
when it is available. Its candidate landscape can map any two documented scores
to the axes and optional evidence/status fields to point colour and size. A
clicked point updates the selected candidate, its exact supporting relation and
the expression views.

The Expression heatmap aggregates no more than 25 selected groups at a time and
keeps TPM and FPKM separate. The Species & tissue expression tab links the same
candidate to every available tissue/organism-part context, faceted by species,
with the exact underlying Expression Atlas rows available as a TSV. Missing
mapped contexts remain blank or explicitly unavailable; they are never plotted
as measured zero.

The Volcano eligibility tab deliberately does not invent fold changes or
significance from absolute expression values. It activates automatically only
when a future integrated relation contains both a recognised log-fold-change
field and a recognised P-value, adjusted-P, FDR or Q-value field.

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

The viewer's **Fit and centre** control restores its default orientation and
auto-fit zoom, then displays a confirmation. The app also upgrades the former
zoom-only **Fit structure** action when an older portable report is loaded.

## Ranking formulas and weighting sensitivity

The Computational recommendations section now places a pointer above its main
table and a detailed ranking-methodology section below it. That section records
the discovery, orthology, domain, expression, pre-structure, ligandability,
pocket-conservation, structural and final-score equations, including the
production default weights, neutral handling of unavailable assessed
denominators, deterministic tie-breaks and evolutionary-group consolidation.

A focused final-gate card on the same page varies only the minimum-member
druggability requirement. It starts at the recorded inclusive threshold of
`minimum_druggability_score >= 0.50`, keeps every other recorded gate fixed and
shows the altered passing list, recorded-versus-selected counts, and groups
entering or leaving the strict intersection. The authoritative table above it
is never rewritten. Sensitivity lists can be downloaded as paired TSV and Excel
files with the selected threshold retained in every row.

Horizontal box plots on the same card show the retained selected-pocket score
distribution for assessed members in every lead cluster that passes all other
fixed final gates. Member points are overlaid on a shared zero-to-one axis and
the dashed reference line follows the selected slider threshold.

An expandable weighting-sensitivity explorer exposes the recorded defaults as
sliders. It normalises the selected weights within each score layer, optionally
retains the recorded hard-gate tier and can apply a separately labelled 3D
refinement weight. Its table and paired TSV/Excel downloads are explicitly
non-authoritative: they recompute a bounded what-if ranking from stored values
and never alter the official ranks, mandatory gates, DuckDB or pipeline output.

## Dependencies and tests

```bash
conda install -c conda-forge \
  r-base r-shiny r-bslib r-dplyr r-dt r-ggplot2 r-htmltools r-plotly \
  r-openxlsx r-rlang r-shinycssloaders r-stringr r-tibble r-testthat \
  r-duckdb r-duckplyr

Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The test suite covers source selection, run-directory discovery, lazy Parquet
registration, section classification, group-level grant-overview counts,
threshold validation and SQL, focused final-gate boundary behaviour and
entrant/leaver comparison, member-level druggability box plots, formatted Excel
export contracts, druggability near-miss reclassification, linked
candidate/expression visual queries, module UI contracts, portable pocket-review
validation, repaired fit-and-centre controls, selected-group sequence/model
identifiers and the retained
Expression Atlas functionality.

The complete cluster-build, external-drive transfer and local launch procedure
is in `PORTABLE_VISUALISATION_RUNBOOK_v0_6_0.md`.

## Interpretation boundary

OrthoFinder grouping, sequence conservation, domain annotation, expression,
AlphaFold confidence, predicted pockets and structural alignment are
computational evidence. They do not establish E3 activity, compound binding,
selectivity or induced target degradation. Human structural, biological and
chemistry review remains required.
