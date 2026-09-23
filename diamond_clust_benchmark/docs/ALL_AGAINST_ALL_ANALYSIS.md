# All-against-all clustering comparison

## Purpose

The original benchmark asks whether each candidate is at least 10% faster than
the DIAMOND 2.2.3 operational reference while reproducing its clustering. That
is a backward-compatibility question. It does not establish that 2.2.3 is
biologically correct.

The all-against-all analysis compares every retained clustering result with
every other result. It is intended to show whether differences are associated
primarily with the DIAMOND version, DeepClust versus LinClust, exact versus
approximate identity, or the fast-final-clustering setting.

Agreement between several methods is not proof of biological correctness.
Independent curated families, domain architectures, phylogeny, known
orthologues and paralogues, and downstream E3 results are still required for
that judgement.

## Metrics

The script produces the following complementary measurements.

- Pairwise F1 and same-cluster-pair Jaccard measure agreement among unordered
  protein pairs placed in the same cluster. They are mathematically related,
  so Jaccard improves interpretation but is not independent evidence.
- Adjusted Rand index corrects partition agreement for chance.
- Normalised mutual information measures shared clustering information.
- Variation of information and its normalised form measure information lost
  or gained when moving between two partitions. Lower values indicate closer
  results.
- Directional pair recall distinguishes separation of source pairs from
  additional target pairs.
- Directional split and merge summaries count source clusters distributed
  across multiple target clusters and the members affected by those changes.
- Best-match cluster Jaccard is reported as macro, median and member-weighted
  values, including size strata. This prevents the global result from being
  interpreted solely through the largest clusters.
- Exact-match counts identify clusters whose complete membership is unchanged.
- E3 sentinel metrics include aggregate-neighbourhood Jaccard and a separate
  Jaccard value for every matched sentinel sequence.
- Repeat stability is calculated when at least two retained membership tables
  exist for a method.

## Current repeat limitation

The completed benchmark retained `clusters.tsv` for the configured quality
repeat only. Its other repeats retained timing and provenance but not their
full cluster memberships. The new script will therefore write
`not_estimable_only_one_retained_membership` for repeat stability in the
current run. This is an honest missing measurement, not an analysis failure.

Repeat stability can be calculated automatically for a future run when two or
more `repeat_<n>/clusters.tsv` files are retained for each case. The timing
tables cannot be used as a substitute for membership stability.

## Dundee cluster command

After pulling the updated repository, activate the existing environment and
enter the package directory:

```bash
cd /gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/E3_project_draft
git pull --ff-only origin main
conda activate e3_discovery
cd diamond_clust_benchmark
mkdir -p slurm_logs
```

Submit the analysis:

```bash
./scripts/submit_all_against_all_slurm.sh \
    --config config/full_onekp_cluster.v0_1_0_20260921.yaml \
    --run-root /gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/diamond_clust_benchmark_results/full_onekp_plus_v0_1_0_20260921 \
    --output-directory /gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/diamond_clust_benchmark_results/full_onekp_plus_v0_1_0_20260921/all_against_all_v0_1_0_20260923 \
    --account barton \
    --partition barton \
    --cpus 2 \
    --memory 256G \
    --duckdb-memory 200GB \
    --time 4-00:00:00 \
    --conda-env e3_discovery \
    --job-name diamond_all_pairs_v0_1_0
```

Two DuckDB threads are deliberate. Each pair is processed sequentially with a
200 GB memory ceiling and spill storage in `SLURM_TMPDIR` where available. This
reduces the risk of another report-stage out-of-memory failure.

If the sentinel path in the configuration is not the intended file, add:

```bash
    --sentinel-ids-tsv /absolute/path/to/sentinel_ids.tsv
```

The sentinel table must be a headered TSV with one `sequence_id` column.

## Monitoring and recovery

The submission command prints the job identifier and both Slurm log paths.
Monitor it with:

```bash
squeue -j JOB_ID
tail -f slurm_logs/slurm-JOB_ID.out
tail -f slurm_logs/slurm-JOB_ID.err
```

Each completed method pair is checkpointed. If the job stops before creating
`COMPLETE`, resubmit the same command with `--resume`. Input path, size,
modification time and available checksum metadata are checked before a
checkpoint is reused.

Do not use `--resume` after changing or replacing membership inputs. Stale
checkpoints are rejected, but a new versioned output directory provides the
clearest provenance.

## Outputs

The analysis directory contains:

- `tables/method_cluster_summary.tsv`;
- `tables/pairwise_method_comparisons.tsv`;
- `tables/directional_split_merge_summary.tsv`;
- `tables/size_stratified_best_match.tsv`;
- `tables/sentinel_method_comparisons.tsv`;
- `tables/sentinel_per_sequence_comparisons.tsv`;
- `tables/repeat_stability.tsv`;
- PNG and PDF heatmaps, cluster profiles, a split/merge figure and the
  variation-of-information dendrogram under `figures/`;
- `reports/all_against_all_summary.html`;
- input, timing and analysis provenance under `provenance/`; and
- a `COMPLETE` marker written only after all tables, figures and provenance
  have been produced successfully.

## Direct non-Slurm invocation

For a small pilot or an already allocated interactive node:

```bash
python scripts/compare_all_memberships.py \
    --config /absolute/path/to/config.yaml \
    --run-root /absolute/path/to/completed/run \
    --output-directory /absolute/path/to/new/all_against_all_output \
    --threads 2 \
    --memory-limit 200GB \
    --temporary-directory auto \
    --formats png pdf
```

Run `python scripts/compare_all_memberships.py --help` for all named options.
The script has no positional arguments and never writes comma-separated
outputs.
