# Complete fresh run

The clean-room launcher is for a new analysis that must generate every scientific stage
instead of consuming results from an earlier E3 workflow run.

## What the preflight enforces

`run_e3_pipeline_fresh.sh` calls `e3-workflow validate-fresh` before submission. It
requires:

- schema version 2 and a non-empty central `tools` section;
- production mode;
- all 13 core stages enabled, including structural alignment; optional Stage
  `09c_computational_chemistry` may remain disabled;
- generation commands for discovery, candidate evidence, OrthoFinder, orthology,
  expression, ligandability and structural alignment;
- no candidate-evidence, OrthoFinder, expression, domain-result or ligandability reuse
  manifest;
- no unresolved `CHANGE_ME` markers in stage commands or tool settings;
- a new empty run root, unless `--resume` explicitly continues the same run.

Domain evidence may use the reviewed InterPro download/cache implementation. This is a
fresh acquisition of curated annotations, not a local InterProScan/HMMER run.

## Prepare the configuration

```bash
cp \
    e3_end_to_end_workflow/config/production.cluster.template.yaml \
    e3_end_to_end_workflow/config/my_fresh_panel_v0_1_0_20260725.yaml
```

Replace every `CHANGE_ME` value, supply the new manifests and review the output contracts.
The component adapters must publish exactly the paths declared in `expected_outputs`.

Run the strict preflight:

```bash
e3-workflow validate-fresh \
    --config e3_end_to_end_workflow/config/my_fresh_panel_v0_1_0_20260725.yaml
```

## Submit and leave

```bash
./run_e3_pipeline_fresh.sh \
    --config e3_end_to_end_workflow/config/my_fresh_panel_v0_1_0_20260725.yaml \
    --mode slurm \
    --max-jobs 10 \
    --account barton \
    --partition general
```

The launcher submits a small Snakemake controller job. That job owns orchestration and
submits scientific child jobs. The terminal can be closed after `sbatch` returns the
controller job ID.

The default local CPU budget is 32. Stage-level thread values still come from the YAML;
no stage should request more threads than its configured Slurm allocation.

## Check and resume

```bash
./run_e3_pipeline_fresh.sh \
    --config e3_end_to_end_workflow/config/my_fresh_panel_v0_1_0_20260725.yaml \
    --mode slurm \
    --status
```

After fixing an external interruption:

```bash
./run_e3_pipeline_fresh.sh \
    --config e3_end_to_end_workflow/config/my_fresh_panel_v0_1_0_20260725.yaml \
    --mode slurm \
    --max-jobs 10 \
    --account barton \
    --partition general \
    --resume
```

Do not delete successful stage directories. Resume validates their manifests, input
checksums, output checksums and configuration digest before skipping them.

## Dry-run first

```bash
./run_e3_pipeline_fresh.sh \
    --config e3_end_to_end_workflow/config/my_fresh_panel_v0_1_0_20260725.yaml \
    --mode slurm \
    --dry-run
```

A dry-run validates the whole DAG but does not prove that an external component adapter
will produce its declared files. Each adapter also needs a standalone smoke test.
