# Protein Pocket Workbench 1.3.0

Browse predicted protein pockets, saved structural alignments, pocket-marked
FASTA alignments and trees. The analysis runs in batch on HPC; colleagues can
open the finished resource on their own computer. No cluster account or pocket
predictor is needed for viewing.

## Updating the viewer you already use

**Install this update on your viewing machine. Keep the existing 1.2.0 software
and environment on Dundee while the quality rerun is running or being resumed.**
Workflow fingerprints include software identity, so changing that installation
can prevent an exact resume. Existing native resources from 1.0–1.2 open in
1.3.0 without rerunning pocket prediction, fitting, alignment or rebuilding DuckDB.

Extract the software ZIP into Downloads, stop the old app with Ctrl-C, then:

```bash
cd "$HOME/Downloads/protein_pocket_workbench_1.3.0"
conda activate pocket_workbench
python -m pip install --upgrade --editable .
pocket-workbench --version
```

The version should be `1.3.0`. Keep this source directory in place because the
installation is editable. If you do not already have the environment, replace
the activation step above with these two commands:

```bash
conda env create --file environment.viewer.yml
conda activate pocket_workbench
```

## Open your existing BRCA1 results

On the Mac used for viewing:

```bash
MADDY_LOCAL="$HOME/Library/CloudStorage/OneDrive-UniversityofDundee/2026_oct_Maddy_BRCA1_pockets"
pocket-workbench app \
  --resource "$MADDY_LOCAL/results/brca1_workbench_v1_1" \
  --port 8510
```

Open <http://127.0.0.1:8510>. Adjust `MADDY_LOCAL` to your actual local folder.
For the completed quality rerun, use its finished `04_workbench` resource
instead. Resume outputs may be numbered: consult `latest_outputs.json` for
the exact path and wait until the run has finished before copying it.

For any other project:

```bash
pocket-workbench app --resource /path/to/finished_resource --port 8510
```

Use the directory containing **project.json**, prepared models and
**pocket_workbench.duckdb**. Keep the complete resource together. An ordinary
HTML report or DuckDB file alone does not supply the structures needed for 3D.
A review ZIP contains a nested `app_resource.zip`; extract that too for the app.
The app starts in browsing mode, with analysis submission controls hidden.

## What is clearer in 1.3.0

- One selected pocket opens in close-up with muted local protein context,
  bright lining surfaces, sticks, markers, rank labels and confidence details.
- Aligned pairs use separate reference/mobile colours. View presets, focus,
  opacity, background and display filters support closer inspection.
- Pocket tables start with the original review rank; model labels are shorter.
  Exact source identifiers remain in search, hover information and downloads.
- Reference/model/analysis selectors replace long comparison names. The larger
  directional matrix retains separate fit scopes and missing values.
- Strict rank-one and best-tested-pocket plots show the corresponding overlap
  and decision. Counts and plots use the same selected scope.
- The original full-length resource has an input-confidence summary even without
  a region-preparation audit. Model groups link directly to their saved 3D fits.
- Pocket-marked FASTA defaults to one model per sequence/range; all replicates
  remain selectable. Larger letters, a column ruler, relevant legends and
  selection-aware counts/downloads improve navigation.

The coloured surface follows **atoms lining the pocket**. It does not represent
the empty cavity volume. Display filters do not alter predictions or saved fits.
See [the viewer guide](docs/VIEWER_GUIDE.md) for controls and interpretation.

## Share the updated offline viewer

The app immediately uses the new viewer when opening an existing native
resource. Previously exported HTML files retain the viewer embedded when they
were created. To regenerate a finished offline review from saved evidence:

```bash
pocket-workbench review \
  --resource /path/to/finished_resource \
  --output /path/to/new_review_v1_3
```

Choose a new output folder outside the resource. This exports existing evidence;
it does not run predictors, structural fitting, FAMSA or tree inference. It
creates the review folder and a sibling ZIP, including HTML, formatted Excel,
TSV, DuckDB and `app_resource.zip`. All-pairs reviews can be large: allow space
for the folder and ZIP. Share the ZIP; reviewers extract the whole folder and
open `index.html`. External source/Inspector links require internet.

## Batch analysis and methods

The quality-preparation/prediction workflow and Slurm scripts are retained.
Use [QUALITY_RERUN.md](docs/QUALITY_RERUN.md) for a new quality run and
[HPC_WORKFLOW.md](docs/HPC_WORKFLOW.md) to build from existing predictions.
Do not replace the running 1.2.0 workflow as part of this viewer update.

Keep original full-length predictions as the baseline. Automatic confidence
regions are candidates, not confirmed biological domains; cropping changes
surface geometry and can create exposed sites. Interpret pockets with local
confidence, cut-boundary flags, fit coverage and biological context.

[Methods](docs/METHODS.md) · [Glossary](docs/GLOSSARY.tsv) ·
[Deployment](docs/DEPLOYMENT.md) · [Inputs](docs/INPUTS.md) ·
[DuckDB schema](docs/SCHEMA.md) · [Validation](docs/VALIDATION.md)

Development validation uses explicitly synthetic coordinates and saved evidence.
The real BRCA1 coordinate resource and running Dundee jobs were not available
in this workspace; no new biological predictions or cluster submissions were made.
