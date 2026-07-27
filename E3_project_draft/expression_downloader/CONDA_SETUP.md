# Conda setup for E3AtlasDuckplyr

The preferred setup on the cluster is conda/mamba rather than installing R packages from inside R.

## Option A: install into your existing environment

```bash
conda activate Go_analysis2

# mamba is faster, but conda is also fine if mamba is unavailable.
mamba install -c conda-forge -c bioconda \
  pyarrow \
  r-dplyr \
  r-duckplyr \
  r-duckdb \
  r-fs \
  r-httr2 \
  r-purrr \
  r-readr \
  r-rlang \
  r-stringr \
  r-tibble \
  r-tidyr \
  r-xml2 \
  r-testthat \
  bioconductor-expressionatlas
```

If `mamba` is not available, use the same command with `conda install`.

## Option B: create a clean environment

```bash
mamba env create -f envs/e3_atlas_duckplyr.yml
conda activate e3_atlas_duckplyr
```

or:

```bash
bash inst/scripts/00_create_conda_env.sh
conda activate e3_atlas_duckplyr
```

## Check dependencies

```bash
Rscript inst/scripts/00_check_dependencies.R
python -c "import pyarrow; print(pyarrow.__version__)"
```

## Install the local package

Once the conda dependencies are present:

```bash
R CMD INSTALL .
```

The scripts can also run directly from the unpacked source tree without package installation because `inst/scripts/_bootstrap.R` sources the local `R/` files if the package is not installed.

## Run the pipeline

```bash
Rscript inst/scripts/run_all.R \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_dir=analysis/expression_atlas \
  --force_download=false \
  --force_import=false \
  --create_duckdb=true
```

## Run the tests

```bash
R CMD INSTALL .
Rscript inst/scripts/08_run_tests.R
./inst/scripts/09_run_python_tests.sh
```
