# Milestone 1 benchmark protocol

## Objective

Measure the performance and reproducibility of the production E3 discovery
workflow without claiming an unmeasured speed-up. The inherited 5-60 proteome
series and 1KP+ timing provide historical context, but formal delivery metrics
must be regenerated under controlled conditions.

## Benchmark questions

1. Does the workflow complete successfully and reproducibly?
2. How do runtime, memory and I/O scale with sequence count and total residues?
3. How stable are raw cluster count, E3-seeded cluster count and strict-member
   count between repeated runs?
4. How closely does legacy-reproduction mode reproduce inherited outputs?
5. What is the measured runtime for the full intended dataset?

## Benchmark datasets

Use at least three scales.

### Development dataset

Five to ten proteomes. Small enough for rapid iteration and complete output
inspection.

### Intermediate dataset

At least 50-60 proteomes, preferably matching the recovered historical
benchmark composition where files can be verified.

### Large production dataset

The 1KP+ collection or the final agreed dataset. This is required before making
large-scale performance claims.

For every dataset record:

- dataset ID and release date;
- complete sample manifest;
- proteome count;
- sequence count;
- total amino-acid residues;
- compressed and uncompressed input bytes;
- source database/release and checksums;
- duplicate-ID and duplicate-sequence statistics.

## Hardware and software controls

Record:

- hostname or cluster node class;
- operating system;
- CPU model and allocated cores;
- total and allocated memory;
- local/scratch/network filesystem used;
- scheduler job ID and resource request;
- DIAMOND, Snakemake, Python, DuckDB and PyArrow versions;
- workflow git commit/release;
- configuration checksum.

Do not interpret a scheduler memory request as observed memory use.

## Repeats and cache control

Use at least three independent repeats for formal summaries. Use a fresh output
root per repeat. State whether filesystem caches are likely warm or cold. Avoid
mixing first-run database construction with subsequent search-only runs without
labelling them separately.

## Metrics

Collect rule-level and end-to-end:

- wall-clock seconds;
- CPU seconds;
- peak RSS and, if available, USS/PSS;
- I/O read and write volumes;
- input and output sizes;
- raw DeepClust rows and cluster count;
- realignment rows;
- E3-seeded cluster count;
- raw and strict E3-seeded member counts;
- validation status;
- output checksums.

## Comparisons

### Legacy reproduction

Run DIAMOND 2.1.23 with inherited approximate identity, mutual coverage and
clustering e-value. Compare output counts and, where feasible, set overlap with
the inherited 6,707 representative sequences. Differences must be investigated,
not automatically forced away.

### Production mode

Run the pinned production environment with exact clustering identity and strict
post-realignment filtering. Report this as a new production analysis, not as a
bit-for-bit legacy reproduction.

## Statistical summaries

For each rule and total workflow calculate:

- repeat count;
- mean, minimum and maximum wall-clock time;
- population standard deviation;
- mean and maximum observed peak RSS;
- coefficient of variation where useful.

For scaling, regress runtime against sequence count and total residues as well as
proteome count. Clearly label interpolations and extrapolations. Do not state an
extrapolated value as an observed runtime.

## Acceptance criteria

A formal benchmark passes when:

- all configured repeats complete;
- all resource validation checks pass;
- output counts/checksums are stable or explained;
- no source file is modified;
- logs and provenance are complete;
- measured resource use is reported;
- figures are generated from machine-readable benchmark tables;
- scientific wording remains limited to E3-seeded sequence clusters.

## Recommended figures

1. End-to-end wall-clock time versus sequence count/residue count.
2. Rule-level runtime contribution.
3. Peak RSS by rule and dataset.
4. Raw clusters, E3-seeded clusters and strict-member counts by dataset.
5. Legacy versus production overlap for representative sequences/clusters.

## Package-owned RAM monitoring

Version 0.1.12 records sampled aggregate process-tree peak RSS, CPU time and
wall time for each major stage. Use `benchmark_summary/resource_usage_summary.tsv`
for observed RAM. Do not substitute DIAMOND memory limits, scheduler requests
or macOS Snakemake `max_rss` values of zero for observed memory.
