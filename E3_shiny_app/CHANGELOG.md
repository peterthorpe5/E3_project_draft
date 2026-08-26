# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.18.0

<!-- source: RELEASE_NOTES_v0_18_0.md; sha256: 30e687e824e996b2783b6da2fa3db0ebf66bbf0e2e9a490603fc0b8e5e2b71ad -->

### Decision-ready complete results

The enriched HOG overview now puts the following evidence near the front of
the selectable column list:

- the recorded 3D pocket-position and 3D alignment statuses;
- separate nullable flags for same-position support and the stricter conserved
  3D pocket result;
- minimum assessed-member druggability and the all-assessed-members gate; and
- structural coverage, TM-score, overlap, centroid-distance, residue-match and
  chemical-group-conservation summaries.

The enriched member table joins a deterministic strict selected-pocket row
where available and exposes its pocket number, druggability, mapping,
confidence, predictor agreement and evidence status. Missing joined evidence
is labelled unassessed rather than converted to a zero score. Same-position
support is explicitly not presented as proof of conserved pocket chemistry.

Human, Arabidopsis, rice and barley representatives, identifiers and member
counts are now separated throughout the HOG and threshold reporting views.

### Search, expression and heatmaps

- Unified-search matches provide first-18, select-all and clear controls. The
  table and TSV/Excel downloads use exactly the selected fields.
- Expression filtering accepts one identifier or up to 50 unique values pasted
  with semicolon, comma, tab or newline separators. The filtered values can be
  downloaded directly as TSV or Excel.
- Expression heatmaps now encode low values as white and high values as red.

### Seed-catalogue portability repair

Seed metadata JSON is decoded defensively in R after collection, avoiding
DuckDB's optional JSON extension and its network-dependent autoload path.
Pasted seed terms are split consistently on semicolons, commas, tabs and new
lines. `jsonlite` is now an explicit runtime dependency.

### Scientific-method annotation retained

The v0.17.0 threshold and method annotations remain unchanged, including the
Xu and Zhang (2010) reference for TM-score 0.50 as an established approximate
fold/topology boundary. The annotation continues to state that this global
fold threshold does not by itself establish pocket equivalence.

No scientific pipeline output, stored threshold or authoritative ranking is
rewritten by this reporter release.

### Release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

## v0.17.0

<!-- source: RELEASE_NOTES_v0_17_0.md; sha256: d9c302488feb4f16da2e0ee7444f04e0b8a76a539b644b7dd9859ab21b1115a8 -->

### Expanded operating help

Every primary tab retains its collapsed **❓ How to use this tab** panel. Each
entry now has a separate **What this tab yields** paragraph identifying the
tables, plots, evidence rows and downloads produced by that page.

### Recorded methods and thresholds

Fourteen scientific tabs now include a separate collapsed **ⓘ Methods and
thresholds** panel. The annotations cover the recorded grant-aligned gates,
ranking weights, OrthoFinder grouping, domain and expression denominators,
AlphaFold Database retrieval and QC, FPocket/P2Rank pocket selection, MAFFT
pocket-region analysis, US-align/TM-align 3D comparison and preliminary
chemistry hand-off.

The structural annotations explicitly record:

- a whole-model AlphaFold QC flag at 0.50 of residues with pLDDT at least 70,
  explicitly distinguished from downstream pocket-local selection;
- pocket mapping 0.95, pocket pLDDT fraction 0.70 and druggability 0.50;
- TM-score 0.50, centroid distance 8 Angstrom and 3D pocket overlap 0.50;
- local residue match 0.50, chemical-group conservation 0.60 and group support
  0.75, with both structural aligners agreeing; and
- the distinction between strict rank-one results and top-five pocket
  sensitivity evidence.

The 3D-alignment panel links to Xu and Zhang (2010), which supports TM-score
0.50 as an approximate fold/topology boundary. It also states that this global
fold threshold does not establish pocket equivalence.

No scientific calculation, threshold, ranking or source resource is changed by
this release.

### Release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

Any actual dependency, parse, functional or test failure blocks release.

## v0.16.0

<!-- source: RELEASE_NOTES_v0_16_0.md; sha256: 6f48b481cb9bdcfbe34d57f2d5ef186de914773103ee123676ad3c1499e103b9 -->

### Independent structural-review shortlist

The dedicated shortlist now answers the computational team's intended
question: which root-level HOGs should be considered for newly performed
structural analysis? It returns 200 HOGs by default, can expand to 500 and uses
the authoritative rank built from discovery, orthology/species, E3-domain and
expression evidence. Requiring the recorded pre-structure pass is optional.

Existing models, pockets, druggability, mapping, alignment, conservation and 3D
results are neither selected nor displayed in this table. They are preserved in
the other application tabs.

### Richer Threshold explorer

The paired pre-structure and structurally informed result tables now retain
many more available source fields and add root-HOG membership context. This
includes human and Arabidopsis representatives and identifiers, member/species
counts and lists, orthogroup and parent-clade links, review/mapping summaries,
ranks, seed evidence, domain/expression availability, inclusion/exclusion
reasons and explicit missing evidence. The same columns are retained in TSV and
formatted Excel downloads.

### E3 seed catalogue

A new tab searches one or several inherited seed identifiers, names or
annotation terms and downloads the result as TSV or formatted Excel. Exact
`known_e3_seeds` rows and provenance are preferred when the loaded release
contains that authority. Older releases use a clearly labelled
cluster-associated fallback rather than inventing per-seed annotations.

Available accession-matched protein sequences can be downloaded as FASTA. The
sequence reconciliation inspects every sequence-bearing HOG member because the
`is_input_candidate` field is not a seed flag. The catalogue has a dedicated
hard cap of 100,000 rows so a complete controlled seed set can be requested
without removing query bounds.

### Release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Any actual failure blocks release.

## v0.15.0

<!-- source: RELEASE_NOTES_v0_15_0.md; sha256: 9d3c508b46d3048e3caa9f470968ae71689feff3ddb384157d5f17456c252287 -->

### Complete enriched HOG results

The **All results** tab now defaults to an enriched one-row-per-root-HOG result.
Its first selectable fields are HOG ID, canonical pre-structure and
post-structure ranks, human representatives and Arabidopsis representatives.
It also exposes membership/species summaries and every original field from the
strongest available HOG-linked ranking relation.

A separate member-detail result includes every source
`hierarchical_membership` field under an explicit `member_` name and repeats the
complete HOG-level ranking and representative context. Membership-only and
ranking-only HOGs remain visible and carry explicit source-availability flags.

The original raw DuckDB relations are unchanged and remain selectable for exact
source audit. The UI explains whether **Select all fields** refers to an
enriched joined result or one raw relation, and both routes preserve bounded TSV
and formatted Excel downloads.

Run the complete release gate before publishing:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Any actual failure blocks release.

## v0.14.0

<!-- source: RELEASE_NOTES_v0_14_0.md; sha256: 3dcbabcd20d4b3e15dfe65fba12c787cef1882d67c9d80dbeaeb08ff02dbb590 -->

### Direct pre-structure top-N HOG list

The new **Pre-structure ranked HOGs** tab provides the team's requested ungated
top-200 analysis set directly. It selects one row per root-level `N0.HOG…` by
the authoritative recorded `prestructure_evolutionary_group_rank`, or the
equivalent `evolutionary_group_rank` when that is the published field. It does
not accept the distinct cluster-level `computational_rank` and applies no
target-species, mandatory-species, domain, expression, pocket, druggability or
structural gate.

The count is adjustable within the global row cap. A literal search filters
only within the selected top-N rows and never recalculates their ranks. The
display and paired TSV/Excel downloads retain all source annotations plus
available human and Arabidopsis HOG representatives.

### Contextual tab help

All 25 top-level tabs now begin with a collapsed **❓ How to use this tab** box.
Each entry explains the principal controls, evidence boundary and a relevant
interpretation caution. The shared catalogue and UI coverage are tested so new
tabs must deliberately add their own guidance.

### Defensive behaviour and validation

The new module reports unavailable rank fields and query errors in the UI
without inventing a fallback biological result. Focused tests cover source
selection, query bounds, root-HOG filtering, absence of gate filtering,
representative annotation, retained recorded ranks, summary edge cases,
downloads and complete help coverage.

Run the complete release gate before publishing:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when the R session does not
provide a `--file` argument. Any actual failure blocks release.

## v0.13.1

<!-- source: RELEASE_NOTES_v0_13_1.md; sha256: c2e198aecfe58fe79867e37785df211dc52c5d039d9d898e37629319a19c6ceb -->

### Human and Arabidopsis HOG representatives

The HOG summary, human-member and complete-member tables in both the
**Human-containing HOGs** and **Plant and human HOGs** tabs now contain:

- `human_hog_representatives`
- `arabidopsis_hog_representatives`

The values are calculated per root-level `N0.HOG…` group and repeated in all
three displayed and downloadable tables. Parsed protein accessions are preferred;
parsed entry names and then raw identifiers are deterministic fallbacks. Multiple
unique representatives are sorted and semicolon-delimited. HOGs without an
Arabidopsis member retain a blank Arabidopsis value.

The tab filter searches both new representative fields. UI guidance defines the
selection and blank-value rules explicitly.

### Validation

The user reported that the complete R suite passed before this additive schema
change. Query integration and filtering assertions now cover multiple human
representatives, one Arabidopsis representative, repeated member-table values and
the intentionally blank absent-lineage value. The complete suite must be rerun:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Any actual test failure blocks release.

## v0.13.0

<!-- source: RELEASE_NOTES_v0_13_0.md; sha256: d474ffe6a459bc72339d80c9718299f6b20d8a04093370bbb66149088caf98c7 -->

This release mirrors Python reporter v0.10.0.

### Human and cross-lineage HOG tabs

- Adds **Human HOGs** for every root-level `N0.HOG…` containing
  `Homo_sapiens`.
- Adds **Plant & human HOGs** for the subset also containing at least one of the
  12 curated target plant species.
- Queries remain lazy, read-only and bounded, and load only when explicitly
  requested.
- Summary, human-member and all-member views carry candidate rank/status where
  available, membership metadata, available aliases and candidate-linked
  sequence fields. Each table has TSV and formatted Excel downloads; available
  protein sequences can also be exported as FASTA.

### Complete-resource search

- Adds a dedicated Search tab accepting one item or pasted lists.
- Smart, exact and literal-contains modes search recognised names, HOG/OG IDs,
  E3 seeds, accessions, entries, genes and DeepClust identifiers.
- Search combines unlike relation schemas safely by casting source fields to
  text before row binding, preventing the prior logical/character type clash.
- Summary and complete-hit tables both support TSV and Excel downloads.

### Test additions

- Adds SQL-builder, representative DuckDB, filter-consistency, parsing, schema
  compatibility and UI-contract tests for both feature sets.

## v0.12.1

<!-- source: RELEASE_NOTES_v0_12_1.md; sha256: 15416c6f76b73c1cec4fd20d1d40ec3aac9182be55a7b441d22f89c559505656 -->

- Renames the Orthology grouping controls to distinguish **Root-level
  phylogenetic HOGs (`N0.HOG…`; recommended)** from **Original MCL orthogroups
  (`OG…`; broader legacy view)**.
- Expands HOG on screen as hierarchical orthogroup and states that the `N0`
  groups reconcile rooted gene trees with the species tree.
- Identifies `OG…` groups as the original MCL-based `Orthogroups.tsv` output,
  retained for comparison rather than presented as the recommended root-level
  phylogenetic result.
- Preserves all relation names, filters, downloads, calculations and the
  scientific separation between OrthoFinder and DeepClust.

## v0.12.0

<!-- source: RELEASE_NOTES_v0_12_0.md; sha256: 0fb2f4298a92b04fa28273b25a1b98a525e3e191d96edf88c3b9a01ba3f8dad4 -->

- Adds a scientifically separate DeepClust/1KP sequence-neighbourhood panel to
  the Orthology page, with coverage metrics, an interactive distribution,
  inherited-seed and 1KP filters, optional evolutionary-group links and
  TSV/Excel downloads.
- Adds independent log-scale controls for both axes of the OrthoFinder and 1KP
  coverage plots; downloaded PDFs use the selected scales.
- Adds runtime PDF controls to compatible legacy pocket-review iframes, so the
  current 3D canvas and complete alignment can be downloaded without
  regenerating the original review bundle.
- Adds the previously missing PDF download for the bounded expression plot.
- Fixes the Orthology taxonomy selector constructing taxon labels before the
  represented-species table existed.

## v0.11.1

<!-- source: RELEASE_NOTES_v0_11_1.md; sha256: f414a5ee661b7daa203a80940a6ec4977b3b09c517e83fd0cca1574fc4a691cc -->

This patch corrects defensive validation in the new OrthoFinder grouping-level
resolver. Unknown, missing, empty or non-scalar group-type values now raise the
documented `Unsupported OrthoFinder group type` error before named-vector
indexing. Unit tests cover both valid mappings and all malformed input classes.

Scientific calculations, filters and displayed results are unchanged from
v0.11.0.

## v0.11.0

<!-- source: RELEASE_NOTES_v0_11_0.md; sha256: 62dd4364326f543bdab5e66986a3f69d8401fd1891406a74d85b9f90e1972754 -->

- Adds the same expanded Orthology and Seed & HOG workflows as the Python app.
- Adds exact species and curated taxonomy-role filters, group breadth metrics,
  single-species group distributions and group/member data downloads.
- Adds raw protein and selected MAFFT alignment FASTA downloads.
- Adds PDF downloads for all active app graphs and supports pocket-review v0.4.0
  direct current-view and multi-page alignment PDFs.
- Retains `cluster_id` in selectable final-gate box-plot data, repairing the two
  v0.10.6 group-selector test failures.

## v0.10.6

<!-- source: RELEASE_NOTES_v0_10_6.md; sha256: 0e4345b3356e8cf7d64f640cf4ddd4e720c45e2db6c33bab837672d7f5d0f06e -->

This usability release makes the final-gate member druggability box plot
selectable without changing any recorded result or scientific gate.

- A searchable **Evolutionary group to display** selector lists every
  structurally assessed group with retained member-level selected-pocket scores.
- The default is the highest-ranked scored group reaching the final
  druggability gate; when none reaches it, the highest-ranked scored assessed
  group is used.
- **All groups reaching the last gate** preserves the ranked comparison view.
  It is bounded to 30 groups for readable plotting, while every scored assessed
  group remains individually selectable.
- The plot updates immediately when the selected group changes.
- A summary reports the evolutionary-group ID, lead cluster, displayed group
  count, assessed-member count, minimum member score and complete status at the
  selected threshold.
- Statuses distinguish `PASS`, `FAILS DRUGGABILITY` and
  `FAILS ANOTHER FIXED GATE`, preventing a good pocket score from concealing a
  different failed requirement.
- Unit and UI regression tests cover searchable choices, default selection,
  single-group filtering, comparison truncation, summary values and defensive
  validation.

The application remains read-only. The selector filters values already loaded
from the completed resource and does not rerun or rewrite scientific analyses.

## v0.10.5

<!-- source: RELEASE_NOTES_v0_10_5.md; sha256: c0698d2e4f396000836124d5da704d3a2beb6816efc2b30f30def07a368d805f -->

This presentation and consistency release makes the two threshold-explorer
result sets explicit without changing the source data, recorded analysis or
scientific gate definitions.

- The explorer now shows a **Pre-structure candidate list** and a
  **Structurally informed candidate list** at the same time.
- Both lists share the same biological threshold controls and row scope. The
  structural controls affect only the structurally informed list.
- The summary boxes distinguish pre-structure passes, structurally assessed
  groups and structurally informed passes.
- Each list has its own bounded table and paired TSV/formatted Excel downloads.
- The former mode selector is removed, eliminating the confusing difference
  between the R app's structural default and the Python app's pre-structure
  default.
- The candidate-landscape Plotly widget now explicitly registers
  `plotly_click`, removing the Shiny event warning while retaining the exact
  point-to-candidate linkage.
- Regression tests cover matched paired settings, both table/download UI
  contracts and Plotly click registration.

The DuckDB temporary-extension directory message remains informational: it
describes session-local extension caching and does not affect the candidate
results.

## v0.10.4

<!-- source: RELEASE_NOTES_v0_10_4.md; sha256: 8d402158b8d10299763b08a25acdb4bc62e2ffa8975be3cd1b6132306391a179 -->

This compatibility patch corrects two R test failures discovered in the
v0.10.3 final-gate visualisation release. It does not change scientific values,
thresholds, gate decisions, rankings or output data.

- Empty recorded and selected sensitivity lists now retain a character-typed
  `sensitivity_change` column. This prevents `dplyr::bind_rows()` from trying to
  combine a zero-length logical column with a character column.
- The empty-result regression test now checks the column type explicitly.
- The Plotly regression test now checks the stable public widget classes,
  `plotly` and `htmlwidget`, rather than the version-dependent internal class
  `plotly_built`.
- The threshold-line assertion remains in place, so the selected slider value
  must still be materialised in the Plotly layout.

The two skipped `test_script_utils.R` tests remain expected when the R session
does not provide a `--file` argument.

## v0.10.3

<!-- source: RELEASE_NOTES_v0_10_3.md; sha256: 360ca6720499d9e3626b94197485e77ce0689f644038ec255b90db1ad125f08f -->

This sensitivity-analysis release keeps the authoritative 0.50 result, source
values, recorded ranks and every other production gate unchanged.

- The Computational recommendations page now contains a focused slider for the
  final all-members druggability gate.
- The rule is represented exactly as an inclusive minimum-member requirement:
  `minimum_druggability_score >= selected_threshold`.
- The selected list is recalculated from the complete fixed gate intersection;
  lowering the threshold cannot bypass pre-structure, pocket mapping,
  conservation, structural coverage or strict 3D requirements.
- Recorded and selected pass counts are shown together, with a separate table
  identifying groups entering or leaving relative to 0.50.
- The authoritative recommendation table is not rewritten. The recalculated
  list is explicitly labelled as sensitivity analysis and has paired TSV and
  formatted Excel downloads.
- Compatibility sources missing any required gate field are rejected with a
  clear message rather than being misreported as an empty biological result.
- Horizontal box plots show retained selected-pocket scores and individual
  assessed members for each lead cluster reaching the last gate; the reference
  line follows the selected slider value.
- Older portable review pages receive a working **Fit and centre** viewer
  control that restores orientation and zoom and confirms the action visibly.
- Regression tests cover the inclusive equality boundary, fixed-setting
  contract, source-field validation, entrant/leaver classification and UI
  controls, member distributions and portable-viewer compatibility repair.

## v0.10.2

<!-- source: RELEASE_NOTES_v0_10_2.md; sha256: e67e6746edc7442aa5a3c9abdac8db3ebf3c7fbc3ec28c7839f0fb75f2d6c3e9 -->

This presentation and reliability release keeps all scientific source values,
recorded ranks and primary-analysis gates unchanged.

- The Glossary now opens with every project term and field-dictionary row in one
  vertically scrollable browser table. Section filtering and downloads remain
  optional.
- The Expression section provides direct controls for opening the existing
  heatmap and scientifically gated volcano-eligibility views.
- The 3D alignment section now includes an interactive minimum-TM-score versus
  3D-pocket-overlap evidence map with hover details, zoom, pan and recorded 0.50
  threshold lines. Rotatable coordinate models remain in the portable 3D
  structures and pockets view.
- Compatibility fixes cover current DT extension validation, unnamed Excel
  long-text row indices, workbook table-part discovery, stable ranking order
  vectors and current dplyr column selection.
- The obsolete raw-expression-tab expectation in the application tests now
  matches the current result-source interface.
- A dedicated Workflow schematic tab follows every stage from controlled inputs
  to app-ready recommendations, including parallel discovery/OrthoFinder,
  domain/expression and structural/optional-chemistry branches.
- The Computational recommendations page now provides a full methods-style
  explanation of score construction, unavailable denominators, effective final
  weights, hard-gate precedence, deterministic consolidation and experimental
  limitations.

The alignment plot is descriptive. Same-position support still requires the
recorded centroid-distance rule, and none of these interface changes rewrites a
scientific result.

## v0.10.1

<!-- source: RELEASE_NOTES_v0_10_1.md; sha256: 4d378fea404864201c47f7a7869163244079922af2eeb904dd9ca3b51204d9f0 -->

This maintenance release improves readability and export completeness without
changing any scientific result or source value.

- Wide DataTables now provide horizontal scrolling, a bounded vertical body
  with a stationary header, compact numeric cells and deliberately wider
  identifier and narrative columns.
- The All results browser now offers both exact TSV and formatted Excel
  downloads for the bounded rows being viewed.
- The threshold explorer now opens the pre-structure and structural controls
  together and applies both sets by default. An optional selector adds post-hoc
  gates for compatible recorded aggregate scores; these extra gates are off by
  default and cannot rerun the scientific pipeline.
- Excel workbooks show gridlines and explicit cell borders, centre ordinary body
  values, and use left-aligned wrapped 10-point text with capped row heights for
  long narrative cells.
- The glossary now combines project-wide technical terminology with the full
  218-field final-candidate data dictionary and records definitions, units,
  rules, cautions and sources.
- Computational recommendations now documents every recorded score formula,
  default weight, tie-break and evolutionary-group consolidation step below the
  table. An expandable slider-based sensitivity explorer can produce a clearly
  non-authoritative alternative ordering with paired TSV and Excel downloads;
  it never rewrites official ranks or hard gates.

TSV values and numeric values stored in Excel remain exact. Rounding is display
formatting only.

## v0.10.0

<!-- source: RELEASE_NOTES_v0_10_0.md; sha256: 0d864c8776d9d7fab7f7f7150736b51f6351eed5b72d73187ecf8d5899e26c11 -->

- Removes the obsolete raw Expression Atlas sidebar and its four dependent
  legacy tabs. Integrated candidate expression remains available in the main
  evidence interface.
- Replaces the permanent sidebar layout with a full-width navigation layout.
- Adds a dedicated computational-chemistry section over the same integrated
  DuckDB relations used by the Python app.
- Retains read-only, bounded queries and TSV downloads.
- Adds a neighbouring formatted Excel download wherever the app exposes a TSV
  table download. Excel tables have frozen headers, filter controls, banded
  rows, readable bounded widths, wrapped long text and semantic numeric formats.

## v0.9.0

<!-- source: RELEASE_NOTES_v0_9_0.md; sha256: 27e2bd33fb5522a1a7ed0761d6d52f936e16bca4d54293a6819761d4dc99fa00 -->

Version 0.9.0 adds a linked, read-only Visual explorer to the R Shiny
application while retaining the v0.8.1 source-loading compatibility repairs.

- The candidate landscape exposes selectable x, y, colour and size fields from
  the authoritative candidate relation. Clicking a point links the candidate
  summary and exact supporting-relation table.
- The expression heatmap compares no more than 25 candidate groups across one
  selected species/context scale and one explicit expression unit.
- The species/tissue tab links the selected group to every available
  tissue-annotated Expression Atlas context, faceted by species. DuckDB
  aggregates all matching contexts before the plotted-cell limit, so the
  separate exact-row preview/download limit cannot truncate the visual profile.
- Missing or unavailable expression evidence remains distinct from measured
  zero.
- Volcano plotting activates only when a loaded relation contains both a
  recognised differential-expression effect-size field and a recognised
  P-value, adjusted-P, FDR or Q-value field. Absolute expression is not treated
  as differential expression.
- All new DuckDB queries are quoted, exact, read-only and hard-bounded.

The complete R `testthat` suite and the all-source parse regression must be run
in the `e3_shiny_app` conda environment before the release is committed.

## v0.8.1

<!-- source: RELEASE_NOTES_v0_8_1.md; sha256: 333fcf1aa86ee70db2165df589a33e7aedab09e0c4a8d1e50bb7aeaa1d11861b -->

Version 0.8.1 is a source-loading compatibility hotfix for the v0.8.0
application. It replaces a compact single-expression `tryCatch()` error handler
with an explicit braced function body in `module_result_section.R`. This avoids
the Shiny application loader reporting a possible missing comma while sourcing
the package-style `R/` directory.

It also wraps the two expression-filter column layouts in a single
`shiny::tagList()`. The layouts had been placed directly inside one conditional
branch and separated by a comma, which prevented R from parsing the module.

The launcher now passes the explicit `app.R` file to `shiny::runApp()` instead
of the package root. The application therefore follows its declared source
order without Shiny also auto-loading the package-style `R/` directory.

The scientific queries, display logic, input data contracts and workflow
results are unchanged.

The complete `testthat` suite must be executed in the `e3_shiny_app` R
environment before release.

## v0.8.0

<!-- source: RELEASE_NOTES_v0_8_0.md; sha256: 9ae976de300791dea39e3464b9d4c0a63135b39bc637797e9ea4dea0040affa0 -->

Version 0.8.0 is aligned with workflow v0.13.0 and the corrected expression
contract. It retains the v0.7.0 glossary, assessed-species denominator help and
tissue/context filtering, while distinguishing unavailable mapping from
measured zero expression.

The complete `testthat` suite must be executed in the `e3_shiny_app` R
environment before release.

## v0.7.0

<!-- source: RELEASE_NOTES_v0_7_0.md; sha256: 882e8faa99d32fa3aa9387e098683462ef35ad2302f99be2b18a7020cb27a267 -->

- Adds a searchable, downloadable Glossary tab without removing existing tabs.
- Adds plain-language definitions beneath all manual threshold controls.
- Clarifies that the domain-support fraction is calculated among species with
  usable domain annotations, not all target species or all sequences.
- Prioritises workflow v0.12.0 candidate-by-expression-context data so tissue,
  developmental stage, condition, treatment, experiment and sample fields can
  reach the final application tables.
- Retains legacy resources while distinguishing missing mapping from measured
  biological zero expression.

## v0.6.0

<!-- source: RELEASE_NOTES_v0_6_0.md; sha256: 51e8cc3d8ded6809ef703d3d9978f1f904c776edcb5d18c9ab0b070ef5291e65 -->

### Selected-group visual review

- Adds a **3D structures & pockets** tab without removing or replacing any
  existing application tab.
- Adds a separate **Pocket-aligned sequences** tab for the published MAFFT
  alignment and exact pocket-residue highlights.
- Uses the existing checksum-bound, self-contained pocket-review bundle rather
  than attempting to follow inaccessible cluster paths from a copied DuckDB.
- Provides a searchable rank, evolutionary-group, lead-cluster and reference
  accession selector.
- Defaults to the first group in the authoritative review order and never
  recalculates candidate ranking.
- Exposes the original group-member accession/name values, stable FASTA export
  identifiers, species, reference status and pocket-evidence status.
- Provides selected-group TSV downloads and direct links to the full ranked
  review index and cross-group structural evidence matrix.
- Shows unavailable models and unassessed members explicitly rather than
  interpreting them as biological negatives.

### Portable release behaviour

- Adds `--pocket_review_dir` and `E3_POCKET_REVIEW_DIR` configuration options.
- Automatically discovers the bundle only when exactly one valid direct
  `pocket_review*` directory exists beside the selected DuckDB or Parquet.
- Rejects incomplete bundles, unsafe group-page paths, duplicate ranks and
  ambiguous automatic discovery.
- Serves the report locally through a read-only Shiny resource mapping; no
  network connection, CDN or remote structure service is required.

### Interpretation boundary

The embedded 3D view is a rotatable C-alpha trace with mapped pocket residues,
not an atomistic surface, docking result or binding prediction. It visualises
completed evidence without rerunning pocket detection, MAFFT, US-align or
TM-align.

## v0.5.0

<!-- source: RELEASE_NOTES_v0_5_0.md; sha256: 6ed9803f8a9d85f7e2ded64d296272aa667b758b0a31958af144e3147e046ab8 -->

### Correctness fixes

- Returns the resolved `resource_source`, Parquet path and run-directory path
  from `get_app_config()`.
- Makes derived-directory inference accept DuckDB, master-Parquet and completed
  run-directory sources without passing unsupported arguments.
- Restores the deterministic unknown-Parquet relation naming expected by the
  test suite. Numeric stage prefixes remain safe because relation identifiers
  are always quoted in generated SQL.
- Removes the candidate master relation from unrelated specialist sections,
  avoiding duplicate candidate-level displays in orthology, domain, expression,
  ligandability and structural tabs.
- Uses `final_evolutionary_candidate_prioritisation` for headline counts. If
  only a cluster-level compatibility source exists, the app deterministically
  retains one lead row per OrthoFinder evolutionary group before counting.

### Threshold explorer

- Adds separate pre-structure and structurally informed views.
- Pairs sliders with manual numeric inputs and provides a one-click reset to the
  current grant-aligned defaults.
- Supports target, mandatory, domain, expression, structural-coverage and
  minimum-druggability thresholds plus categorical evidence requirements.
- Labels results as `PASS`, `NEAR_MISS`, `FAIL` or
  `NOT_STRUCTURALLY_ASSESSED`.
- Uses minimum member druggability as the dynamic all-member gate while
  retaining the original fixed-threshold all-member decision as an audit field.
- Downloads tab-separated custom lists with the active numeric thresholds
  repeated in every row.
- Exposes a substantially expanded evidence table with column visibility,
  filtering and horizontal scrolling.

### Interpretation boundary

The explorer filters completed evidence. It does not rerun pocket detection,
sequence alignment or 3D comparison. Its lists are sensitivity analyses and do
not alter the primary recorded analysis.

## v0.4.0

<!-- source: RELEASE_NOTES_v0_4_0.md; sha256: e032648ee42109a29707acf39cadba4b82c4a64c971b398735120a0fd5bfeff7 -->

- Replaces the generic-only scaffold with grant-focused candidate, orthology,
  domain, expression, ligandability, pocket-conservation and 3D-alignment views.
- Adds independent checkbox column controls to every scientific section and the
  all-results browser.
- Supports three interchangeable read-only sources: integrated DuckDB, one
  candidate master Parquet, or all current non-superseded workflow Parquets.
- Adds a Milestone 1/Milestone 2 overview and explicit interpretation boundaries.
- Preserves the raw Expression Atlas summary, table, lookup and plotting modules.
- Adds unit/integration tests for source discovery, lazy Parquet registration,
  section routing, selected-column SQL and UI contracts.
