# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.16.2

- Adds accessible question-mark definitions beside every metric in the
  embedded pair-evidence table, with a complete readable definition panel.
- Explains why the displayed plant model is the fixed structural reference,
  including the evidence ordering that can select a Medicago representative
  and the absence of any preferred-species rule.
- Adds focused help for filtered human-extension ranks, alternative protein and
  pocket controls, and recognised structural-evidence table columns.
- Changes presentation and documentation only; no scientific result, threshold,
  ranking, stored review bundle or reference choice is recalculated.

## v0.16.1

- Synchronises the human-and-plant pairwise 3D, structure/pocket and
  pocket-annotated FASTA views under one evolutionary-group selector.
- Labels both the fixed reference and transformed mobile protein, including
  species and structural aligner, for every pairwise superposition.
- Explains the filtered, non-contiguous extension ranks and reports explicitly
  when original rank 7 is absent from the portable review bundle.
- Expands the recorded methods for one-per-species plant representative
  selection, best-evidence structural-reference selection, retained
  alternatives and exact human-member handling.

## v0.16.0

- Opens exact analysis-derived, self-contained US-align/TM-align
  superpositions in the existing plant-only 3D alignment view.
- Adds a scientifically separate human-and-plant 3D alignment view with
  structures, pockets, pocket-annotated MAFFT alignments, evidence tables and
  HTML, TSV, formatted Excel and FASTA downloads.
- Retains exact human HOG-member sequences when structure or pocket evidence is
  unavailable, without presenting them as pocket-aligned evidence.
- Adds a complete runtime DuckDB-header glossary and a `Column definitions`
  worksheet to every generated Excel workbook.

## v0.15.0

<!-- source: RELEASE_NOTES_v0_15_0.md; sha256: 703368ef3a67b695dcaa82b727cc64d0bc6a03b3ced9afba8f558ec22983a288 -->

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

- Unified-search matches persist while column controls rerun the Streamlit
  page. Users can choose the first 18, all or no fields, and both preview and
  download exactly the selected columns.
- Expression filtering accepts one identifier or up to 50 unique values pasted
  with semicolon, comma, tab or newline separators. The filtered values can be
  downloaded directly as TSV or Excel.
- Expression heatmaps now encode low values as white and high values as red.

### Scientific-method annotation retained

The v0.14.0 threshold and method annotations remain unchanged, including the
Xu and Zhang (2010) reference for TM-score 0.50 as an established approximate
fold/topology boundary. The annotation continues to state that this global
fold threshold does not by itself establish pocket equivalence.

No scientific pipeline output, stored threshold or authoritative ranking is
rewritten by this reporter release.

### Release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

## v0.14.0

<!-- source: RELEASE_NOTES_v0_14_0.md; sha256: 576e8eb7508ea1742ec1d9b8ee6f3a3f6cf412444a847fcae0a0394f3ae1d4ad -->

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
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any functional, style, documentation, shell or 95% branch-coverage failure
blocks release.

## v0.13.0

<!-- source: RELEASE_NOTES_v0_13_0.md; sha256: 2fd66d183b13f3a2a923184a44e71927825591f7656b98d85b8313ac0c9ed7f9 -->

### Independent structural-review shortlist

The former ungated top-HOG page has been replaced by a scientifically explicit
shortlist for the computational team. It returns the top 200 root-level
`N0.HOG…` groups by default and can expand to 500. The recorded rank integrates
discovery, orthology/species, E3-domain and expression evidence. The recorded
pre-structure pass is available as an optional filter.

Existing AlphaFold/model, pocket, ligandability/druggability, mapping,
alignment, conservation and 3D fields are excluded from this shortlist and
from its deterministic tie-breaks. Those published results are unchanged and
remain available in the dedicated structural tabs.

### Richer Threshold explorer

Both threshold-result tables retain substantially more source context,
including available ranks, candidate and seed identifiers, component scores,
species coverage and missing species, domain and expression availability,
discovery composition, inclusion/exclusion reasons and missing-evidence fields.
The bounded result is then enriched with human and Arabidopsis representatives,
accessions and entries, total HOG member/species counts, species composition,
orthogroup/parent-clade links and review/mapping summaries. These fields are
present in the matching TSV and formatted Excel downloads.

### E3 seed catalogue

A new searchable catalogue returns one row per inherited known-E3 seed and
accepts pasted lists of identifiers, names or annotation terms. When the loaded
release publishes `known_e3_seeds`, exact metadata and row provenance are read
from that authority. Older releases reconstruct matched identifiers from the
candidate summaries and place non-one-to-one annotations in explicitly named
`associated_…` fields.

An exact protein sequence is reported only when the seed identifier matches a
sequence-bearing HOG member. The sequence search correctly considers every HOG
member; `is_input_candidate` is not used because it describes candidate status,
not seed status. Available sequences can be downloaded as FASTA, and the table
as TSV or formatted Excel. The dedicated query remains hard-bounded at 100,000
rows and its user-set cap can exceed the normal preview limit.

### Release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any functional, style, documentation, shell or 95% branch-coverage failure
blocks release.

## v0.12.1

<!-- source: RELEASE_NOTES_v0_12_1.md; sha256: 54814d6429cce54fb63ac58f651180049ca7fa1b6eb2d9b7097b87555fb56f71 -->

### Coverage-gate hotfix

The complete v0.12.0 application suite passed all 133 functional tests, but the
release gate stopped because total branch coverage was 94%, below the required
95% threshold.

This patch adds focused tests for previously untested defensive and fallback
paths in:

- bounded DuckDB candidate, expression and differential-expression queries;
- display formatting, FASTA validation and Plotly PDF renderer failures;
- ranking weight types/ranges, optional 3D status, identifier and recorded-rank
  fallbacks; and
- pasted-search type, term-count, output-limit and empty-summary handling.

No production scientific or application logic changed. The coverage threshold
remains 95% and must not be lowered.

The eight Plotly/Kaleido messages in the predecessor run are third-party
deprecation warnings from Kaleido 0.2.1 compatibility code. They did not fail
the tests or coverage gate. Kaleido remains pinned because this application
uses its self-contained PDF renderer rather than introducing a system-browser
runtime requirement in this test-only patch.

Run the complete release gate before publishing:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any test, style or coverage failure blocks release.

## v0.12.0

<!-- source: RELEASE_NOTES_v0_12_0.md; sha256: b89661c651d7adba2a246e6e58e81228a9beb99bb3da2dc987d4cd0b71492fc5 -->

### Complete enriched HOG results

The **All results** tab now opens with an enriched one-row-per-root-HOG view
instead of implying that one raw relation contains the complete HOG record. Its
selectable fields begin with HOG ID, canonical pre-structure and post-structure
ranks, human representatives and Arabidopsis representatives. They continue
with membership/species summaries and every original field from the strongest
available HOG-linked ranking relation.

A second enriched member-detail view retains every source
`hierarchical_membership` field with a `member_` prefix and repeats the HOG-level
representatives, rankings and candidate annotations on each member row. It
therefore supports complete, interpretable member exports without constructing
an uncontrolled many-to-many join.

All original DuckDB relations remain selectable for exact source-level audit.
The interface now states explicitly that **Select all fields** means all fields
in the selected enriched view or raw relation.

### Defensive behaviour

The join retains membership-only and ranking-only root HOGs, marks source
availability explicitly, deterministically selects one ranking row per HOG and
reports how many source ranking rows existed. Every query remains column-
validated and row-bounded.

Run the complete release gate before publishing:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any test or style failure blocks release.

## v0.11.1

<!-- source: RELEASE_NOTES_v0_11_1.md; sha256: b733cbfeb83305e9e2c2140920395647c27fbb9bc8c90aa581a48c92a8dd19a3 -->

### Style-gate hotfix

Version 0.11.0 installed successfully, but the release style gate reported
`W391 blank line at end of file` for four newly added files:

- `src/e3app/prestructure_hogs.py`
- `src/e3app/tab_help.py`
- `tests/test_prestructure_hogs.py`
- `tests/test_tab_help.py`

Version 0.11.1 removes only those redundant terminal blank lines. Each file now
ends with exactly one newline, as required by PEP 8 and `pycodestyle`.

There is no application-logic, query, scientific, interface or test-behaviour
change from v0.11.0. R Shiny v0.14.0 already passed its complete suite and is
unchanged.

### Release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any remaining failure blocks publication.

## v0.11.0

<!-- source: RELEASE_NOTES_v0_11_0.md; sha256: 88f5b872c8973808eb8f44893bcbda675ef138318bb9b4e785b445250a924a0b -->

### Direct pre-structure top-N HOG list

The new **Pre-structure ranked HOGs** tab makes the requested top-200 analysis
set available without configuring the general threshold explorer. It:

- selects one row per root-level `N0.HOG…`;
- orders by `prestructure_evolutionary_group_rank`, falling back only to the
  equivalent authoritative `evolutionary_group_rank` field;
- never substitutes cluster-level `computational_rank`;
- applies no target-species, mandatory-species, domain, expression, pocket,
  druggability or structural gate;
- defaults to 200 rows within the configured application row cap;
- preserves the recorded rank when the visible result is searched; and
- adds available human and Arabidopsis HOG representatives before paired TSV
  and formatted Excel download.

If an older result source lacks both the root-HOG identifier and authoritative
HOG-level pre-structure rank, the tab explains that it is unavailable instead
of constructing a biologically different surrogate ranking.

### Contextual tab help

Every top-level tab now begins with a collapsed **❓ How to use this tab** panel.
The maintained help catalogue provides tab-specific operating guidance,
evidence boundaries and interpretation cautions. Tests require exact coverage
of all current top-level tabs so a future tab cannot silently omit guidance.

### Streamlit runtime compatibility

All deprecated `use_container_width` arguments have been replaced with
`width="stretch"`. The minimum Streamlit version is consequently 1.51. The
final-druggability group selector now obtains its initial value solely from its
keyed Session State entry, avoiding the warning caused by supplying both a
widget default and a Session State value.

### Validation

New focused tests cover rank-source authority, root-HOG filtering, deterministic
deduplication, absence of gate filtering, representative annotation, row-limit
validation, complete help coverage and the two Streamlit warning regressions.
The complete suite must be rerun in the release environment:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any failure blocks release.

## v0.10.1

<!-- source: RELEASE_NOTES_v0_10_1.md; sha256: dbd0c2ea2f876aa0a236d12c37b398d939e1072509ab5b6eb37a860d9b8b93e4 -->

### Search test hotfix

The batch smart search intentionally returns every matching relation with source
provenance. The accession `Q9SA03` in the representative test resource occurs in
both `aliases.member_accession` and `ranked.candidate_accessions`. The previous
test assumed that the ranked relation would always be the first row, although
the stable relation ordering places `aliases` first.

The test now checks the complete set of valid relation/column matches. Search
logic, matching modes, result ordering and production data are unchanged.

### Human and Arabidopsis HOG representatives

The summary, human-member and complete-member tables in both HOG explorers now
contain:

- `human_hog_representatives`
- `arabidopsis_hog_representatives`

Each value is calculated once per root-level `N0.HOG…` group and repeated on
every table row so it remains present in TSV and Excel downloads. A member's
display identifier uses the parsed protein accession when available, otherwise
the parsed entry name, otherwise the published raw identifier. Multiple unique
representatives are sorted and separated by semicolons. A missing lineage is an
empty string, not a fabricated biological negative.

The local HOG filter searches both new fields.

### Validation

The user's v0.10.0 environment reported 120 passing tests and the one obsolete
row-order assertion fixed here. The edited source and tests compile in the build
workspace and pass whitespace and 100-character line-length checks. The complete
suite must be rerun in the release environment:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

The Plotly/Kaleido `scope.mathjax` messages are dependency deprecation warnings,
not the cause of the failed assertion. Static PDF payload tests remain unchanged.

## v0.10.0

<!-- source: RELEASE_NOTES_v0_10_0.md; sha256: 23bda43badc0d82931cd08e0920741fe986157444032cc7385a2ae2d533439d7 -->

### New exploration views

- Adds a lazy-loaded **Human HOGs** tab containing every root-level
  `N0.HOG…` with at least one `Homo_sapiens` member.
- Adds a separate **Plant & human HOGs** tab requiring both human membership
  and membership from at least one of the 12 curated target plant species.
- Both views retain ranked and unranked HOGs, candidate ranking position and
  status where available, composition counts, human identifiers, all HOG
  co-members, aliases and candidate-linked sequence annotations.
- Both views provide complete TSV and formatted Excel downloads plus FASTA when
  the integrated release contains the corresponding protein sequences.

### Search replacement

- Replaces exact single-accession search with a batch-capable complete-resource
  search for names, HOG/OG IDs, E3 seeds, accessions, entries, gene identifiers
  and DeepClust identifiers.
- Accepts newline, comma, semicolon or tab lists, with smart, exact-token and
  literal-contains modes.
- Every hit records the original search term, source relation and matching
  fields before returning every available source column.

### Scientific boundaries

- Human/plant HOG membership is explicitly evolutionary co-membership rather
  than evidence that every member is an E3 ligase.
- HOGs absent from the candidate ranking are labelled
  `NOT_IN_CANDIDATE_RANKING`; absence is not converted into biological failure.
- DeepClust remains a separate non-phylogenetic sequence-neighbourhood view.

### Validation

- Adds focused unit and representative DuckDB tests for HOG view definitions,
  ranking enrichment, aliases, member sequences, list parsing, matching modes,
  bounds and source provenance.
- Updates headless Streamlit expectations for the two new views and replacement
  Search tab.

## v0.9.2

<!-- source: RELEASE_NOTES_v0_9_2.md; sha256: 4651d55db0a46f73ded7e3c118da2cf381d3ac07969710bc157d1e61e495ceed -->

- Repairs the headless Streamlit fixture so `orthogroup_membership`,
  `hierarchical_membership` and `candidate_group_member_sequences` follow the
  production relation contracts.
- Scopes Orthology widget assertions to their actual Streamlit tabs, preserving
  explicit coverage of both log-axis controls and both corrected grouping-level
  labels.
- Fixes the single v0.9.1 test failure in
  `test_app_renders_and_searches`; application logic, data queries and scientific
  results are unchanged.
- The Plotly/Kaleido messages reported alongside the failure are dependency
  deprecation warnings and are not test failures.

## v0.9.1

<!-- source: RELEASE_NOTES_v0_9_1.md; sha256: cc11cf79ce6e7707e22248bbfcc9b04c490d71f22142933334905bd81b0eaa72 -->

- Renames the Orthology grouping controls to distinguish **Root-level
  phylogenetic HOGs (`N0.HOG…`; recommended)** from **Original MCL orthogroups
  (`OG…`; broader legacy view)**.
- Adds a visible definition of HOG and the exact `N0.HOG…`/`OG…` identifier
  mapping used by the application.
- Corrects the Orthology and seed-explorer explanations without changing
  relation keys, query behaviour, downloads or scientific results.
- Adds headless regression assertions for both corrected selector labels.

## v0.9.0

<!-- source: RELEASE_NOTES_v0_9_0.md; sha256: a5bf5b8db2cecd3624f629b1f86adbb555be07bdc1dbf39b8bb312ae348538ce -->

- Adds a separate **DeepClust and 1KP sequence neighbourhoods** panel below the
  OrthoFinder view. It reports cluster-level raw/strict 1KP sample and parsed
  species coverage from `candidate_evidence`, supports one or several inherited
  seed filters and preserves optional links to reconciled evolutionary groups.
- Keeps the scientific boundary explicit: DeepClust membership is sequence-space
  discovery evidence and is never labelled as inferred orthology or proof that
  every member is an E3 ligase.
- Adds independent linear/logarithmic x- and y-axis controls to the OrthoFinder
  group-size and 1KP-coverage plots. PDF exports preserve the active scales.
- Upgrades compatible legacy pocket-review HTML in memory with functional
  **Download current view PDF** and **Download alignment PDF** controls. The
  source review bundle remains read-only.
- Packages and validates the offline browser PDF compatibility asset.

## v0.8.1

<!-- source: RELEASE_NOTES_v0_8_1.md; sha256: 126ded73ece42187b2478bd23ae58a2986f0cd7f5d87b644dcc54dd7c1cc1644 -->

This patch removes the PEP8 E203 violation in FASTA sequence wrapping by using
the standard slice form without whitespace before the colon.

FASTA content, graph exports and scientific behaviour are unchanged from
v0.8.0.

## v0.8.0

<!-- source: RELEASE_NOTES_v0_8_0.md; sha256: 1148fcc8b95d7db8ecacf6dadac1bbc261b75c245449b1626355bbf27566d985 -->

- Expands Orthology with release-wide metrics, exact multi-species and curated
  taxonomy-role filters, all-species groups, largest groups and size/breadth
  distributions retaining one-species groups.
- Adds a multi-seed HOG/orthogroup explorer with Any/All matching, species
  filtering, associated evidence, TSV/Excel tables and protein FASTA export.
- Adds selected-group MAFFT FASTA and on-demand vector-PDF graph downloads.
- Supports the direct 3D-view and alignment PDF controls generated by the
  structural-alignment v0.4.0 pocket-review report.

Seed status means inherited prior E3 evidence. It is not treated as proof of E3
function, and exact species/taxonomy labels are never inferred when unavailable.

## v0.7.6

<!-- source: RELEASE_NOTES_v0_7_6.md; sha256: d9385d8e4022e5d94175a070966f76ccfddd8652f11c6a406f9363513a13c397 -->

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
- The full Python quality gate passes 94 tests with 95% branch-aware coverage,
  including headless selection of a different group in the application.

The application remains read-only. The selector filters values already loaded
from the completed resource and does not rerun or rewrite scientific analyses.

## v0.7.5

<!-- source: RELEASE_NOTES_v0_7_5.md; sha256: 6612067498411b3d50f7d948ae5529adcd81972bc2f136d111d359ee7fa93954 -->

This presentation and consistency release makes the two threshold-explorer
result sets explicit without changing the source data, recorded analysis or
scientific gate definitions.

- The explorer now shows a **Pre-structure candidate list** and a
  **Structurally informed candidate list** at the same time.
- Both lists share the same biological threshold controls and row scope. The
  structural controls affect only the structurally informed list.
- Summary metrics distinguish pre-structure passes, structurally assessed
  groups and structurally informed passes.
- Each list has its own bounded table and paired TSV/formatted Excel downloads.
- The former mode selector is removed, so the R and Python apps present the
  same two scientific populations rather than starting on different views.
- A defensive paired-settings helper guarantees that the two evaluations
  differ only by their pre-structure/structural evaluation mode.
- The complete Python gate passes 93 tests with 95% branch-aware coverage.

## v0.7.4

<!-- source: RELEASE_NOTES_v0_7_4.md; sha256: 9e6c5865403b6ee2db3a2518288fa96aeef036ac99ce94f97ac9ecf44c08eba2 -->

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
- The portable structure viewer's former zoom-only action is upgraded to
  **Fit and centre**, which restores orientation and zoom and confirms the
  action visibly.
- The Python quality gate includes regression tests for the inclusive equality
  boundary, fixed-setting contract, source-field validation, entrant/leaver
  classification, member distributions, rendered slider and legacy viewer
  repair.

## v0.7.3

<!-- source: RELEASE_NOTES_v0_7_3.md; sha256: 52731183dbea1ac06da3f3a3554e15cc2aab19ef5f78e068b9b505ef76110027 -->

This presentation-only patch keeps all scientific source values, recorded
ranks and primary-analysis gates unchanged.

- Every in-app data-grid column now receives an explicit pixel width.
- Numeric and logical fields remain compact, identifiers receive more space,
  and narrative interpretation fields receive the widest treatment.
- Wide results therefore use Streamlit's native horizontal scrollbar instead
  of compressing headings and identifiers into near-character-width columns.
- The bounded vertical viewport retains Streamlit's stationary header.
- A dedicated Workflow schematic tab now explains the complete evidence path
  from controlled inputs and DeepClust/OrthoFinder branches through domain,
  expression, pocket and 3D evidence to deterministic group consolidation and
  app-ready recommendations.
- The Computational recommendations page now contains the expanded methods-style
  explanation of every score, numerator, denominator, missing-evidence rule,
  effective final weight, gate-first ordering rule and interpretation boundary.

The same underlying data, selected columns, row limits and TSV/Excel downloads
are retained.

## v0.7.2

<!-- source: RELEASE_NOTES_v0_7_2.md; sha256: ccc115c56fe4693513888d057eac3b76b39bc407095dca88c8552bd793c61526 -->

This presentation and reliability release keeps all scientific source values,
recorded ranks and primary-analysis gates unchanged.

- The Glossary now opens with every project term and field-dictionary row in a
  single browser table. Section filtering remains optional, as do TSV and Excel
  exports.
- Main navigation uses Streamlit's stable tab test identifiers to wrap onto as
  many rows as needed and suppress both tab-scroll controls.
- The Expression section now embeds the cross-species heatmap and scientifically
  gated volcano-eligibility view already available in Visual explorer.
- The 3D alignment section now includes an interactive minimum-TM-score versus
  3D-pocket-overlap evidence map with hover details, zoom, pan and recorded 0.50
  threshold lines. The existing portable review retains rotatable coordinate
  models.

The alignment plot is descriptive. Same-position support still requires the
recorded centroid-distance rule, and none of these interface changes rewrites a
scientific result.

## v0.7.1

<!-- source: RELEASE_NOTES_v0_7_1.md; sha256: bcae2d19c1029385aaae275451e46ce5b594338ff8e368aa50a417e2a530b4d1 -->

This maintenance release improves readability and export completeness without
changing any scientific result or source value.

- Main navigation tabs wrap across multiple rows instead of hiding sections
  behind horizontal tab-scroll arrows.
- Wide result tables retain horizontal scrolling, use a bounded vertical
  viewport with a stationary header, allocate wider text columns and display
  ordinary decimal measures to three places.
- The All results browser now offers both exact TSV and formatted Excel
  downloads for the bounded rows being viewed.
- Excel workbooks show gridlines and explicit cell borders, centre ordinary body
  values, and use left-aligned wrapped 10-point text with capped row heights for
  long narrative cells.
- The glossary now combines project-wide technical terminology with the full
  218-field final-candidate data dictionary and records definitions, units,
  rules, cautions and sources.
- Computational recommendations now documents the complete recorded ranking
  formulas, default weights, tie-breaks and group consolidation below the main
  table. An expandable slider explorer creates a clearly non-authoritative
  alternative ordering with paired TSV and Excel downloads without changing
  official ranks, hard gates or source data.

TSV values and numeric values stored in Excel remain exact. Rounding is display
formatting only.

## v0.7.0

<!-- source: RELEASE_NOTES_v0_7_0.md; sha256: 891290663a00ed26eee7c20363399ce1eaaa595d2534508c2943f7f80157240e -->

- Adds a dedicated computational-chemistry section for integrated candidate
  evidence, hand-off decisions, sensitivity results, pharmacophore features and
  optional fragment evidence.
- Recognises the new chemistry Parquets consistently in DuckDB and workflow-run
  directory modes.
- Retains bounded, read-only queries and TSV downloads.
- Adds a neighbouring formatted Excel download wherever the app exposes a TSV
  table download. Excel tables have frozen headers, filter controls, banded
  rows, readable bounded widths, wrapped long text and semantic numeric formats.

## v0.6.0

<!-- source: RELEASE_NOTES_v0_6_0.md; sha256: cf723f018e94f6aba0b9687d47cec62f1671091b2be89c6a6ad65c2f6d0a7953 -->

Version 0.6.0 adds a linked, read-only Visual explorer to the Streamlit
application.

- The candidate landscape exposes user-selectable x, y, colour and size fields
  from the authoritative candidate relation. Point selection links to the exact
  candidate row and any compatible supporting relation.
- The expression heatmap compares up to 25 candidate groups across a selected
  species/context scale while keeping expression units separate.
- The species/tissue view shows every available tissue-annotated context for a
  candidate, faceted by species. DuckDB aggregates all matching contexts before
  the plotted-cell limit, so the separate exact-row preview/download limit
  cannot truncate the visual profile.
- Missing or unavailable expression evidence is never converted to measured
  zero.
- Volcano plotting is capability-gated. The current absolute Expression Atlas
  release does not contain differential effect sizes plus significance values,
  so the tab explains the scientific limitation instead of fabricating a plot.
- Plotly point selection is linked through Streamlit session state; every data
  query is exact, read-only and bounded.

Validation: 48 tests passed with 95% branch-aware coverage, including the new
data-query, visual-preparation, Plotly and headless Streamlit contracts.

## v0.5.0

<!-- source: RELEASE_NOTES_v0_5_0.md; sha256: 323ea8cf1573822d80d80b1fb3095988094b80b92f11177aa1ad0a9d2baca98e -->

Version 0.5.0 is aligned with workflow v0.13.0 and the corrected expression
contract. It preserves the v0.4.0 glossary, inline threshold definitions and
tissue/context explorer while clearly separating unavailable expression
mapping from measured zero expression.

Validation: 40 tests passed with 98% branch-aware coverage, including headless
Streamlit rendering, exact threshold/glossary tests and corrupt-resource cases.

## v0.4.0

<!-- source: RELEASE_NOTES_v0_4_0.md; sha256: ee403778a116a575c440e23fd8878526b83cdec1038ebb228849a213b7266d4b -->

- Adds a searchable, downloadable glossary covering seeds, grouping units,
  gates, strict predictions, assessed denominators, primary thresholds and
  result labels.
- Adds plain-language help directly beneath every manual threshold control.
- Defines the domain-support denominator as species with usable domain
  annotations; unassessed species are neither passes nor failures.
- Adds species, tissue/organism-part and identifier filtering for workflow
  v0.12.0 `candidate_expression_context_summary` resources.
- Warns that legacy zero count fields on `NOT_MAPPED` rows mean missing mapping,
  not measured biological zero expression.
- Retains every v0.3.0 tab and the immutable primary recommendation results.

## v0.3.0

<!-- source: RELEASE_NOTES_v0_3_0.md; sha256: e5160d3ad891357271a8fa12aa1d0d8d52bf8812c30f3a8882a13cc181fc6589 -->

Released 3 August 2026.

### Scientific corrections

- Headline metrics now use the evolutionary group as their decision unit.
- `final_evolutionary_candidate_prioritisation` is the authoritative source
  when available.
- Compatibility sources are deterministically deduplicated by evolutionary
  group before counts or threshold decisions.
- Groups outside the current structural top 200 are labelled
  `NOT_STRUCTURALLY_ASSESSED`, never as structural failures.

### Interactive threshold explorer

- Preserves the completed grant-aligned defaults: target species 0.90,
  mandatory species 1.00, domain support 0.80, expression support 0.80,
  structural support 0.75 and minimum member druggability 0.50.
- Provides paired sliders and exact numeric inputs.
- Separates pre-structure from structurally informed prioritisation.
- Reports pass, one-gate near-miss, fail and structurally unassessed states.
- Exports expanded evidence fields and all active thresholds as TSV.
- Reuses stored evidence and does not rerun scientific calculations.

### Portable visual review

- Adds `--pocket-review-dir` and `E3_POCKET_REVIEW_DIR`.
- Auto-discovers exactly one valid sibling `pocket_review*` bundle.
- Adds **3D structures & pockets** and **Pocket-aligned sequences** tabs.
- Embeds the self-contained selected-group viewer and MAFFT alignment.
- Returns model and OrthoFinder-group member sequence identifiers as tables and
  TSV downloads.
- Supports search by review rank, evolutionary group, lead DeepClust cluster
  and reference accession.

### Engineering

- Continues to open DuckDB read-only through the native Python `duckdb` client.
- Keeps SQL execution and filtering in DuckDB and collects only bounded results
  into pandas for Streamlit display.
- Adds defensive bundle schema/path validation, unit tests, headless application
  tests, PEP8 validation and Google-style documentation checks.

## v0.2.0

<!-- source: RELEASE_NOTES_v0_2_0.md; sha256: 37a67fb99c0840bdd4180b083ed9a97858fb6cc03b0415f1b28773f460abe599 -->

- Adds grant-focused candidate, orthology, domain, expression, ligandability,
  pocket-conservation and 3D-alignment sections.
- Adds independent column selection and TSV downloads for every section.
- Supports an integrated DuckDB, one candidate master Parquet or all current-run
  Parquets through one read-only query layer.
- Adds semicolon-aware exact accession search and a grant progress overview.
- Adds source-layout, selected-column, section, error-path and headless UI tests.
- All 22 tests pass at 98% branch-aware coverage.
