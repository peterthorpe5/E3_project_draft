# Cluster runbook

## Before submission

1. Confirm the input FASTA and optional sentinel TSV are immutable and readable.
2. Copy the production template to a new versioned YAML and choose a new output
   root. Never point at a completed benchmark root.
3. Confirm `e3_discovery` resolves DIAMOND 2.2.3 and
   `diamond_clust_2_2_8` resolves DIAMOND 2.2.8.
4. Install this package into the controller environment.
5. Run `validate-config`, then `run_workflow.sh --dry-run`.
6. Check free space at the output root and the selected scratch filesystem.

Useful preflight commands:

```bash
conda run --name e3_discovery diamond version
conda run --name diamond_clust_2_2_8 diamond version

conda run --name e3_discovery \
    diamond-clust-benchmark validate-runtime \
    --config config/full_onekp_cluster.v0_1_0.yaml \
    --output /tmp/diamond_clust_runtime_preflight.json
```

## Submission and monitoring

Submit with `scripts/submit_benchmark_slurm.sh`; its response prints the Slurm
job identifier and persistent log paths. Monitor without modifying outputs:

```bash
squeue -u "${USER}"
tail -F slurm_logs/slurm-JOB_ID.out
```

The controller uses one allocation and deliberately serialises all benchmark
cases through the `benchmark_slot=1` Snakemake resource. Parallelising cases
would invalidate the fairness assumption.

## Restart behaviour

Rerun the same command after an interruption. Snakemake retains complete
case-repeat directories. A pre-existing incomplete directory is moved into the
configured `failed/` directory with a timestamp and random suffix. A complete
directory is immutable; use a new output root to change the design or rerun a
completed observation.

Scratch data are disposable. Persistent logs, measurements, membership
summary, manifest and failure record are kept under the output root.

## Report-only recovery

When every case/repeat contains `COMPLETE` but the final report fails, do not
rerun the benchmark cases. Submit only the report with the existing immutable
configuration and result root:

```bash
./scripts/submit_report_slurm.sh \
    --config config/full_onekp_cluster.v0_1_0.yaml \
    --run-root /absolute/path/to/the/existing/benchmark/root \
    --account barton \
    --partition barton \
    --cpus 2 \
    --memory 256G \
    --time 2-00:00:00 \
    --conda-env e3_discovery
```

This launcher invokes the reporting CLI directly and therefore cannot execute
DIAMOND. Large DuckDB joins may spill below `<run-root>/scratch/quality`; each
comparison removes its temporary directory after the connection closes.

## Acceptance checks

After completion, require all of the following:

- `reports/report_manifest.json` has `status: COMPLETE`;
- every case/repeat contains `COMPLETE`, `metrics.tsv` and
  `case_manifest.json`;
- expected FASTA counts and checksums match the input profile;
- all quality-repeat memberships contain exactly the expected member count;
- `decision_summary.tsv` reports each speed and quality component separately;
- the HTML conclusion agrees with the TSV decision table.

If no candidate passes, retain the report as a valid negative result. Do not
weaken the concordance threshold or remove slow repeats after inspecting the
outcome. Design a new versioned experiment instead.
