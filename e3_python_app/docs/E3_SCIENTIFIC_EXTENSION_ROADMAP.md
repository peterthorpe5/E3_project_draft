# E3 scientific extension roadmap

Status: implementation contract for work after Python app v0.17.0  
Last reviewed: 2026-09-02

## Non-negotiable scientific boundaries

1. The completed top-200 production cohort is immutable. New exploration must
   use a new campaign identifier, configuration snapshot, output root and
   manifest. It must never silently replace ranks, gates or results in the
   completed release.
2. Missing, unassessed, failed, excluded and negative evidence are distinct
   states. A missing value must never become zero or `False` merely to make a
   score calculable.
3. E3 HOG ranking and within-HOG member ranking answer different questions.
   Evolutionary membership is context, not proof of conserved E3 function.
4. Trimming is initially a reversible display and sensitivity operation. The
   full sequence, original coordinates, model and whole-model pLDDT summary
   remain available beside every trimmed result.
5. Every expensive stage is restartable and content-addressed by input
   checksum, tool/container version and normalised configuration.

## Delivered in v0.17.0

- Six colour-marked scientific stages replace the single flat row of 25 tabs.
  The page names, help panels, methods and data queries are unchanged.
- Every recorded structure pair has a reproducible follow-up panel with
  reference/comparison identifiers, a validated EMERALD deep link for
  canonical UniProt pairs, exact pair FASTA export, AlphaFold Database links,
  the standalone RCSB Mol* viewer and RCSB pairwise structure alignment.
- The independent pre-structure queue can export up to 1,000 ranked HOGs. The
  first 200 remain the immutable production cohort; ranks 201–1,000 are an
  exploratory queue and are not labelled structurally assessed.
- The enriched member result provides a deterministic structural-readiness
  rank within each HOG. It orders joined structure/pocket evidence,
  druggability, mapping fraction, pocket pLDDT fraction and predictor agreement,
  then uses species and raw identifier as stable tie-breaks. This is a review
  order, not an E3-function score.

EMERALD currently calculates in the browser and does not expose a documented
results API. The app therefore opens the selected pair and exports its exact
input rather than scraping or claiming to ingest an external result. EMERALD
safety windows describe alignment robustness, not biological disorder.

## Workstream A: versioned top-1,000 structural campaign

Create `top1000_exploratory_v1` as a child of the frozen pre-structure ranking.
Its manifest must record the parent release ID and checksum, included rank
interval, exact HOG IDs, sequence/model input checksums, tool versions,
container digests, thresholds, timestamps and code commit.

Each HOG and member must carry one of these explicit processing states:

- `NOT_SELECTED`
- `QUEUED`
- `RUNNING`
- `COMPLETE`
- `FAILED`
- `EXCLUDED`
- `INPUT_UNAVAILABLE`

The workflow should process ranks 201–1,000 in resumable batches while reusing
only checksum-compatible cached outputs. Publication produces new normalised
tables and a separate portable review bundle. It does not edit top-200 files.

Acceptance criteria:

- repeated execution with unchanged inputs schedules no completed item again;
- a changed model, sequence, configuration or tool version invalidates only
  dependent cached results;
- failed items can be retried independently and remain visible in inventory;
- the app labels campaign, parent release and structural-assessment coverage;
- outputs reconcile exactly to the exported 1,000-HOG input manifest.

## Workstream B: purpose-specific member ranking

Do not collapse every use case into one opaque score. Publish separate ranks:

| Rank | Purpose | Evidence | Initial status |
|---|---|---|---|
| Structural readiness | Choose a model/pocket review representative | Structure availability, selected-pocket druggability, exact mapping, pocket pLDDT and predictor agreement | Implemented as an auditable lexicographic order |
| Evolutionary representative | Choose a central or medoid-like member | Stable tree distance or sequence-distance summary from the standalone OrthoFinder app | Requires versioned bridge output |
| Motif representative | Avoid redundant sequences in motif discovery | Family/domain assignment, sequence completeness and cluster diversity | Planned with motif campaign |
| Target-species priority | Support a user-defined biological application | Taxonomic selector result plus explicit user priority | Planned; never made globally authoritative |

Every rank must expose its evidence values, eligibility status and deterministic
tie-breaks. An overall member score should be added only after the team approves
its purpose, weights, validation set and treatment of unavailable evidence.

## Workstream C: terminal disorder and Mol* structural review

### Data contract

The structural workflow must publish one row per model residue containing model
and FASTA locators, amino-acid identity, pLDDT, pocket membership, mapped E3
domain membership and an optional independent disorder score. It must also
publish proposed N- and C-terminal cut positions and the rule that proposed
them.

Low pLDDT alone is not proof of intrinsic disorder. Initial automatic proposals
should require a sustained terminal low-confidence run and should be presented
beside an independent disorder predictor when available. A proposal must not
remove a mapped E3-associated domain, selected-pocket residue or other protected
feature without an explicit warning and override.

### Interface

For each protein, provide:

- `Full model`, `Suggested core` and `Custom residue range` choices;
- a residue-position graph showing pLDDT categories, proposed terminal cuts,
  disorder evidence, protected domains and selected-pocket residues;
- whole-model and retained-core length, mean pLDDT and coverage side by side;
- original and trimmed coordinate downloads with an exact transformation
  manifest; and
- a reset action that always returns to the unmodified full model.

Mol* should be bundled at a pinned version in the portable report rather than
loaded from an unversioned remote script. Required views are pLDDT colouring,
pocket highlighting, conserved/variant residues, overlay on the fixed
reference and a side-by-side comparison. Pair summaries must retain TM-score,
RMSD, aligned-residue count, sequence identity, pocket overlap, centroid
distance and chemical-group conservation. Trimming sensitivity must be shown
beside, not substituted for, the recorded full-model comparison.

Acceptance criteria include offline operation, deterministic state snapshots,
keyboard-accessible controls, model/pocket provenance, coordinate-safe residue
selection and a browser test for each portable action.

## Workstream D: taxonomy selectors and phylogenetic context

The generic OrthoFinder application owns tree parsing, taxonomic reconciliation,
OrthoFinder 3 compatibility and alternative stringency runs. The E3 app consumes
a stable versioned export and provides E3-bounded selection and reporting.

Selectors operate on a HOG member set using composable predicates:

- **Include clade**: at least one included member is in the clade; members
  outside it are allowed and reported.
- **Only in clade**: at least one included member is in the clade and no
  included member is outside it.
- **Not in clade**: no included member is in the clade.

Multiple selectors combine with logical `AND`, making queries such as “include
Poaceae, not *Solanum tuberosum*, may occur elsewhere” explicit. Species,
subspecies, varieties and cultivars require stable taxon IDs plus source-name
and synonym audit fields. Contradictory predicates must be rejected before a
query runs.

A compact pruned phylogenetic tree should show selected and excluded clades,
species represented in the loaded release and taxa with no data. The figure is
a selection aid; it must not imply that absent release data prove biological
absence.

## Workstream E: motif discovery

Run motifs as a separate versioned campaign over exact exported sequences.
Start with family/domain-stratified sets—for example RING/U-box, HECT, RBR and
substrate-receptor classes—because pooling mechanistically different E3
families is likely to yield misleading composition signals.

For each stratum, retain both full-length and mapped-domain sequence sets,
sequence-completeness status, redundancy clusters and HOG/species partitions.
MEME Suite runs must record program, version, background model, motif-width
range, occurrence model, random seed, command line and input checksum. Use
held-out species or HOGs for validation and compare against matched non-E3 or
shuffled backgrounds. Avoid selecting and validating a motif on the same
sequences.

The app should display motif logos, locations, family/domain context,
enrichment statistics, held-out performance, member/HOG links and explicit
failure or insufficient-sample states. Profile-HMM or domain models should be
evaluated alongside short motifs where that better represents a dispersed E3
signature.

## Workstream F: 2026 human proteostasis catalogue audit

The preprint *Survey of the human proteostasis network: the
ubiquitin-proteasome system* is a useful versioned curation and validation
source, not an automatic replacement for existing seeds or scores. The
supplementary files were inspected from the Proteostasis Consortium data
download page on 2026-09-02.

The first ingestion step is an overlap/disagreement report covering accession
normalisation, E3 class/family, InterPro domain, current seed authority, HOG
mapping and E2–E3 context. New records remain `PROPOSED_FROM_UPS_2026` until
reviewed. Table S4 is figure-specific and must not be treated as a comprehensive
structure inventory.

The audit manifest should preserve source URL, access date and SHA-256 for each
supplementary workbook. The locally inspected Table S1 checksum is
`2872d268cd4ae28f098fe3bbe055f25bfba223aae97fd73a0b6722a2b7180a43`.

## Delivery order

1. Diagnose and complete the existing human/plant extension without submitting
   a duplicate cluster job; validate its manifest and output inventory first.
2. Publish the standalone OrthoFinder repository, then remove the generic
   package from this repository in a separate history-preserving change.
3. Freeze the top-1,000 campaign manifest and execute ranks 201–1,000 in
   restartable batches.
4. Publish residue-level confidence/disorder data and the pinned Mol* viewer,
   then enable reversible trimming sensitivity.
5. Add the taxonomy bridge/tree and the evolutionary-representative rank.
6. Run the family-stratified motif campaign and UPS catalogue overlap audit.

No deletion of the current generic OrthoFinder package should occur until its
new remote repository, tags and history have been verified.

## External references

- [EMERALD-UI](https://algbio.github.io/emerald-ui/)
- [EMERALD-UI source](https://github.com/AlgoBio/emerald-ui)
- [RCSB Mol* 3D View](https://www.rcsb.org/3d-view)
- [RCSB pairwise structure alignment](https://www.rcsb.org/alignment)
- [RCSB Mol* documentation](https://www.rcsb.org/docs/3d-viewers/mol*/mol*-cheat-sheet)
- [Proteostasis Consortium data downloads](https://www.proteostasisconsortium.com/data-download/)
- [UPS preprint](https://www.biorxiv.org/content/10.64898/2026.03.13.711689v3)
