# Protein Pocket Workbench 1.2.0

Run confidence-aware preparation, fpocket, P2Rank and the downstream analyses
on Dundee HPC. Download one finished review ZIP; colleagues can browse its
structures, pockets, alignments, tree, Excel and DuckDB without a cluster account.
The app opens in browsing mode and does not launch this workflow automatically.

**Keep the original full-length predictions as the baseline.** The new run
uses retained contiguous regions and writes a separate results directory.
Automatic regions are confidence-supported candidates, not confirmed biological
domains. Cropping changes surface geometry; it does not improve coordinates.

## Install or update on Dundee

Extract this ZIP alongside your existing software, then:

```bash
cd "$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/protein_pocket_workbench_1.2.0"

# If pocket_workbench already exists:
conda env update --name pocket_workbench --file environment.prediction.yml

conda activate pocket_workbench
python -m pip install --upgrade --editable .
pocket-workbench doctor
pocket-workbench-rerun --help
```

For a **new environment**, replace the environment-update command with:

```bash
conda env create --file environment.prediction.yml
```

This adds fpocket 4.2.2 and Java 17 to the E3 structural environment
(USalign 20241201, TMalign 20240303). Your original `protein_pockets`
environment remains separate. The Maddy script reuses the existing P2Rank
2.5.1 launcher at `software/p2rank_2.5.1/prank` under the project directory.
No new AlphaFold predictions are needed.

For a viewing-only installation, `environment.yml` is sufficient; no pocket
predictor is required. Keep an editable installation's source directory in place.

## Run the whole Maddy workflow

From this package directory:

```bash
sbatch scripts/run_maddy_quality_pockets.slurm.sh
```

The Maddy preset requests account **barton**, partition **barton** (matching
your earlier working pocket job), 8 CPUs, 64 GB and 48 hours. Override scheduler
settings before the script name if needed, for example
`sbatch --partition=general scripts/run_maddy_quality_pockets.slurm.sh`.
The allocation is a starting request, not a measured runtime guarantee.

It reads:

- `$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/alpha_fold_models/`
- `BRCA1_all_reps.fasta` under the same project
- Matching AF Server `*_full_data_0.json` … `*_full_data_4.json` beside each CIF

Every model is assessed, including all five prediction replicates. MSA/template
directories are excluded. Native AF3 `*_confidences.json` sidecars are also supported.
Original coordinate files, JSON, FASTA and `results/pockets_all_models_v1`
are unchanged.

The new output root is:

```text
results/pockets_quality_regions_v1/
```

| Output | Contents |
| --- | --- |
| `01_quality/` | Model QC, retained/rejected range decisions, excluded ranges, full-chain preparation copies, Excel and HTML audit |
| `02_cleaned_models/` | Separate contiguous candidate-region mmCIFs with original author residue labels |
| `03_pocket_predictions/` | fpocket, independent P2Rank, fpocket rescoring, logs, original predictor reports/Excel/DuckDB |
| `04_workbench/` | Ready-to-open native app resource with pocket flags, both structural tools, MSA/tree and DuckDB |
| `05_review/` and `05_review.zip` | Finished offline HTML review, formatted Excel, TSV, DuckDB and `app_resource.zip` |
| `workflow.log`, `workflow.json` | Progress, input/settings identity and completion/partial/failure status |
| `latest_outputs.json` | Exact final resource and review locations, including numbered resume exports |

The final `05_review.zip` is the file to download and share. Extract the whole
archive, then open `05_review/index.html`. Everything needed for local molecular
and alignment viewing is bundled. External source/Inspector links need internet.

## Review preparation first, if desired

This optional run creates the audit without calling the prediction tools:

```bash
sbatch scripts/run_maddy_quality_pockets.slurm.sh --prepare-only
```

Inspect `01_quality/index.html` and `01_quality/quality_audit.xlsx`. Then
continue with exactly the same settings:

```bash
sbatch scripts/run_maddy_quality_pockets.slurm.sh --resume
```

The same resume command can follow an interrupted job. Do not submit two jobs
to the same output directory. Source, preparation, tool and result checksums
protect reuse; changed cleaning or analysis settings need a **new** output root:

```bash
QUALITY_RESULT_ROOT="$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/results/pockets_quality_regions_v2" \
  sbatch scripts/run_maddy_quality_pockets.slurm.sh --max-low-gap 40
```

If Slurm cannot find Conda, activate the environment before submission or export
the actual `CONDA_EXE` executable. `MADDY_PROJECT` overrides the project parent;
`POCKET_WORKBENCH_P2RANK` overrides the existing prank path.

## What the quality step does

Defaults use residue-mean pLDDT ≥70 as core anchors; retain short internal loops;
split at non-core runs longer than 30 residues, backbone gaps or inconsistent
PAE; add up to five boundary residues; and require ≥50 residues, ≥40 core
residues and ≥50% core content. At least 80% of core pairs must have symmetric
PAE ≤10 Å. Missing or irreconcilable PAE is explicit and fails the default screen.

Every retained range is a contiguous original subsequence. Disjoint pieces are
never joined. Optional curated ranges can replace the automatic proposals;
see [quality workflow and limitations](docs/QUALITY_RERUN.md). Review ranges
around known domains and tandem-domain interfaces before biological conclusions.

Prediction uses `predict -c alphafold` and same-cavity rescoring with
`rescore -c rescore_2024`. The latter is experimental. All pocket predictions,
ranks and confidence labels remain available. Primary comparisons additionally
require complete lining-residue mapping, the local pLDDT rule, assessed PAE and
no flagged proximity to a cut end or very-low-confidence retained residue.
These are heuristics, not validated ligandability classifications.

The default downstream plan makes separate reference comparisons within
corresponding-region groups, using both USalign and TMalign. Eligibility needs
≥70% mutual coverage through full parent-sequence correspondence; ordinal
region names alone never establish a match. The first five **original** pocket
ranks are tested without promoting a screened-out rank one. Use
`--comparison-mode matched_all` for all eligible region pairs.

## Download and browse

On your laptop:

```bash
rsync -avP \
  pthorpe001@login.compute.dundee.ac.uk:~/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets/results/pockets_quality_regions_v1/05_review.zip \
  .
unzip 05_review.zip
```

Open `05_review/index.html`. For the full app, install this package on the
viewing machine, then:

```bash
unzip 05_review/app_resource.zip
pocket-workbench app --resource 04_workbench --port 8510
```

Open <http://127.0.0.1:8510>. Resume exports may contain a numbered native
resource; use the directory actually extracted. The app has an **Input quality**
page and a preparation/context pocket filter. Fit coverage for this workflow
refers to the cropped region, not whole-protein conservation.

## Other projects and existing results

The Python workflow is generic and uses named options. A generic Slurm worker
is also supplied:

```bash
sbatch scripts/run_quality_pockets.slurm.sh \
  --models /path/to/original_models \
  --fasta /path/to/representatives.fasta \
  --output /path/to/new_quality_results \
  --p2rank /path/to/p2rank_2.5.1/prank \
  --title "My pocket project"
```

To reuse completed full-length pocket results without rerunning predictors,
the previous `pocket-workbench build` and `scripts/submit_maddy_brca1.sh`
workflow remains available; see [HPC workflow](docs/HPC_WORKFLOW.md).
Existing 1.0/1.1 native app resources remain readable.

The app retains 3D pocket/superposition views, residue mapping, pocket-marked
FASTA alignments, trees, HOG/model-group comparison, manual external Inspector
ZIPs, help, searchable glossary, Excel and DuckDB downloads. Bulk ZIP import
also remains available. New HPC quality preparation is a batch command.

See [methods](docs/METHODS.md), [deployment](docs/DEPLOYMENT.md),
[inputs](docs/INPUTS.md), [schema](docs/SCHEMA.md) and
[validation and test limits](docs/VALIDATION.md).

No real BRCA1 rerun or Dundee submission was performed in this development
workspace. Automated tests use explicitly synthetic models and predictor
fixtures; real USalign/TMalign execution and offline browser behaviour are
tested separately. The included real BRCA1 example has earlier report tables
only, without fabricated coordinates.
