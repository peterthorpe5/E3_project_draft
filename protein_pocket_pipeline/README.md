# Protein Pocket Pipeline

Predict and rank candidate small-molecule binding pockets from **local, de novo
AlphaFold models**. Supply a folder of PDB/mmCIF files, then open the resulting
HTML report or Excel workbook. Each model is analysed independently. FASTA is
optional and checks that a structure represents the intended sequence.

This is a standalone Python package. It does **not** require the E3 discovery
pipeline, an E3 database, UniProt accessions, an app or a web server. A ZIP of this
folder is sufficient to install the package on another machine.

## Install once

From this folder, on Linux or macOS:

```bash
conda env create --file environment.yml
conda activate protein_pockets
python -m pip install --editable .
```

Install [P2Rank 2.5.1](https://github.com/rdk/p2rank/releases/tag/2.5.1)
separately, or use an existing installation. The supplied environment includes
fpocket 4.2.2 and Java 17. See [installation](docs/INSTALLATION.md) for the exact
P2Rank download, checksum, version check and Windows/WSL instructions.

## Run

```bash
protein-pockets run \
  --models /path/to/alphafold_models \
  --output /path/to/pocket_results \
  --p2rank /path/to/p2rank_2.5.1/prank
```

The model folder must be flat. Its `.pdb`, `.cif` and `.mmcif` files are read;
other files are ignored. A model's filename stem becomes its `sample_id`. Use
letters, numbers, underscores, dots or hyphens, beginning with a letter/number.
Every model needs a unique identifier, including on case-insensitive filesystems.
AF3 structures can remain in mmCIF format. Extract any server ZIP archives first.

To check representative FASTA sequences too:

```bash
protein-pockets run \
  --models /path/to/alphafold_models \
  --fasta /path/to/representatives.fasta \
  --output /path/to/pocket_results \
  --p2rank /path/to/p2rank_2.5.1/prank
```

With this simple folder route, FASTA identifiers must exactly match filename
stems. If names differ, files live in subfolders, several models share one
sequence, or a target chain must be selected, use a
[manifest TSV](docs/INPUTS.md) instead. No filename-to-sequence guessing occurs.

The default assumes B fields contain AlphaFold pLDDT. For experimental structures
or models whose confidence was lost during conversion, set `--confidence none`.
The pipeline cannot determine the AlphaFold generation or reconstruct absent
confidence values from coordinates.

## What happens

1. Validate each model and prepare protein heavy atoms, retaining an explicit
   map back to original chains, residue numbers and insertion codes.
2. Run **fpocket** to find cavities and extract its druggability score, volume
   and all other available native pocket descriptors.
3. Run **P2Rank prediction**, using its `alphafold` profile, to predict sites
   independently of fpocket.
4. Run **P2Rank rescoring** on the **same fpocket output**, using the explicit
   `rescore_2024` profile. This is the rescoring choice used in the E3 package;
   P2Rank describes this profile as experimental.
5. Annotate each pocket with local pLDDT and its original lining residues. Record
   within-model residue overlap between independent predictions and fpocket.
6. Write the same results to Excel, HTML, TSV and a materialised DuckDB database.

## Read the results

| Start with | Contents |
| --- | --- |
| `report.html` | Offline browser with model/search/confidence filters, sortable tables and file links |
| `excel/protein_pockets.xlsx` | Combined workbook; open **Ranked_cavities** first |
| `excel/models/<sample_id>.xlsx` | A complete workbook for one model |
| `tables/ranked_pockets.tsv` | Ranked fpocket cavities in a machine-readable table |
| `database/protein_pockets.duckdb` | Typed results and app-friendly views, with no external file dependencies |
| `tables/field_dictionary.tsv` | Column meanings and types, also included in every workbook |
| `logs/<sample_id>/` | Command arguments, stdout, stderr and timings |
| `tool_outputs/<sample_id>/` | Native tool evidence, TSV conversions and P2Rank visualisation scripts |
| `inputs/` and `models/` | Unmodified input copies, prepared structures and residue maps |
| `provenance/` and `checkpoints/` | Versions, configuration, checksums and resumable per-model state |

Keep the result directory together when copying it: the HTML tables are embedded,
but its download links need the adjacent folders. All tabular outputs are TSV.
P2Rank's internally generated CSV files are converted to TSV before each stage
finishes, including unsuccessful stages.

**Ranks restart for every model.** The main cavity ranking follows P2Rank's
rescoring rank. If rescoring is disabled or fails, every cavity in that model
uses fpocket druggability instead, and `ranking_basis` says so explicitly.
Independent P2Rank pockets keep their own native ranks in **All_pockets** and the
HTML's **Independent P2Rank** tab. Confidence does not silently change the rank.

The default local confidence flag requires at least **80% of all predicted lining
residues to have pLDDT ≥70**, with complete residue mapping. This is an explicit,
adjustable review rule. It is not a validated druggability cut-off. Low-confidence
pockets remain visible. Missing measurements are blank/NULL, never silently zero.

These are predicted binding-site features. A high score does not demonstrate
binding, affinity, selectivity, an inhibitory effect or therapeutic usefulness.
See [methods and interpretation](docs/METHODS.md).

## Resume or submit a job

Repeat the **identical** run command with `--resume` to reuse intact completed
models and retry failures. Input, option, software or tool-model changes require a
new output directory. Checkpoints and retained model/tool files are verified
before reuse. Existing results are not appended or duplicated.

For Slurm, activate the environment first and use
[the optional wrapper](scripts/README.md). Defaults are Dundee's `barton`
account and `general` partition; override these with your own site's `sbatch`
options. A normal denbi/Linux server needs no scheduler wrapper.

Exit statuses: `0` = complete, including valid no-pocket results; `1` = setup,
input or export error; `2` = at least one failed/partial model; `130` = interrupted.
Failed models and tool-specific errors remain in the report.

## Documentation and checks

- [Installation](docs/INSTALLATION.md)
- [Inputs, optional FASTA and target chains](docs/INPUTS.md)
- [Methods, ranking and confidence](docs/METHODS.md)
- [Output schema and DuckDB queries](docs/OUTPUTS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Testing and validation](tests/README.md)
- [Origin and differences from the E3 workflow](docs/PROVENANCE.md)

```bash
python -m pip install --editable '.[dev]'
python -m pytest --cov=protein_pockets --cov-report=term-missing
ruff check .
ruff format --check .
```

The package enforces 95% test coverage, including branches. Real external-tool
smoke testing is separately documented and does not pretend to validate the
biological interpretation of a particular AlphaFold model.

Version 1.0.0. [MIT licence](LICENSE).
