# ARIA plant E3 Python reporter

Version **0.21.4** adds **Prepare Protein Imager data** beside each relevant
link: External links, Ligandability, and the plant and human/plant structure
reviews. Choose a HOG or protein, prepare the files, download an individual
mmCIF or a HOG ZIP, then load its `.cif` files in Protein Imager. Selected
reviews supply their current group automatically. Preparation retrieves full
AlphaFold coordinate files without fetching unnecessary PAE data.

Version 0.21.3 makes **External links** a working HOG-based preparation page.
Choose a HOG, select proteins, open populated Mol*/AlphaFold/EMERALD links,
download an exact pair FASTA, or explicitly prepare selected-member models.
The prepared models can be downloaded as an Inspector ZIP or an individual
mmCIF for manual Protein Imager loading. Source, HOG and selection changes
invalidate prepared downloads. Existing links remain in place.

Version 0.21.2 adds **Protein Imager** to Ligandability and the selected
structure/pocket reviews. A shared **External links** page under Information
and Structural prioritisation lists the existing tools and explains their
required inputs. Pair-specific links and model-bundle preparation remain on
their existing pages. Protein Imager uses a manual upload of the retained
PDB/mmCIF model and manual pocket-residue selection; the link does not transfer
models or annotations. See [the external tools guide](docs/EXTERNAL_LINKS.md).

Version 0.21.1 restores **All results** under **Candidate discovery** and
keeps its **Search & results** shortcut. Both locations provide identical
complete downloads. Complete HOG/OG searches now open stored ranks and member
metadata directly; full evidence dossiers/counts are loaded on request and
cached while you inspect them. Timed spinners show work in progress. All results
defaults to the published candidate table, with joined previews/counts optional;
complete downloads always include every matching row and field.

Version **0.21.0** adds a top-level **🔎 Search & results** section. **Protein &
HOG search** searches the complete loaded resource, resolves proteins to their
recorded groups, shows original ranks with their source fields, and exports a
complete linked evidence dossier. **All results** now filters before preview
limiting and offers separate complete TSV/Excel downloads containing every
matching row and field, regardless of `--max-rows` or hidden preview columns.
See [Search and complete downloads](docs/SEARCH_AND_DOWNLOADS.md).

Version **0.20.0** refines the **Protein research workbench** with a Start here
page, a generic three-step workflow, optional E3 entry point, contextual
question-mark help, FASTA examples, a glossary and downloadable guidance.
Mapping-to-retrieval and result-to-analysis buttons carry exact selections
between pages. Jobs now explains status and next steps; technical JSON and logs
sit inside expanders. Optional model/annotation forms explain missing setup and
show only relevant controls. The installed research profile and existing jobs
remain compatible. See [the workbench guide](PROTEIN_RESEARCH.md).

Version 0.18.8 introduced the Streamlit companion's **C-terminal
conservation** page. It presents a compact selectable group summary, reviewed
taxonomy filters, species and sequence-coverage evidence, available E3/seed
annotations and independently filterable member detail. The orthology-first
screen retains the default of terminal asparagine (`N`) in at least 80% of
assessed plant members. Arabidopsis supports experimental follow-up and human
members remain a separate comparison. See the
[C-terminal review guide](docs/C_TERMINAL_CONSERVATION_REVIEW.md) for exact
denominators, taxon semantics and export scope.

Version 0.18.4 introduced an
easy-to-find **Within-HOG ranking** page, extended composable exact-taxon and
clade filters to reviewed input-specific taxonomy mappings, and compared
full-model with retained-core mean pLDDT in the reversible terminal-display
workflow. Unknown species remain explicitly unmapped.

For the persistent University RHEL 9 deployment of this milestone application, see
the [tested server deployment guide](deployment/rhel9/README.md). That deployment is
separate from the experimental OrthoFinder interrogation viewer.

Both applications use the same release contract and answer the same grant-facing
questions across candidate prioritisation, OrthoFinder grouping, domains,
expression, ligandability, pocket conservation, 3D alignment and provenance.

The 29 pages include a top-level **Search & results** section and six
colour-marked scientific stages:
information, candidate discovery, E3 orthology context, structural
prioritisation, structural comparison, and chemistry and outputs. Search and
All results are available directly, without entering the chemistry section.
Only the selected
section and page are queried and rendered, so an interaction no longer executes
every application page. Immutable structural-review bundles are fully validated
once per application process and then reused; explicit deployment validation is
unchanged.

Recorded structure pairs provide validated EMERALD hand-offs for canonical
UniProt accessions, exact selected-pair FASTA export and AlphaFold Database
links. Mol* actions now load each exact AlphaFold accession rather than an empty
viewer; the unreliable RCSB computed-model pair hand-off is deliberately not
offered. External results are not scraped or written back into the read-only
release. The enriched member result also adds a deterministic
structural-readiness rank within each HOG without changing the authoritative
HOG ranking.

The embedded group and pairwise 3D views provide reversible N- and C-terminal
display trimming. The viewer presents a sustained low-confidence recommendation
first, keeps its sensitivity settings collapsed, and offers manual fine-tuning
separately. Pair reviewers may apply independent recommendations to both
structures. When residue-level pLDDT is present, a 460-pixel full-width graph shows
confidence zones, exact hover values, coverage, current retained residues,
full-model and retained-core mean pLDDT, their difference, and applied versus
proposed terminal regions. Missing pLDDT produces an explicit
recovery message rather than an empty plot. These controls never rewrite the
model, alignment, pocket evidence, score or ranking, and low pLDDT is not
labelled as proof of intrinsic disorder.

The human-and-plant 3D tab now uses one synchronised evolutionary-group
selection for its explicit reference/mobile protein comparison, selectable
structures and retained pockets, and pocket-annotated MAFFT/FASTA view. Its
methods state how plant representatives and structural references were chosen,
how all exact human HOG members were handled and why extension ranks can be
non-contiguous.

This reporting release foregrounds strict 3D pocket-position support, the
separate conserved-pocket/chemical gate and assessed-member druggability in
the complete HOG results. Human, Arabidopsis, rice and barley representatives
are reported separately. Unified-search matches now have selectable/exportable
columns, expression identifiers accept pasted lists with direct value-table
downloads, and expression heatmaps use a white-to-red low-to-high scale.

The app is read-only. It opens a completed DuckDB directly or registers Parquet
files as views in an in-memory DuckDB. Screen previews have a row cap and only
bounded preview tables are collected into pandas. Explicit complete exports
stream every matching row in batches and include every field. The final
download is held by Streamlit until the session/download cache is released;
large exports should therefore be requested deliberately. The Python app uses
the native `duckdb` Python client for SQL execution; it does not use `duckplyr`,
which is an R-specific dplyr translation layer.

## Result-source modes

Choose exactly one:

```bash
# Recommended complete release
./run_e3_python_app.sh \
  --resource-duckdb /path/to/e3_integrated_resource.duckdb \
  --pocket-review-dir /path/to/portable_release/pocket_review \
  --human-plant-review-dir /path/to/human_plant_extension/pocket_review \
  --taxonomy-map /path/to/reviewed_taxonomy_mapping.tsv \
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
`E3_RESOURCE_RUN_DIR`, `E3_EXPRESSION_DUCKDB`, `E3_POCKET_REVIEW_DIR`,
`E3_HUMAN_PLANT_REVIEW_DIR`, `E3_TAXONOMY_MAP` and `E3_MAX_TABLE_ROWS`.

The pocket-review option is additive and optional. When it is omitted, the app
auto-discovers the bundle only if exactly one valid direct child beginning with
`pocket_review` is beside the selected DuckDB/Parquet, or inside the selected
run directory. It never guesses between multiple bundles. The separate
human-and-plant review is never auto-discovered: it must be selected explicitly
so it cannot be confused with the immutable plant-only baseline.

The taxonomy-map option is also optional. Without it, the app uses its packaged
13-species snapshot. With it, exact source labels and reviewed lineages can
cover new species, subspecies, varieties and cultivars. The complete schema and
fail-closed review rules are documented in
[`docs/CUSTOM_TAXONOMY_MAPPING.md`](docs/CUSTOM_TAXONOMY_MAPPING.md).

## Interface

The reporter provides:

- a top-level Search & results section and six ordered, colour-marked
  scientific stages covering 30 maintained pages, from release information
  through discovery, orthology, structure and outputs;
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
- a dedicated **C-terminal conservation** page that groups proteins by HOG or
  OG before applying an exact terminal-sequence rule. It defaults to `N` and an
  80% plant-member match, accepts multi-residue endings, lets users narrow the
  reviewed target-plant set, reports plant-member and plant-species breadth
  separately, can require an Arabidopsis match, keeps human evidence outside
  the plant denominator, and exports group/member tables plus available sequence
  FASTA. The current candidate-linked sequence relation is labelled as a
  pilot-data scope rather than a whole-proteome screen;
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
- an **E3 seed catalogue** listing the exact inherited identifiers and, when
  published, their exact authority-level names, annotations and provenance.
  Older resources fall back to clearly labelled cluster-associated annotation;
  accession-matched sequences can be downloaded as FASTA, and the displayed
  catalogue is also downloadable as TSV or formatted Excel. Its dedicated hard
  cap can be increased to 100,000 records independently of normal previews;
- species, tissue/organism-part and identifier filters for the normalised
  candidate-by-expression-context relation, when supplied by workflow v0.13.0
  or later;
- a separate Threshold explorer with the completed analysis defaults, paired
  sliders and typed values, simultaneously displayed pre-structure and
  structurally informed candidate lists, explicit `PASS`, `NEAR_MISS`, `FAIL`
  and `NOT_STRUCTURALLY_ASSESSED` labels, expanded candidate, seed, domain,
  expression and missing-evidence fields, HOG composition, human and
  Arabidopsis representatives, plus separate TSV and formatted Excel exports;
- a dedicated **Independent structural-review shortlist** returning the top
  200 root-level `N0.HOG…` groups by default, expandable to an explicitly
  exploratory top-1,000 queue. It uses the
  authoritative ranking from all recorded discovery, orthology/species,
  E3-domain and expression evidence, with an optional pre-structure-pass filter.
  Existing AlphaFold models, pockets, druggability, mapping, alignment and 3D
  results are excluded from this decision table but retained in other tabs;
- a dedicated **Within-HOG ranking** page where one root HOG can be selected
  directly. Its independently numbered member rows expose the exact structural
  evidence used in the deterministic review order, keep unassessed members
  visible by default and provide focused TSV and Excel downloads. This review
  order does not replace the HOG-level ranks or claim E3 function;
- a separate **HOG model comparison** page where one root HOG and any subset of
  its recognised UniProt members can be selected. All members are selected by
  default. The app retrieves each available AlphaFold Database mmCIF model and
  optional PAE document, skips unavailable models with an explicit audit record,
  and creates one ZIP for the user to download and manually upload to the
  external AlphaFold 3 Multi-Model Inspector. The archive includes
  `manifest.tsv`, source URLs, checksums and an interpretation guide. These are
  models of different HOG members, not alternative AF3 conformers of one
  protein; unavailable AF3-specific scores must not be treated as zero;
- a linked Visual explorer containing a selectable multi-axis candidate
  landscape, a cross-species expression heatmap, exact species-by-tissue
  profiles and the bounded evidence tables behind every selected candidate;
- a scientifically gated Volcano eligibility view, which activates only when a
  relation contains both a recognised differential-expression effect size and
  a P/FDR/Q-value field; the current absolute Expression Atlas release is not
  misrepresented as a differential analysis;
- a plant-only 3D-alignment view that opens the exact self-contained,
  interactive US-align/TM-align structural superpositions used by the analysis,
  alongside the established evidence map and tables. A separate **Human & plant
  3D alignment** view retains the recorded plant reference, adds exact human HOG
  members, and provides the combined superpositions, rotatable structures and
  pockets, pocket-annotated MAFFT alignments, evidence tables, HTML, TSV, Excel
  and FASTA downloads. Human members without an assessable AlphaFold model or
  qualifying pocket remain visible in a separate exact-sequence inventory and
  are not mislabelled as pocket-aligned evidence. Current report pages download
  the rotated 3D canvas and complete alignment directly as PDFs;
- a reproducible external follow-up panel for every selected structure pair,
  with pair roles, validated EMERALD and AlphaFold links where canonical
  UniProt accessions exist, exact two-sequence FASTA, and RCSB Mol* and pairwise
  structure-alignment actions. EMERALD safety windows are labelled as alignment
  robustness rather than disorder calls;
- searchable HOG/orthogroup, DeepClust cluster, rank and accession choices,
  alongside downloadable OrthoFinder member sequence/model identifiers;
- a separate column multiselect and row limit for every section;
- a replacement complete-resource search accepting one item or a pasted
  newline/comma/semicolon/tab list. Smart, exact and literal-contains modes
  recognise names, root HOG IDs, legacy OG IDs, E3 seeds, accessions, entries,
  genes and DeepClust identifiers; every hit retains the input term, relation,
  matched fields and all source columns, with TSV and Excel downloads;
- complete selected-group dossiers following recorded group, contributing-cluster
  and protein identifiers. Rankings, members, annotation and other linked raw
  evidence retain separate source tables and linking-column provenance. Original
  group ranks are resolved independently for each stage, with their exact source;
- an **All results** browser whose default enriched overview joins one row per
  root HOG to human and Arabidopsis representatives, canonical pre-structure
  and post-structure ranks, complete source-ranking fields and membership
  summaries. A separate enriched member view repeats that context beside every
  HOG member; all unmodified raw relations remain selectable for exact audit;
- the same within-HOG structural-readiness rank in the enriched member result. Joined
  structural evidence and its component values remain visible, missing evidence
  is not converted to zero, and the rank is not presented as an E3-function
  score;
- provenance and QC views; and
- a collapsed **❓ How to use this tab** panel on every primary tab, with
  tab-specific operating instructions followed by an explicit description of
  the tables, plots or downloads that the tab yields;
- a separate collapsed **ⓘ Methods and thresholds** panel on each relevant
  scientific tab. These panels record the production methods, gates, ranking
  weights, missing-evidence rules and interpretation boundaries without
  duplicating or changing the active sensitivity controls. The 3D-alignment
  panel includes the clickable Xu and Zhang (2010) reference supporting the
  approximate TM-score 0.50 fold-similarity boundary;
- on-demand vector-PDF downloads for every native application graph. These use
  the packaged Kaleido renderer and are prepared only when requested; and
- separate complete TSV archives and Excel workbooks on Search and All results;
  these include every matching row and field, have count manifests and field
  dictionaries, and split Excel tables across worksheets rather than dropping
  excess rows. Excel refuses overlong cells with guidance to use TSV;
- paired TSV and formatted Excel downloads of other displayed result tables.
  These preview exports contain the same bounded rows and selected columns, with visible cell
  gridlines, explicit borders, filter arrows, frozen headers, banded rows,
  centred body values, 10-point wrapped narrative text, bounded readable widths
  and capped long-text row heights, plus data-appropriate display formats. A
  second **Column definitions** worksheet defines every exact exported header,
  including its type, unit, rule, caution, source and related fields. Numeric
  source values remain exact;
  only their display is shortened.

Wide in-app result tables give every column an explicit readable minimum width,
then use a horizontal scrollbar and a bounded vertical viewport with a
stationary header. Numeric display is shortened to three
decimal places (or three significant figures for P/E/FDR/Q values) without
changing the exported data. The main navigation labels wrap across as many rows
as the window requires, so sections are visible without tab-scroll arrows.

The phased scientific and technical contract for top-1,000 processing,
terminal-disorder sensitivity, external Mol* hand-offs, taxonomy selectors,
motif analysis, incremental updates and standalone OrthoFinder ownership is recorded in
[`docs/E3_SCIENTIFIC_EXTENSION_ROADMAP.md`](docs/E3_SCIENTIFIC_EXTENSION_ROADMAP.md).


  for the generic selection-coverage tree in the standalone
  `orthofinder-results` repository.

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

The release quality gate includes focused human-HOG, plant–human-HOG,
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
├── human_plant_structural_extension/
│   ├── plant_pocket_review/
│   │   ├── structural_alignment/
│   │   ├── groups/
│   │   ├── sequences/
│   │   ├── tables/
│   │   ├── provenance/
│   │   └── index.html
│   └── pocket_review/
│       ├── structural_alignment/
│       ├── groups/
│       ├── sequences/
│       ├── tables/
│       ├── provenance/
│       └── index.html
└── SHA256SUMS.txt
```

Launch it on macOS with:

```bash
PORTABLE_ROOT="/Volumes/One Touch/2026_E3_protac/portable_visualisation_release_top200_20260803"

./run_e3_python_app.sh \
  --resource-duckdb "${PORTABLE_ROOT}/e3_integrated_resource.duckdb" \
  --pocket-review-dir \
    "${PORTABLE_ROOT}/human_plant_structural_extension/plant_pocket_review" \
  --human-plant-review-dir \
    "${PORTABLE_ROOT}/human_plant_structural_extension/pocket_review" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501
```

The portable HTML pages embed the C-alpha traces, pocket mappings, alignment,
CSS and JavaScript. The app does not need cluster access or a remote structure
service after the release has been copied.

Pocket-review bundles generated by structural-alignment v0.6.0 retain explicit
ModelCIF local pLDDT in their browser payloads, enabling quality-aware terminal
suggestions and pLDDT colouring in Python app v0.18.0. Bundles generated by
structural-alignment v0.5.0 still receive manual N/C residue-count trimming in
memory; regenerate only the portable review report when the pLDDT-aware controls
are required. No structure prediction or structural alignment rerun is needed.

Pocket-review bundles also provide direct
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

## Protein research workbench (v0.19.1)

For selected DeepClust exports without a global database on your laptop, see
[DEEPCLUST_EXCHANGE.md](DEEPCLUST_EXCHANGE.md). Stage 3 → Protein research workbench
→ Discover → Import extracted cluster accepts the upstream tool's per-cluster
FASTA files. Extraction still requires a database holder; cloning its tool alone
does not provide remote sequence access. The official `SEQID/CLUSTERID` sequence
map schema is supported.

Stage 3 now includes a generic protein-family workbench: global DeepClust linking
and complete indexed retrieval, audited stricter subclusters, MAFFT/statistics,
JBrowse MSA, Alignment Viewer 2, Nightingale, self-hosted Auspice integration and
optional ESMFold/InterProScan/eggNOG jobs. The E3 input adapter is separate from the
generic engine, which also runs without an E3 resource.

See [PROTEIN_RESEARCH.md](PROTEIN_RESEARCH.md) for prerequisites, source schemas,
scientific limits, worker/service setup and a complete walkthrough. Configure a
writable sidecar using `config/protein_research.example.toml`, then add
`--research-config /absolute/path/research.toml` to your existing E3 launch command.
The DeepClust release and optional annotation/model databases are separate operator
installations; they are not downloaded automatically when installing the app.
