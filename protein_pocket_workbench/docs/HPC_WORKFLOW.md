# Batch preparation on Dundee HPC

**To clean and rerun predictors**, use the new
[quality-aware rerun](QUALITY_RERUN.md) and
`scripts/run_maddy_quality_pockets.slurm.sh`. It writes
`results/pockets_quality_regions_v1`. The Maddy rerun preset uses partition
barton, matching the earlier working prediction job; scheduler options can
override it.

The workflow below **reuses existing predictions**. Its E3 preset uses
partition general and does not perform quality cropping or call the predictors.

Use the supplied environment, which follows the E3 structural environment:
`usalign=20241201` and `tmalign=20240303`. Both must be available in the
environment running the Slurm worker. The README has installation commands.
If Conda is unavailable inside Slurm, export its real executable before submission:

```bash
export CONDA_EXE="$(command -v conda)"
bash scripts/submit_maddy_brca1.sh
squeue -u pthorpe001
```

The worker uses account barton, partition general, 8 CPUs, 64 GB, 48 hours.
Logs are `pocket_build-<jobid>.out` and `.err` in the submission directory.
Progress is recorded at `provenance/build_status.json` in the new resource.
An alternative compatible environment can be selected through
`POCKET_WORKBENCH_CONDA_ENV`.

Stages:

1. Validate/import existing pocket evidence, structures and exact FASTA mapping.
2. Build representative FAMSA alignment and seeded NJ bootstrap tree.
3. Run independent USalign and TMalign comparisons, four at a time.
4. Rebuild materialised DuckDB using one parent writer.
5. Publish HTML, Excel/TSV, DuckDB and the reusable app resource ZIP.

The build never calls fpocket or P2Rank. Original prepared structures are
preferred because their numbering matches the pocket records. Raw AlphaFold
folders supply missing matching models.

## Resource choices

The all-pairs preset makes 3,540 fits for 60 models. Standalone viewers and
aligned PDBs can use substantial disk space for large structures. The
64 GB/8 CPU/48 hour allocation is a starting request, not a measured BRCA1
runtime guarantee. Real BRCA1 structure files were unavailable during development.

For a smaller reference analysis:

```bash
MADDY_PROJECT="$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets"
sbatch scripts/build_project.slurm.sh \
  --input "$MADDY_PROJECT/results/pockets_all_models_v1" \
  --input "$MADDY_PROJECT/alpha_fold_models" \
  --fasta "$MADDY_PROJECT/BRCA1_all_reps.fasta" \
  --output "$MADDY_PROJECT/results/brca1_reference_resource" \
  --review-output "$MADDY_PROJECT/results/brca1_reference_review" \
  --comparison-mode reference \
  --reference fold_kag3268860_19102026_model_0 \
  --workers 4 --threads 8 --bootstrap 100
```

The example reference is an exact ID from the earlier run, not a claim that
it is the best biological reference. Reference mode leaves uncomputed matrix
cells empty.

## Fit scope

The batch default is `--fit-scope global --min-plddt 0`. Each structural
aligner receives the independent full target-chain Cα traces, including
insertions. This follows the E3 global approach. Whole-model predictions,
especially low-confidence inter-domain arrangements, need expert interpretation.

For a known reference domain, add `--start START --end END` in reference
mode. The range uses mapped FASTA positions, or prepared model positions
when no representative FASTA is supplied. The mobile region uses pairwise
sequence correspondence. Domain pockets must lie entirely inside that region.

With `--min-plddt 70`, fit residues are filtered independently on each trace.
Those results are labelled confidence-selected and are not full-model TM-score
evidence. Legacy `--fit-scope paired` uses sequence-paired residues; explicit
Kabsch requires that mode and has no TM-score.

Original rank-one evidence stays separate. `--top-pockets 5` bounds tested
cavities. `--confident-only` filters pockets before selecting them; if rank one
is excluded, its assessment is unknown, not replaced with another pocket.

## Resume

Import directories are never overwritten. Resume from an existing prepared
resource, retaining the same settings and choosing a new review directory:

```bash
sbatch scripts/build_project.slurm.sh \
  --resource /path/to/brca1_workbench_v1_1 \
  --review-output /path/to/brca1_review_retry \
  --workers 4 --threads 8
```

Exact completed fits are reused only when structures, coordinate maps,
pockets, settings and binary checksums match. Failed pairs keep their reasons.
Exit status 2 means partial comparison results were retained and exported.
Fatal input/export errors return 1.

Run one build per resource. Use `--workers` for concurrency; independent
writers on the same resource are unsupported. Workers and sequence threads
must fit the CPU allocation. Sequence and structure stages run sequentially.

## Export existing analyses without rerunning them

```bash
pocket-workbench review \
  --resource /path/to/completed_resource \
  --output /path/to/new_review
```

This creates `new_review/` and `new_review.zip`. Use a Slurm allocation for
large exports. Reviewers extract the ZIP and open `index.html`, or extract
its `app_resource.zip` and open that directory in the app.
