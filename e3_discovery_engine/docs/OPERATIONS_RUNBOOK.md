# Operations runbook

## 1. Create and activate the environment

```bash
conda env create -f workflow/envs/production.yml
conda activate e3_discovery
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

### `Traceback with adjusted matrix not supported`

This indicates that DIAMOND was asked to produce traceback-dependent identity
or alignment fields while using a compositionally adjusted scoring matrix.
Use `diamond.comp_based_stats: 0` for the production workflow. The configuration
validator rejects incompatible modes 2-6 when exact identity is selected.
Do not remove exact identity or strict post-realignment filtering merely to
make the command run.



### `asymmetric masking for self alignment`

DIAMOND DeepClust performs an internal self-alignment. In DIAMOND 2.2.3,
`--masking seg` applies target-only SEG masking and is therefore asymmetric.
Use `diamond.masking: tantan` for symmetric repeat masking, or `none` when
masking is intentionally disabled. Production templates use `tantan`, and the
command builder rejects SEG before DIAMOND starts.

## Paths containing spaces

Release 0.1.8 fixed shell quoting in Snakemake, but DIAMOND 2.2.x clustering
can still split database-related paths internally. Release 0.1.9 creates a
whitespace-free symbolic-link alias for the configured workflow output root
and uses it for `makedb`, `deepclust` and `realign`. The data remain in the
configured output directory, including macOS volumes such as
`/Volumes/One Touch/...`.

The alias is normally created under the repository's `.e3_path_aliases/`
directory and its mapping is written to:

```text
<output_root>/provenance/diamond_path_alias.json
```

To use a different whitespace-free location, set:

```yaml
diamond:
  path_alias_root: /path/without/whitespace/e3_aliases
```

Do not delete the alias while a DIAMOND stage is running. It may safely be
recreated from the provenance record after a run has stopped.

## macOS external-drive benchmark sidecars

Some external-drive filesystems store macOS extended metadata in hidden
AppleDouble files named ``._<filename>``. A benchmark directory can therefore
contain both ``diamond_deepclust.tsv`` and a binary metadata sidecar named
``._diamond_deepclust.tsv``. The benchmark aggregator ignores hidden files and
hidden directories, while continuing to validate every visible benchmark TSV
as UTF-8 Snakemake output.


## Inspect measured RAM and automatic summaries

```bash
column -t -s $'\t' <RUN_ROOT>/benchmark_summary/resource_usage_summary.tsv
column -t -s $'\t' <RUN_ROOT>/summaries/workflow_key_metrics.tsv
column -t -s $'\t' <RUN_ROOT>/summaries/realignment_content_summary.tsv
```

The RAM table is generated by the package process-tree monitor and includes
DIAMOND child processes.
