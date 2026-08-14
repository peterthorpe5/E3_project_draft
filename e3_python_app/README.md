# ARIA plant E3 Python reporter

Version 0.10.1 is the Streamlit companion to `E3_shiny_app` 0.13.1. Both
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
- focused Candidates, Domains, Expression, Ligandability, Pocket conservation
  and 3D alignment sections. Expression embeds the same heatmap and
  scientifically gated volcano views as the Visual explorer;
- an expanded Orthology section reporting membership-sequence, species,
  group, E3-seeded-group, all-species-group and largest-group metrics; exact
  multi-species, breadth, seed-evidence and curated taxonomy-role filters; and
  a full group-size distribution that explicitly retains one-species groups,
  with independently selectable linear/logarithmic x and y axes. Its grouping
  selector distinguishes recommended root-level phylogenetic hierarchical
  orthogroups (`N0.HOG…`) from the broader original MCL orthogroups (`OG…`);
- separate lazy-loaded **Human HOGs** and **Plant & human HOGs** views. The
  first retains every root-level `N0.HOG…` containing `Homo_sapiens`; the
  second requires both a human member and at least one of the 12 curated target
  plant species. Both expose one-row-per-HOG composition and candidate-ranking
  annotations, all human sequence identifiers, every co-member, available gene
  aliases and candidate-linked protein sequences, with TSV, formatted Excel
  and available-sequence FASTA downloads. A HOG absent from candidate ranking
  is explicitly `NOT_IN_CANDIDATE_RANKING`, not a biological failure;
- a scientifically separate DeepClust and 1KP sequence-neighbourhood panel,
  using the full 1KP+ candidate-evidence summaries for raw/strict member,
  sample and parsed-species coverage, inherited-seed filters, optional links to
  reconciled evolutionary groups, a log-switchable coverage graph and TSV/Excel
  downloads without relabelling sequence clusters as orthology;
- a separate Seed & HOG explorer supporting one or several inherited E3 seed
  identifiers, Any/All matching, matching-group summaries for the selected
  phylogenetic or legacy grouping, member-table species filters, associated
  evidence, and filtered member protein FASTA export;
- species, tissue/organism-part and identifier filters for the normalised
  candidate-by-expression-context relation, when supplied by workflow v0.13.0
  or later;
- a separate Threshold explorer with the completed analysis defaults, paired
  sliders and typed values, simultaneously displayed pre-structure and
  structurally informed candidate lists, explicit `PASS`, `NEAR_MISS`, `FAIL`
  and `NOT_STRUCTURALLY_ASSESSED` labels, expanded candidate evidence plus
  separate TSV and formatted Excel exports for both lists;
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
  review bundle. Current report pages download the rotated 3D canvas and the
  complete alignment directly as PDFs; 0.9.0 upgrades legacy report pages in
  memory with the same controls, and the alignment tab also downloads the
  selected published MAFFT alignment as FASTA;
- searchable HOG/orthogroup, DeepClust cluster, rank and accession choices,
  alongside downloadable OrthoFinder member sequence/model identifiers;
- a separate column multiselect and row limit for every section;
- a replacement complete-resource search accepting one item or a pasted
  newline/comma/semicolon/tab list. Smart, exact and literal-contains modes
  recognise names, root HOG IDs, legacy OG IDs, E3 seeds, accessions, entries,
  genes and DeepClust identifiers; every hit retains the input term, relation,
  matched fields and all source columns, with TSV and Excel downloads;
- a schema-agnostic all-results browser with paired TSV and Excel downloads;
- provenance and QC views; and
- on-demand vector-PDF downloads for every native application graph. These use
  the packaged Kaleido renderer and are prepared only when requested; and
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

Directly above that list, horizontal box plots show retained selected-pocket
scores for assessed members. A searchable selector lists every structurally
assessed group with member-level scores and defaults to the highest-ranked group
reaching the last gate. The selected-group summary reports its evolutionary-
group ID, lead cluster, assessed-member count, minimum score and complete status
at the slider threshold. An **All groups reaching the last gate** option retains
the ranked comparison view, bounded to 30 groups for readable plotting.
Individual member points remain visible, the shared axis is fixed from zero to
one, and the dashed threshold line moves with the slider.

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

The v0.10.1 quality gate includes focused human-HOG, plant–human-HOG,
HOG-level human/Arabidopsis representative and
multi-field list-search tests in addition to branch-aware coverage at or above 95%
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

Pocket-review bundles generated by structural-alignment v0.4.0 add direct
**Download current view PDF** and **Download alignment PDF** controls. The app
also injects these offline controls into compatible legacy group pages at read
time, without changing the source bundle. Native
app plots use `kaleido>=0.2.1,<1`, which is installed with the declared Python
dependencies.

The structure control is labelled **Fit and centre**. It restores the default
orientation and auto-fit zoom and displays a confirmation, including for older
portable pages upgraded in memory by this app.

## Interpretation boundary

These are computational recommendations. OrthoFinder membership, E3-domain
support, RNA expression, predicted cavities, pocket-region conservation and
US-align/TM-align agreement do not prove E3 activity, compound binding or
induced degradation.
