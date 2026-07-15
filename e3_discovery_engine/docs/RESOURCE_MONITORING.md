# Resource monitoring

Version 0.1.12 adds a package-owned resource monitor because Snakemake's
platform-specific memory fields can report zero on macOS. Each major workflow
stage starts a monitoring thread inside the stage Python process. The monitor
samples that process and all recursively discovered child processes, including
DIAMOND.

## Measurements

Each `resource_metrics/*.tsv` file contains:

- stage name and completion status;
- root process identifier;
- UTC start and finish timestamps;
- wall-clock seconds;
- user, system and total CPU seconds;
- aggregate peak resident set size in bytes and MiB;
- maximum simultaneous process count;
- sample count and requested sampling interval;
- operating-system platform.

The CPU total retains the maximum cumulative CPU time seen for each process
identity. Peak RSS is the maximum simultaneous sum observed across the live
process tree. The default 0.2-second interval is a compromise between detecting
short peaks and avoiding measurable monitoring overhead.

## Outputs

The final aggregation stage writes:

```text
benchmark_summary/resource_usage_records.tsv
benchmark_summary/resource_usage_summary.tsv
benchmark_summary/peak_ram_by_stage.png
benchmark_summary/peak_ram_by_stage.pdf
```

The resource summary is the preferred memory report. Scheduler requests and
DIAMOND `--memory-limit` values are limits or allocations, not observed RAM
consumption, and must not be reported as measured use.

## Interpretation limits

The monitor is sampled rather than kernel-event based, so a very short memory
spike between samples can be missed. Child processes that start and end between
samples may contribute incompletely to CPU time. DIAMOND stages last long
enough for the measurements to be useful. Formal HPC benchmarks should also
retain scheduler accounting such as Slurm `sacct` and compare it with the
package monitor.

## Linux and Slurm CPU accounting in version 0.1.13

The process monitor now records a POSIX `getrusage` snapshot for the Python
process and completed child processes before and after each stage. On Linux,
this is used to retain child CPU time after DIAMOND exits. The output field
`cpu_accounting_method` records the method used. Sampled `psutil` accounting is
retained as a fallback on platforms where POSIX resource accounting is not
available.

Slurm `sacct` output is also retained for the full 1KP+ job. Formal CPU-time
reporting should compare the workflow records with Slurm accounting before the
figures are frozen. Peak RSS remains measured from the live Python/DIAMOND
process tree, while Slurm `MaxRSS` supplies an independent scheduler-level
check.
