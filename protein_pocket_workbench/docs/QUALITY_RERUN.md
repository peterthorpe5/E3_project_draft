# Quality-aware rerun

Use a separate run as a sensitivity analysis alongside the original full-length
predictions. Cropping removes uncertain geometry but can also remove real
contacts or create new exposed surfaces. It cannot repair an inaccurate fold.
For BRCA1, inspect the RING and tandem BRCT context; do not assume automatic
confidence blocks identify those biological units correctly.

## Preparation and evidence

1. Discover every original PDB/mmCIF recursively, excluding MSA/template folders.
2. Select one protein chain, retain heavy atoms and original author labels,
   and calculate residue-mean pLDDT from the per-atom B fields.
3. Reconcile the same-model PAE sidecar with that full chain before cropping.
4. Retain contiguous confidence-supported candidates or supplied curated ranges.
5. Record all proposed range decisions, rejected ranges and excluded sequence
   spans; write each retained range to its own mmCIF.
6. Run fpocket, independent P2Rank prediction and same-cavity P2Rank rescoring.
7. Import the new evidence; attach cut-boundary and uncertain-context flags.
8. Build corresponding-region reference fits with both structural tools,
   full-representative protein alignment, exploratory tree and offline review.

The rules are explicit heuristics:

| Choice | Default |
| --- | --- |
| Core anchor | Residue-mean pLDDT ≥70 |
| Maximum internal non-core stretch | 30 residues between anchors |
| Backbone gap | Adjacent CA distance >5 Å |
| Candidate padding | Up to 5 residues, with no overlap between neighbours |
| Minimum retained length / core count | 50 / 40 residues |
| Minimum core fraction | 0.5 |
| Symmetric PAE | max(PAE[i,j], PAE[j,i]) |
| Core-pair consistency | ≥80% of off-diagonal core pairs with symmetric PAE ≤10 Å |
| Artificial-cut proximity | Any lining CA within 8 Å of the first/last three CAs at a new terminus |
| Uncertain-context proximity | Any lining CA within 6 Å of a retained residue CA with pLDDT <50 |

For automatic proposals, a new core anchor starts a new group when the intervening
non-core run is too long, a backbone gap intervenes, or fewer than 80% of its
links to existing group anchors pass the PAE threshold. The whole candidate is
then assessed against the all-core-pair rule. Short low-confidence loops remain
in place. Candidates that fail are recorded rather than rescued by stitching
disconnected residues.

New cut flags also recognise an input structure that is itself an explicitly
mapped fragment of a longer supplied FASTA. Proximity checks use CA coordinates
as transparent approximations; they are not atomic surface or cavity proofs.
The first/last three residues at a cut are used so a cavity just beside the
exact terminal atom is not missed by a single-residue boundary proxy.

No atoms are energy-minimised, remodelled, capped or rescaled. Residue-mean
confidence and retained coordinates do not improve because a region was cropped.
Hydrogens, waters, metals/cofactors and other chains are removed by the original
protein-preparation code. Zinc, BARD1/other partners, biological assembly and
ligand-induced conformations therefore remain unassessed. Retain the original
predictions when interpreting missing or newly created pockets.

## PAE mapping

AF Server `job_model_0.cif` maps exactly to `job_full_data_0.json`, and
similarly for other numbered models. Native AF3 `job_model.cif` maps to
`job_confidences.json`. An exact `<model_stem>_pae.json` is also accepted.
Multiple matching sidecars are an error.

The parser supports `pae` and AFDB `predicted_aligned_error` matrices.
Explicit selected-chain token residue IDs are used when present. Otherwise
selected-chain token order is accepted only when the count equals the complete
selected protein chain and author numbers have no missing positions/insertion
codes. Unlabelled matrices must match the complete single chain. Other-chain
and ligand tokens are never assigned to protein residues by truncating a matrix.
Sidecars have a 1 GiB JSON bound and matrices a 10,000-token bound.

Unmappable/invalid PAE fails that model's preparation and is recorded in
`Model_QC.tsv`. Missing PAE rejects automatic/curated candidates by default.
The explicit `--allow-missing-pae` override permits prediction of regions
without PAE; those pockets do not pass the primary quality screen. Invalid
PAE is not silently ignored by that override.

## Exact FASTA mapping

Parents match supplied FASTA by exact sequence or explicit unique exact fragment
mapping. No accession is inferred from the filename. Identical FASTA records
require an explicit mapping to resolve identity. Unmatched models receive a
separate structure-derived sequence and retain their unmapped-parent status.

For each crop the workflow uses the audited parent sequence interval. When the
crop sequence occurs more than once in the parent, a separate fragment FASTA
record prevents an invented sequence offset. Full-parent bounds remain in the
QC table; that crop cannot be confidently highlighted on the full representative
MSA through an ambiguous repeated substring. Prediction replicates keep
separate pocket-annotation rows. All supplied representatives, including those
without a model, remain in the full-sequence MSA/tree.

## Curated ranges

Where biological ranges are known, provide an actual tab-separated file such as:

```tsv
sequence_id	region_name	start	end	coordinate_system
my_exact_FASTA_identifier	known_unit_A	10	110	sequence
my_exact_FASTA_identifier	known_unit_B	250	450	sequence
```

Those numbers are **illustrative**, not BRCA1 domain coordinates. Use validated
coordinates for your own sequences. Each row needs either `sequence_id` or
`sample_id`, a region name, inclusive start/end and optionally
`coordinate_system` (`sequence` by default, or `model` for one-based
parent-model indices). A sample_id row matches only that exact model.

Sequence ranges require an exact supplied FASTA mapping and complete coverage.
Overlapping ranges fail. Models without a matching row receive no retained
regions. Curated ranges still pass through confidence/PAE checks; a name does
not bypass quality assessment. For cross-model curated comparisons, explicit
region names must agree when both sides are curated.

```bash
QUALITY_RESULT_ROOT="$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/results/pockets_curated_v1" \
  sbatch scripts/run_maddy_quality_pockets.slurm.sh \
  --regions /absolute/path/to/curated_regions.tsv \
  --mapping /absolute/path/to/parent_mapping.tsv
```

The optional parent mapping uses `sample_id`, `sequence_id` and optional
`chain`. Use exact original coordinate filename stems as sample IDs.
Explicit `hog_id`, `source_accession` and `source_url` are carried to child
models for the HOG/source-link pages. Computational region group labels remain
separate from explicit HOG membership.

## Pocket ranking and primary screen

All method records and native scores remain in the predictor output and native
app resource. The fpocket review rank follows P2Rank rescoring, or the original
labelled fpocket fallback when unavailable. P2Rank's independent sites are
separate evidence. Rescoring uses the experimental B-factor-independent
`rescore_2024` profile; the prediction profile is `alphafold`.

The primary preparation/context screen requires:

- Every lining residue mapped to coordinates.
- The original local rule (default ≥80% of lining residues with mean pLDDT ≥70).
- Assessed within-region PAE from an accepted candidate.
- No artificial-cut or very-low-confidence retained-context proximity flag.

All records retain their original rank. Comparisons only use passing original
ranks ≤5 by default. Excluding rank one yields **not assessed** rank-one
evidence; a different cavity is not promoted to rank one. The model browser's
quality filter can be unchecked to inspect all evidence. Standalone model pages
retain all pockets and label the input as a cropped-region analysis; use the
tables for context flags.

## Structural comparison plan

The planner aligns full parent sequences and requires ≥70% coverage of each
retained region by correspondence to the other retained region. This is a
sequence-based eligibility heuristic, not proof of homology/domain equivalence.
Region number/name alone does not establish a correspondence.

Connected eligible ranges form labelled computational groups, never HOG claims.
In `matched_reference` mode, choose the region with the most direct eligible
links, then highest mean pLDDT, then stable ID. Compare it only to directly
eligible neighbours. Indirect-only members are not forced into a reference fit.
Full pair eligibility remains in `comparison_plan.tsv`.

Both USalign and TMalign fit complete independent cropped traces with minimum
fit pLDDT 0, retaining short internal loops. Scope is `cleaned_region`.
TM-scores and CA coverage refer to these inputs, not the original full protein.
Use `--comparison-mode matched_all` for every directly eligible pair or
`none` to omit structural fitting. The tree remains exploratory NJ p-distance,
with 100 seeded column bootstrap replicates by default; it is not a species tree.

## Resume, monitoring and failures

```bash
squeue -u pthorpe001
tail -f "$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/results/pockets_quality_regions_v1/workflow.log"
```

Slurm stdout/error are `maddy_quality-<jobid>.out/.err` in the submission
directory. Predictor progress is also in `03_pocket_predictions/pipeline.log`.
Status is in `workflow.json`; final exact locations are in `latest_outputs.json`.

Exit code 0 means complete; 2 means usable partial/preparation results exist
with exclusions/failures to inspect; 1 means a fatal error. The log and audit
identify affected models. Slurm may mark exit 2 FAILED despite retained partial
results. Do not interpret that status as total loss of output.

Resume requires identical original inputs, cleaning, analysis settings and
prediction thread/timeout settings. Immutable prepared-input checksums are checked.
Completed predictions are reused when report/tool identities match; failed
prediction samples are retried by the original engine. Exact comparison and
sequence analysis identities support downstream reuse.

If prediction evidence changes after a retry, a numbered native resource is
created (`04_workbench_002` etc.) and the previous one is retained. Every new
review export receives a new name; `latest_outputs.json` identifies the latest.
Changed source/settings require a new results directory instead of overwriting.

The outer workflow uses an OS-released file lock. The inherited predictor uses
an exclusive `03_pocket_predictions/.run.lock`. A forced termination can leave
that inner marker behind. **Only after confirming with squeue/process checks
that the old workflow is no longer running**, remove that one stale marker
and resubmit with `--resume`. Never remove a live job's lock.

The Maddy script requires its model directory and FASTA. For another project
use `scripts/run_quality_pockets.slurm.sh` or the named-option
`pocket-workbench-rerun` command directly. No Python is embedded in either shell.

## Sources and interpretation

- [AlphaFold 3 output specification](https://github.com/google-deepmind/alphafold3/blob/main/docs/output.md)
- [EMBL-EBI AlphaFold 3 quality assessment](https://www.ebi.ac.uk/training/online/courses/alphafold/alphafold-3-and-alphafold-server/how-to-assess-the-quality-of-alphafold-3-predictions/)
- [P2Rank and its experimental rescoring profile](https://github.com/rdk/p2rank)
- [fpocket source](https://github.com/Discngine/fpocket)
- [E3 structural workflow reference](https://github.com/peterthorpe5/E3_project_draft)

The thresholds and automatic region-selection algorithm above are workbench
policy choices, not a published validated domain-segmentation or ligandability
method. Evaluate robustness against the original full-length predictions and,
where appropriate, explicit domain/assembly models.
