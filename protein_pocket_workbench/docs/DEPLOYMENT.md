# Browsing locally or on de.NBI

Dundee Slurm is the recommended analysis route. The app consumes completed
data. No analysis starts when a project opens.

For 1.3.0, update the viewing machine only while a 1.2.0 HPC run is active or
resumable. Existing native resources open directly; no analysis or database
rebuild is required. Previously exported HTML stays unchanged until a new
`pocket-workbench review` export is made from the finished resource.

## Local app

For a viewing-only installation, create the lighter environment with
`conda env create --file environment.viewer.yml`, activate
`pocket_workbench` and run `python -m pip install --editable .`.
The viewing machine does not need USalign or TMalign.

```bash
conda activate pocket_workbench
unzip /path/to/final_review/app_resource.zip -d /path/to/projects
pocket-workbench app \
  --resource /path/to/projects/brca1_workbench_v1_1 \
  --workspace /path/to/projects \
  --port 8510
```

Select the directory containing `project.json` as the resource, rather than
the review directory containing `index.html`.

## de.NBI viewer

Keep files on the data volume, for example below
`/home/ubuntu/data/pete/protein_pocket_workbench/`.
Use the current Miniforge installation:

```bash
export CONDA_EXE=/home/ubuntu/data/pete/software/miniforge3/bin/conda
"$CONDA_EXE" env create --file environment.viewer.yml
"$CONDA_EXE" run --name pocket_workbench python -m pip install --editable .
```

Transfer the completed review ZIP from Dundee using your usual route.
Extract it and then its `app_resource.zip` into a persistent projects folder.
In `tmux` or another persistent session:

```bash
bash scripts/launch_viewer.sh \
  --resource /home/ubuntu/data/pete/protein_pocket_workbench/projects/brca1_workbench_v1_1 \
  --workspace /home/ubuntu/data/pete/protein_pocket_workbench/projects \
  --port 8510
```

From the laptop:

```bash
ssh -N -L 8510:127.0.0.1:8510 ubuntu@sabrina-server
```

Here `sabrina-server` is the previously used host name/alias, not newly
verified public DNS. Substitute your normal de.NBI destination if different.
Open <http://127.0.0.1:8510>. The app binds to localhost. A public deployment
requires your normal authenticated reverse proxy; this package does not
configure public hosting or accounts.

## Sharing without server access

Send the final review ZIP. Reviewers extract the whole folder and open
`index.html`. Offline structures, pockets, alignments and trees need no
server account or Python. Excel and DuckDB are included. Original-source and
external Inspector links need internet access.

## Optional workers

The old app launched workers on its own machine. This version hides those
controls by default. An operator can explicitly opt in:

```bash
pocket-workbench app --resource /path/to/resource --enable-jobs
```

Workers use the Streamlit server's machine and Python environment. They do
not SSH to Dundee/de.NBI or automatically submit Slurm jobs. Jobs records
the actual host, interpreter, installed tools and previous HPC build.
