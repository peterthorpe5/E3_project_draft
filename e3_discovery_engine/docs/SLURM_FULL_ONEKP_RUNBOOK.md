# Full 1KP+ Slurm runbook

## Purpose

This runbook describes the full inherited 1KP+ production analysis on the
University of Dundee Slurm cluster. It uses the same scientific settings as
the validated `tantan` workflow, but reads the biological files from cluster
storage and uses job-local scratch for DIAMOND temporary files.

The workflow identifies sequence clusters containing at least one previously
identified E3 candidate. It does not assume that every sequence in such a
cluster is an E3 ligase.

## Cluster paths and allocation

Default source root:

```text
/home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data
```

Default persistent results root:

```text
/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results
```

Slurm allocation:

```text
account:   barton
partition: general
```

The submission script requests one node, 32 CPUs, 256 GiB RAM and seven days.
DIAMOND is limited to 220 GiB so that the Python process, operating system and
other workflow stages retain headroom. These are conservative starting values,
not measured full-run requirements. The submitted job records actual peak RAM,
wall time and Slurm accounting data.

## Biological inputs

The generated manifest reads the inherited ordered sample list from:

```text
<source root>/Other_things/Denbi/denbi_data/E3_discovery_engine/samples.json
```

The corresponding FASTA files and seed table are read from:

```text
<source root>/Other_things/Denbi/denbi_data/E3_discovery_engine/files/fasta_files/
<source root>/Other_things/Denbi/denbi_data/E3_discovery_engine/files/e3_ligases.csv
```

The inherited list contains 14 named proteomes and `onekp_dataset.fasta`.
The combined 1KP FASTA is not treated as one biological sample. Identifiers of
the form:

```text
scaffold-AALA-2000001-Meliosma_cuneifolia
```

are parsed while the FASTA is streamed. The result stores:

```text
source_file_sample_id = onekp_dataset
sample_id              = AALA
onekp_sample_code      = AALA
species                = Meliosma cuneifolia
header_parse_status    = parsed
```

Strict parsing is enabled for the 1KP file. A malformed identifier stops input
preparation rather than silently collapsing sequence-level species metadata.

## Install or update the package on the cluster

Clone or update the Git repository on cluster storage, then install the package
into the existing bootstrap environment:

```bash
cd /path/to/e3_discovery_engine
conda activate e3_discovery
python -m pip install -e .
./run_tests.sh
```

The local macOS configurations are retained in the repository checkout when
they are ignored by Git. The Slurm job generates separate cluster-specific
manifest and YAML files below the result folder; it does not overwrite local
configurations.

## Submit the full analysis

From the repository root:

```bash
./scripts/submit_full_onekp_slurm.sh
```

Equivalent explicit command:

```bash
./scripts/submit_full_onekp_slurm.sh \
  --source-root /home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data \
  --results-base /home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results \
  --account barton \
  --partition general \
  --cpus 32 \
  --memory 256G \
  --diamond-memory 220G \
  --time 7-00:00:00 \
  --conda-env e3_discovery \
  --min-results-free-gib 150 \
  --min-scratch-free-gib 100
```

Before preparation starts, the worker checks that the persistent results
filesystem has at least 150 GiB free and the selected scratch filesystem has at
least 100 GiB free. These are conservative operational checks rather than
claims about expected final usage. Override them only after inspecting the
relevant filesystem with `df -h`.

The submission command prints the job ID, result directory and Slurm log
paths. It also writes `job_info.tsv` below the Slurm log directory.

## Check progress

```bash
./scripts/check_full_onekp_slurm.sh --job-id <JOB_ID>
```

Follow the main Slurm output:

```bash
./scripts/check_full_onekp_slurm.sh --job-id <JOB_ID> --follow
```

Direct Slurm commands remain useful:

```bash
squeue -j <JOB_ID>
sacct -j <JOB_ID> --format=JobID,State,Elapsed,TotalCPU,AllocCPUS,MaxRSS,ExitCode
```

The stage-specific logs are below:

```text
<run root>/logs/
```

DeepClust may write no new log lines for periods while it processes a large
block. Queue state, CPU use and output-file growth should be considered along
with the log tail.

## Restart after interruption or failure

Submit again with the same run tag:

```bash
./scripts/submit_full_onekp_slurm.sh \
  --run-tag <ORIGINAL_TAG>
```

The output root is deterministic from the run tag. Snakemake uses
`--rerun-incomplete`, retains completed products and reruns only missing or
incomplete stages. Review `workflow_failed.tsv` and the stage logs before
resubmitting.

Do not manually remove completed large files unless a specific stage is known
to be invalid. A fresh tag should be used only when a completely independent
run is intended.

## Scratch and persistent storage

Persistent files are written below the result root. DIAMOND temporary files,
path aliases and generic temporary files use `SLURM_TMPDIR` when Slurm provides
it. The worker removes job-created scratch after success. Scratch is retained
after failure to make diagnosis possible, subject to cluster cleanup policy.

The full output includes the combined FASTA, sequence Parquet, DIAMOND
database, cluster membership, realignments, DuckDB resource, curated Parquet,
FASTA exports, QC, summaries, logs and provenance. These products may be tens
of gigabytes. They are intentionally kept out of the Git repository.

## Automatic checks after completion

The job does not mark itself complete until:

- every scientific resource validation check has no `fail` status;
- every monitored stage completed successfully;
- every monitored stage has a positive peak-RAM value;
- the compact review bundle was created.

Completion is indicated by:

```text
<run root>/workflow_complete.ok
```

Failure is recorded in:

```text
<run root>/workflow_failed.tsv
```

## Review bundle

A compact archive is written below:

```text
<results base>/review_bundles/
```

It contains:

- `qc/`;
- `summaries/`;
- `benchmark_summary/`;
- `provenance/`;
- `resource_metrics/`;
- generated Slurm manifest and YAML configuration;
- selected stage logs;
- Slurm job metadata and accounting records.

The full DuckDB, DIAMOND, Parquet and FASTA products remain in the persistent
run directory. The compact archive is the file to share for first-pass review.

## Interpretation limits

The 1KP sequence metadata are derived from inherited identifier strings. This
recovers the four-letter 1KP sample code and species label, but it does not
supply an external taxonomy identifier or resolve synonymy. The exact 1KP
release, protein-translation method and filtering history remain provenance
questions unless recovered from inherited records.

The workflow retains all matched inherited E3 seeds. Additional strict non-seed
members are sequence-similarity candidates, not confirmed E3 ligases. Later
domain, family, phylogenetic, structural and experimental work is still needed.

## Version 0.1.14 preflight and empty-record handling

The submission script now refuses to call `sbatch` until it has:

1. confirmed that the available Conda version is at least 24.7.1;
2. loaded the `e3_discovery` environment through `conda run`;
3. located either the source `samples.json` or the recovered repository copy;
4. confirmed the seed table, production environment and every listed FASTA are
   present and non-empty.

The preflight report is stored as `run_setup/source_input_preflight.json`.
During preparation, the two known empty 1KP records are skipped and recorded in
`qc/skipped_fasta_records.tsv`. More than two empty 1KP records, or any empty
record in a named proteome, stops the workflow.
