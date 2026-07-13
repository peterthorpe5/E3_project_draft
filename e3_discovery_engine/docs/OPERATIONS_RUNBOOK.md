# Operations runbook

## 1. Create and activate the environment

```bash
conda env create -f workflow/envs/production.yml
conda activate e3_discovery_m1_production
python -m pip install -e .
```

For controlled legacy reproduction, use the separate legacy environment and a
separate output root.

## 2. Run release checks

```bash
./run_tests.sh
./scripts/run_release_checks.sh
```

The optional real-DIAMOND test must be run in the production environment:

```bash
RUN_DIAMOND_E2E=1 python -m unittest \
  tests.end_to_end.test_external_diamond_pipeline -v
```

## 3. Prepare configuration and sample manifest

```bash
cp config/config.example.production.yaml config/config.production.yaml
cp config/samples.production.example.tsv config/samples.production.tsv
```

Edit both files. Use absolute FASTA paths for formal HPC runs. Confirm that the
seed table and output root are correct.

## 4. Dry run

```bash
export E3_DISCOVERY_CONFIG="$(pwd)/config/config.production.yaml"
snakemake --snakefile Snakefile --cores 16 --use-conda --dry-run
```

Review every planned input and output. Stop if a path resolves unexpectedly.

## 5. Execute

```bash
./run_workflow.sh config/config.production.yaml 16
```

For HPC execution, use the local Snakemake profile agreed for the cluster and
retain scheduler logs and job IDs with the run.

## 6. Monitor

Inspect:

```text
<output_root>/logs/
<output_root>/benchmarks/
<output_root>/.snakemake/log/
```

A rule failure should leave its log in place. Do not manually edit partially
written outputs. Correct the cause and use Snakemake's restart behaviour.

## 7. Post-run checks

Confirm that these exist and are non-empty:

```text
duckdb/e3_discovery_resource.duckdb
qc/resource_validation.tsv
benchmark_summary/benchmark_summary.tsv
provenance/run_manifest.json
fasta_exports/e3_seeded_representatives.fasta
fasta_exports/e3_seeded_all_members.fasta
```

Review `resource_validation.tsv`. A `fail` means the result is not releasable.
A warning for zero strict members may be legitimate only for a deliberately tiny
or highly divergent test dataset and must be explained.

## 8. Query the resource

```bash
duckdb <output_root>/duckdb/e3_discovery_resource.duckdb
```

Example:

```sql
SELECT *
FROM e3_seeded_cluster_summary
ORDER BY species_count DESC, strict_member_count DESC
LIMIT 50;
```

Additional examples are in `docs/EXAMPLE_QUERIES.sql`.

## 9. Recovery from common failures

### Configuration path wrong

Set `E3_DISCOVERY_CONFIG` to an absolute configuration path and rerun a dry run.
Relative paths are resolved against the configuration file.

### Duplicate sequence IDs

Use `identifier_mode: prefix_sample`. Do not manually rename proteins without
recording the mapping.

### DIAMOND version too old

Production exact identity requires DIAMOND >=2.2.1. Activate the production
environment or switch deliberately to the legacy configuration/environment.

### Empty or invalid FASTA

Inspect the sample ID and source path in the preparation log. Correct the sample
manifest or replace the corrupt source file; never edit the inherited source in
place.

### Missing sequence for a cluster identifier

This is a validation failure. Confirm that clustering and sequence metadata were
made from the same combined FASTA and identifier mode.

### Insufficient disk space

Estimate space for combined FASTA, DIAMOND database, raw/realigned TSV,
Parquet, DuckDB, FASTA exports and Snakemake temporary files before a full run.
Use a fast project/scratch filesystem, not a home directory.

## 10. Formal release

Follow `docs/RELEASE_CHECKLIST.md`, freeze the configuration and manifests,
record the git commit, archive logs/provenance and create checksums for the
release bundle.
