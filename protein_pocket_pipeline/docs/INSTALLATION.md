# Installation

The analysis code needs Python 3.11 or later, Gemmi, DuckDB and openpyxl. The
external tools are **fpocket 4.2.2** and **P2Rank 2.5.1**, with **Java 17**.
Analysis uses local files and makes no internet requests. Installation requires
access to the package repositories and P2Rank download, unless already installed.

## Linux / denbi / macOS

```bash
cd /path/to/protein_pocket_pipeline
conda env create --file environment.yml
conda activate protein_pockets
python -m pip install --editable .
```

If you already have compatible Python, fpocket and Java installations:

```bash
python -m pip install /path/to/protein_pocket_pipeline
```

You can install this folder directly after extracting the standalone ZIP; it does
not import anything from another folder in `E3_project_draft`.

## P2Rank

Use an existing P2Rank 2.5.1 installation or download the official release. Choose
a software directory that will remain available to compute jobs:

```bash
mkdir -p /path/to/software
cd /path/to/software
curl --fail --location \
  --output p2rank_2.5.1.tar.gz \
  https://github.com/rdk/p2rank/releases/download/2.5.1/p2rank_2.5.1.tar.gz
tar --no-same-owner -xzf p2rank_2.5.1.tar.gz
chmod +x p2rank_2.5.1/prank
```

The release archive used for validation has SHA-256:

```text
d243f2d9036ac053fefb9407b5fe1c85f4fe077c519fd975ac585e995feab274
```

Check with `sha256sum p2rank_2.5.1.tar.gz` on Linux or
`shasum -a 256 p2rank_2.5.1.tar.gz` on macOS. The archive is approximately 263 MiB.
It contains model weights and test structures as well as the executable.

## Preflight

```bash
protein-pockets check \
  --fpocket fpocket \
  --p2rank /path/to/software/p2rank_2.5.1/prank \
  --output tool_versions.json
```

Alternatively add that P2Rank directory to `PATH`, after which `--p2rank` can be
omitted. The command checks P2Rank's version and records fpocket's help/version
output. fpocket's version reporting is less consistent, so its binary checksum is
also retained; the supplied environment pins its version. P2Rank's launcher,
library JARs, configurations, selected model weights and calibration files are
fingerprinted. P2Rank 2.5.1's documented commands and output formats were used for
development; a newer version should be checked separately rather than assumed
equivalent. `--require-p2rank` exists for a deliberately reviewed version change.

## Resource use

Start with `--threads 4` and 16 GiB RAM for a small set of representative models.
Samples run sequentially to bound memory, and P2Rank receives the requested thread
count. P2Rank's launcher normally sets a 2 GiB Java heap. Very large proteins may
need that launcher setting increased by the server administrator. The per-command
timeout defaults to 3,600 seconds and can be changed with `--timeout`.

No numerical runtime guarantee is assumed for BRCA1 or for the 14 supplied models.
Run one representative first, then the complete model folder.

## Windows

Use WSL2 with a Linux Conda installation and run the same instructions inside WSL.
This release's command management uses POSIX process groups to terminate whole
tool trees. Native Windows execution is not supported. The generated Excel and
HTML files can be opened normally in Windows.

## Development checks

```bash
python -m pip install --editable '.[dev]'
python -m pytest --cov=protein_pockets --cov-report=term-missing
ruff check .
ruff format --check .
```

An optional [real-tool test](../tests/README.md) uses a local structure and the
same command-line tools as a scientific run.
