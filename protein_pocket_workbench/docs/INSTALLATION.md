# Installation and remote use

For the 1.3.0 viewer update, follow the focused commands in [README](../README.md).
Keep an active/resumable 1.2.0 HPC workflow on its existing software/environment.
Opening its completed native resource in 1.3.0 requires no new predictions,
structural fits, sequence analysis or DuckDB rebuild.

Batch analysis uses [HPC_WORKFLOW.md](HPC_WORKFLOW.md), with the separate quality
rerun in [QUALITY_RERUN.md](QUALITY_RERUN.md). For viewing-only local/de.NBI installation,
use `environment.viewer.yml` and [DEPLOYMENT.md](DEPLOYMENT.md).
The optional prediction/worker instructions below require explicit
`pocket-workbench app --enable-jobs`. Existing pocket predictions are reused
by the normal batch build.

## App environment

From the extracted package root:

```bash
conda env create --file environment.viewer.yml
conda activate pocket_workbench
python -m pip install --editable .
pocket-workbench --version
```

For an existing compatible Python 3.11+ environment, `python -m pip install .`
installs the app and FAMSA. Viewing requires no structural binaries. Batch
builds use USalign and TMalign pinned by the supplied environment. Explicit
legacy paired comparisons can use labelled Kabsch without TM-scores.

The application is reusable without E3_project_draft installed. Its source and
the private predictor code are packaged together. The third-party JavaScript
viewers are bundled; there is no npm build step or CDN requirement for users.

## Reuse existing results

`pocket-workbench import --input /path/to/completed_run --fasta /path/to/reps.fasta
--output /path/to/new_project` reuses prepared structures and predicted pockets.
It builds a separate `pocket_workbench.duckdb`. Keep the whole completed run
available during import; the resulting app resource retains its own prepared
structures, coordinate maps and evidence.

## Predict new pockets

For new AlphaFold models, import model ZIPs first, then use **Models & pockets →
Predict pockets**. Install compatible external software:

```bash
conda install --name pocket_workbench -c conda-forge -c bioconda \
  fpocket=4.2.2 openjdk=17
```

Use the P2Rank 2.5.1 installation you already have and enter its absolute `prank`
path in the app. For this project that is:

```text
~/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/software/p2rank_2.5.1/prank
```

Expand `~` to the actual home directory when entering a path into the executable
field. To use `prank` on PATH, add its parent directory before launching the app:

```bash
export PATH="$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/software/p2rank_2.5.1:$PATH"
```

If P2Rank is not installed, use the official release archive:

```bash
mkdir -p "$HOME/software"
cd "$HOME/software"
curl --fail --location --retry 3 --output p2rank_2.5.1.tar.gz \
  https://github.com/rdk/p2rank/releases/download/2.5.1/p2rank_2.5.1.tar.gz
printf '%s\n' 'd243f2d9036ac053fefb9407b5fe1c85f4fe077c519fd975ac585e995feab274  p2rank_2.5.1.tar.gz' \
  | sha256sum --check -
tar --no-same-owner -xzf p2rank_2.5.1.tar.gz
chmod +x p2rank_2.5.1/prank
```

Continue only after the checksum succeeds. The separately installed predictor
command is `pocket-workbench-predict`, with the original `check` and `run`
subcommands. It does not replace an existing `protein-pockets` installation.

## Remote app

Run `pocket-workbench app --resource /server/project --port 8510` in a persistent
server session. On your laptop, forward that port with your normal SSH route.
The browser opens `http://127.0.0.1:8510`. A GPU is unnecessary. Comparison jobs
can also run on Slurm before browsing the resource elsewhere.

Uploaded files and task status live in the workspace/project directories. Local
analysis workers survive browser disconnections. A stopped app server can be
restarted with the same `--resource`; inspect **Jobs** and reload the resource
after workers finish. Avoid moving a project during an active job.

## Reproducibility and recovery

Each comparison records its own engine, input hashes and settings. Repeating an
identical comparison replaces its index entry rather than appending duplicate
rows. New settings produce a separate comparison ID. Failed pairs retain their
reason and do not erase successful pairs. Existing output folders are protected
on import/export/pack; choose a new output name for a new resource.

If a killed job remains listed as running, the app checks its PID before
starting another task. A queued job that never started has no worker PID: inspect
its log and change only that job's status to `interrupted` after confirming that
no corresponding worker is active. Original predictor run locks follow the
original pipeline's documented recovery rules.
