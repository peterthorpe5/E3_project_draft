# Troubleshooting

## Installed command reports an older release

An extracted source tree and the command on `PATH` are separate. Diagnose both from the
master package directory:

```bash
conda run --name e3_end_to_end_workflow \
    e3-workflow diagnose-install \
    --source-root "$(pwd)" \
    --require-source-match
```

If the command still reports `0.7.6`, replace that environment's editable installation:

```bash
conda run --name e3_end_to_end_workflow \
    python -m pip install \
    --no-deps \
    --force-reinstall \
    --editable "$(pwd)"
```

Do not install from a nested `E3_project_draft/E3_project_draft` copy. Release v0.9.1 has
one repository root and the launchers stop before execution if the source and command do
not match.

## Controller is pending

```bash
squeue --jobs JOB_ID --start
scontrol show job JOB_ID
```

Do not submit a second controller for the same run.

## Controller ended after some stages completed

Read the persistent controller and stage logs. Fix the external cause, confirm the
controller is no longer active, then submit the same immutable configuration with
`--resume`.

Do not delete completed stage directories. The workflow will validate them before
skipping.

## Configuration digest changed

Restore the exact immutable configuration or create a new configuration and `run.name`.
Do not weaken the digest or edit an existing stage manifest.

## Output exists but is rejected

File existence is insufficient. Check:

- the declared relative path;
- non-empty content;
- `stage_manifest.json`;
- recorded size and checksum;
- the retained failed-stage directory;
- the persistent stage log.

## Tool placeholder is unknown

An external command referenced a value absent from the central registry. For example:

```text
{tool_orthofinder_search_threads}
```

requires:

```yaml
tools:
  orthofinder:
    parameters:
      search_threads: 32
```

Tool and parameter keys use lower-case letters, numbers and underscores.

## Expression species is missing

Check the Expression Atlas resource manifest, identifier aliases and species naming.
Publish an explicit unavailable state when no suitable experiment or mapping exists.
Never replace it with zero expression.

## Stage 07 ends after its preamble

The last line in `07_expression.snakemake.log` may only be Snakemake's generic failure
summary. Identify the scientific child job and inspect its scheduler record:

```bash
sacct --jobs JOB_ID \
    --format=JobIDRaw,JobName,State,ExitCode,Elapsed,ReqMem,MaxRSS,NodeList,Reason
```

Version 0.9.1 scans only expression partitions for selected group-member species, reduces
measurements to candidate genes before alias expansion, materialises mapping summaries once,
and gives DuckDB a bounded memory limit plus disk spill directory. Resume the same immutable
configuration after installing v0.9.1; do not delete the completed Stage 00–05 directories.

## Domain annotation is missing

Check the InterPro cache inventory and validation table. Missing curated annotation is
`ANNOTATION_UNAVAILABLE`; it is not evidence that the protein lacks an E3-related domain.

## Sweep comparison is incomplete

`compare-sweep` fails by default when a configured final table is missing. Inspect
`sweep_runs.tsv`, finish or resume the missing runs, then compare again.

Use `--allow-incomplete` only to create a labelled progress report.

## Structural alignment is unavailable

For a normal reuse analysis, stage `09b` may be disabled and optional. Final integration
records `NOT_ASSESSED`. A strict complete fresh run requires the stage to be enabled.
