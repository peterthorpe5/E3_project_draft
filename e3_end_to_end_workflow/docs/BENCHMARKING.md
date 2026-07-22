# Benchmarking protocol

## Purpose and scopes

Every stage is measured automatically so scientific results and their computational cost can be
reviewed together. The workflow deliberately retains complementary measurements:

1. The process-tree monitor covers prerequisite checksum validation, the scientific command and
   expected-output validation. It stops before output inventory and atomic publication.
2. Runner start and finish timestamps extend through checksum inventory.
3. Slurm accounting, when available, independently covers the scheduled allocation and job steps.

The first scope provides the richest process detail. The second is a broader orchestration wall
time, while the third provides scheduler-observed CPU, memory and I/O fields. Their values should
be comparable but need not be equal because their boundaries and sampling methods differ.

## Stage outputs

Each formal stage directory contains:

| File | Contents |
|---|---|
| `benchmark/stage_resource_usage.tsv` | One machine-readable stage summary |
| `benchmark/stage_resource_usage.json` | The same summary with time-series metadata |
| `benchmark/stage_resource_timeseries.tsv.gz` | Ordered samples throughout execution |

The one-row stage summary records:

- UTC start and finish, wall time, exit status and measurement scope;
- user, system and total CPU seconds, mean cores and requested-thread efficiency;
- sampled process-tree peak RSS and VMS, plus the memory-accounting method;
- maximum visible processes and threads;
- sampled cumulative bytes/operations read and written and context switches;
- sampling interval and count;
- requested CPUs, memory and runtime and observed memory/request percentage;
- host, platform, Python/package versions and host CPU/RAM inventory; and
- Slurm job, account, partition, node and allocation environment when available.

The compressed time series records elapsed time, current process/thread counts, RSS/VMS,
cumulative CPU and I/O, interval mean cores and percentage of the configured CPU allocation.

## Run-level outputs

After all twelve stages complete, `benchmark_summary/` contains:

| File | Contract |
|---|---|
| `stage_resource_summary.tsv` | One joined record per stage |
| `workflow_resource_summary.tsv` | Whole-run metrics with units and interpretations |
| `slurm_accounting_status.tsv` | Whether `sacct` enrichment succeeded |
| `slurm_accounting.tsv` | Raw allocation and step records where available |
| `benchmark_complete.tsv` | Completion record bound to the configuration digest |
| `benchmark_manifest.json` | Checksummed benchmark output inventory |

The stage comparison adds runner timestamps, configuration digest, published file count/bytes and
paths to the authoritative manifest and time series. The workflow summary distinguishes the span
from the earliest retained stage start to the latest retained finish from summed stage wall time.
That span includes scheduler gaps and, after partial resumes, time between invocations. Its ratio is
a useful parallelisation factor for a fresh uninterrupted full run; values below one can occur when
scheduling overhead dominates very short stages. Totals for CPU, sampled read/write bytes, samples
and published bytes are included, alongside maximum per-stage RSS, allocation fraction, process
count and thread count. No maximum individual-stage value is presented as simultaneous
workflow-wide use.

## Configuration

Production defaults should normally be:

```yaml
benchmarking:
  sample_interval_seconds: 5.0
  collect_slurm_accounting: true
```

Short tests use a smaller interval so brief synthetic processes are observed. Smaller intervals
increase monitor overhead and output rows; larger intervals increase the chance that a very short
child process is not sampled.

## Interpretation limits

- Peak RSS is the largest sampled sum for the visible process tree. A labelled POSIX fallback is
  used if the tree cannot be inspected. Neither should be summed across stages to estimate
  concurrent workflow memory.
- POSIX CPU deltas include the orchestrator and waited-for children. Process-tree I/O, VMS,
  process/thread counts and time-series CPU are sampled, so very short-lived children can be missed.
- CPU efficiency is total CPU seconds divided by requested thread-seconds. Low utilisation may be
  appropriate for I/O-bound stages; values above 100% indicate use beyond the declared allocation
  and should be investigated.
- Slurm `MaxRSS` and related fields can be delayed or unavailable depending on cluster accounting.
  The status file makes this explicit. Missing accounting never invents zero-valued measurements.
- Failed attempts keep their benchmark files inside the corresponding `failed/` directory, but
  the final run-level summary describes the successfully published twelve-stage DAG.
