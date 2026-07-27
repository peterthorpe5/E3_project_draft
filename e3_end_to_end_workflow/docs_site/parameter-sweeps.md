# Parameter sweeps

Parameter sweeps answer a specific sensitivity question: how do rankings and
recommendations change when named thresholds or external-tool parameters change?

They do not edit one run repeatedly. The generator creates a separate immutable workflow
configuration and `run.name` for every parameter set.

## Define the experiment

Copy the template:

```bash
cp \
    e3_end_to_end_workflow/config/parameter_sweep.template.yaml \
    e3_end_to_end_workflow/config/my_threshold_sweep_v1.yaml
```

Example:

```yaml
schema_version: 1
name: ligandability_threshold_sensitivity_v1
base_config: my_reuse_run_base.yaml
strategy: cartesian
include_baseline: true
maximum_runs: 12
parameters:
  - path: analysis.ligandability.minimum_druggability_score
    values: [0.4, 0.5, 0.6]
  - path: analysis.prioritisation.minimum_structural_species_fraction
    values: [0.6, 0.75, 0.9]
```

Only existing paths below `analysis.` and `tools.` can be varied. A typo cannot create a
new key. `maximum_runs` stops an accidental combinatorial expansion.

`cartesian` tests every combination. `one_at_a_time` changes one parameter at a time.
`include_baseline` adds the unmodified base configuration.

## Generate immutable configurations

```bash
e3-workflow prepare-sweep \
    --sweep-config e3_end_to_end_workflow/config/my_threshold_sweep_v1.yaml \
    --output-dir e3_end_to_end_workflow/config/generated/my_threshold_sweep_v1
```

The output includes:

- `run_001.yaml`, `run_002.yaml`, and so on;
- `sweep_runs.tsv` with configuration checksums, parameter-set checksums and run roots;
- `sweep_generation_manifest.json`.

Generated files retain the base configuration's relative-path meaning through
`path_base`.

## Run the configurations

Submit them in a controlled batch. A safe initial cluster policy is one scientific child
job per sweep controller, with no more controllers than the local allocation policy
allows:

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config e3_end_to_end_workflow/config/generated/my_threshold_sweep_v1/run_001.yaml \
    --max-jobs 1 \
    --account barton \
    --partition general \
    --resume
```

Repeat for the required generated configurations. Do not launch a large sweep blindly.
The controller itself is also a Slurm job, so five controllers with one child job each can
already occupy ten jobs.

For thresholds applied only to integrated evidence, use a base configuration that reuses
the reviewed upstream authorities. This avoids rerunning expensive discovery or structure
prediction while retaining an independent checksum-bound workflow run for each parameter
set.

## Compare completed runs

```bash
e3-workflow compare-sweep \
    --manifest e3_end_to_end_workflow/config/generated/my_threshold_sweep_v1/sweep_runs.tsv \
    --output-dir /path/to/analysis/my_threshold_sweep_v1_comparison
```

The comparison produces tab-separated files:

| Output | Purpose |
|---|---|
| `sweep_run_status.tsv` | Complete or missing final table for every configured run |
| `sweep_candidate_sensitivity.tsv` | Every candidate, rank, score and status in every run |
| `sweep_candidate_summary.tsv` | Rank range, score range and recommendation stability |
| `sweep_comparison_manifest.json` | Comparison status and counts |

The strict default refuses an incomplete sweep. `--allow-incomplete` is for a progress
report and labels the comparison `partial`.

Parameter sensitivity is evidence about robustness. It does not identify a biologically
correct threshold by itself.
