# e3_end_to_end_workflow v0.8.0

Date: 24 July 2026

## Purpose

Version 0.8.0 adds a scheduler-owned Snakemake-controller mode so a complete E3 run can continue
after the submitting terminal disconnects without leaving the controller on a login node.

## Added

- `submit_e3_controller_slurm.sh`
  - submits the controller with `sbatch`;
  - defaults to one CPU, 4,000 MiB and a three-day controller allocation;
  - supports separate controller and scientific-job account, partition, memory and runtime
    controls;
  - records `workflow_control/controller.slurm.tsv` atomically;
  - reports current state through `squeue` and completed state through `sacct`;
  - serialises submission with `controller_submission.lock`; and
  - rejects a second pending or running controller for the same run.
- `scripts/slurm_e3_controller_job.sh`
  - runs through an explicit Conda executable and named environment;
  - reports the resolved Python and workflow version;
  - holds the existing per-run `controller.lock`;
  - invokes the standard runner with the Slurm profile; and
  - preserves the normal exit status in Slurm accounting.

## Retained

- `run_e3_end_to_end.sh --profile local` remains the complete non-Slurm path.
- `submit_e3_end_to_end.sh` remains a legacy detached login-node option for sites that explicitly
  permit it.
- Stage manifests, controlled reruns, atomic publication, failed-stage retention and all
  scientific output contracts are unchanged from v0.7.6.

## Documentation and repository integration

- The repository root now has `run_e3_pipeline.sh`, with `slurm`, `local` and legacy
  `login-detached` modes.
- The repository root README now documents every package, whole-pipeline configuration, expected
  directory organisation, expression-data reuse, a new-dataset procedure, monitoring and package
  quick starts.
- A visually validated A4 operator-guide PDF is provided at
  `docs/E3_PROJECT_OPERATOR_GUIDE_v0_8_0.pdf`.
- The fresh-production template no longer proposes stage walltimes above Dundee's 72-hour maximum.

## Scientific impact

This is an orchestration and operations release. It does not change candidate evidence,
OrthoFinder interpretation, domain mapping, expression mapping, ranking equations, ligandability,
pocket conservation or structural-alignment methods.

## Upgrade

Install the updated package:

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft/e3_end_to_end_workflow
conda activate e3_end_to_end_workflow
python -m pip install --no-deps --editable .
./run_tests.sh
```

Submit from the repository root:

```bash
cd ..
./run_e3_pipeline.sh \
    --mode slurm \
    --config e3_end_to_end_workflow/config/my_immutable_run.yaml \
    --max-jobs 4 \
    --account barton \
    --partition general \
    --resume
```

