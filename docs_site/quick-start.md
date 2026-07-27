# Quick start

## Install the master environment

From `E3_project_draft`:

```bash
conda env create \
    --file e3_end_to_end_workflow/environment.yml

conda run \
    --name e3_end_to_end_workflow \
    python -m pip install \
    --no-deps \
    --force-reinstall \
    --editable e3_end_to_end_workflow

conda run \
    --name e3_end_to_end_workflow \
    e3-workflow diagnose-install \
    --source-root "$(pwd)/e3_end_to_end_workflow" \
    --require-source-match
```

Run the tests before a real submission:

```bash
conda run \
    --name e3_end_to_end_workflow \
    ./e3_end_to_end_workflow/run_tests.sh

./run_repository_tests.sh
```

## Choose and copy a configuration

Use one immutable file per run:

```bash
cp \
    e3_end_to_end_workflow/config/grant_aligned_reuse.cluster.template.yaml \
    e3_end_to_end_workflow/config/my_run_v0_1_0_20260725.yaml
```

Edit the copy. Never edit a configuration after its run has started. A changed
threshold, input or command needs a new configuration filename and `run.name`.

## Validate and inspect the plan

```bash
e3-workflow validate \
    --config e3_end_to_end_workflow/config/my_run_v0_1_0_20260725.yaml

e3-workflow plan \
    --config e3_end_to_end_workflow/config/my_run_v0_1_0_20260725.yaml \
    --human
```

## Submit on Slurm

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config e3_end_to_end_workflow/config/my_run_v0_1_0_20260725.yaml \
    --max-jobs 4 \
    --account barton \
    --partition general \
    --resume
```

Check status later:

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config e3_end_to_end_workflow/config/my_run_v0_1_0_20260725.yaml \
    --status
```

## Run without Slurm

```bash
./run_e3_pipeline.sh \
    --mode local \
    --config e3_end_to_end_workflow/config/my_run_v0_1_0_20260725.yaml \
    --threads 8 \
    --resume
```

Local mode remains in the foreground. Use it for workstations, synthetic tests and small
analyses.
