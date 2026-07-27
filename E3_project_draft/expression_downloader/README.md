# E3AtlasDuckplyr

`E3AtlasDuckplyr` is a small R package/script bundle for building an incremental Expression Atlas import layer for the E3 ligase/HOG resource.

It is designed for the current project situation:

- species are maintained in a simple editable `data/species.txt` file;
- Expression Atlas experiment discovery can be attempted programmatically;
- manually curated experiment accessions can also be supplied;
- remote files are checked before download;
- by default, only experiments with downloadable TPM/FPKM expression matrices are selected, so metadata-only and most microarray-only hits are ignored;
- existing local non-empty files are skipped;
- large expression matrices are converted to long Parquet with a streaming Python/pyarrow importer by default;
- SDRF/condensed-SDRF sample metadata are imported as separate long and wide Parquet datasets;
- future Shiny queries can use lazy `duckplyr` tables rather than loading expression data into memory;
- gene/protein identifier aliases are kept in a separate table so different naming systems can be joined later.

No comma-separated output files are produced. Manifests are TSV and large queryable tables are Parquet/DuckDB-backed.

## Folder layout

```text
e3_atlas_duckplyr/
  R/                              Package functions
  inst/scripts/                   Runnable R and shell scripts
  inst/python/                    Python discovery/download and Parquet import helpers
  data/species.txt                Editable species list
  data/species_overrides.tsv      Optional species name/query corrections
  data/manual_experiments_template.tsv
  tests/testthat/                 Unit tests
  README.md
```

When run, the default output is:

```text
analysis/expression_atlas/
  manifests/
    species_registry.tsv
    atlas_candidate_experiments.tsv
    atlas_ftp_manifest.tsv
    atlas_checked_file_manifest.tsv
    atlas_expression_matrix_availability.tsv
    atlas_selected_checked_file_manifest.tsv
    atlas_download_log.tsv
    atlas_downloaded_files.tsv
    atlas_expression_import_summary.tsv
    atlas_sample_metadata_import_summary.tsv
    gene_identifier_aliases.tsv
  downloads/
    <species>/<experiment_accession>/...
  parquet/
    atlas_expression_long/
      species_column=<species>/experiment_accession=<experiment>/tpms.parquet
      species_column=<species>/experiment_accession=<experiment>/fpkms.parquet
    atlas_sample_metadata_long/
      species_column=<species>/experiment_accession=<experiment>/sample_metadata.parquet
    atlas_sample_metadata_wide/
      species_column=<species>/experiment_accession=<experiment>/sample_metadata.parquet
    gene_identifier_aliases/
      gene_identifier_aliases.parquet
  e3_expression.duckdb
```

## 1. Install dependencies with conda/mamba

The recommended cluster setup is to install the R dependencies with conda/mamba rather than using `install.packages()` inside R. `r-duckplyr`, `r-readr` and `r-duckdb` are available from conda-forge, and `ExpressionAtlas` is available from Bioconda as `bioconductor-expressionatlas`.

Install into your existing environment:

```bash
conda activate Go_analysis2

# mamba is faster, but conda install is also fine if mamba is unavailable.
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

Or create a clean environment:

```bash
mamba env create -f envs/e3_atlas_duckplyr.yml
conda activate e3_atlas_duckplyr
```

Then check the R and Python dependencies:

```bash
Rscript inst/scripts/00_check_dependencies.R
python -c "import pyarrow; print(pyarrow.__version__)"
```

The old `inst/scripts/00_install_dependencies.R` script is still present, but conda/mamba is preferred for the cluster. That script now sets `https://cloud.r-project.org` explicitly if it is used, avoiding the CRAN mirror error.

## 2. Run the unit tests

From inside the unpacked package directory:

```bash
R CMD INSTALL .
Rscript inst/scripts/08_run_tests.R
./inst/scripts/09_run_python_tests.sh

# or, equivalently:
Rscript -e 'library(E3AtlasDuckplyr); testthat::test_dir("tests/testthat")'
```

Or, if you use `devtools`:

```r
devtools::test()
```

The tests are deliberately mostly local/offline. One test exercises a small DuckDB/Parquet import if `duckplyr` is available.

## 3. Edit the species list

The main editable file is:

```text
data/species.txt
```

Add one species per line. Underscores or spaces are both accepted:

```text
Arabidopsis_thaliana
Zea mays
Brassica_napus
```

Then rerun the pipeline. Existing downloaded files that are present and non-empty will be skipped.

Species-specific corrections can go in:

```text
data/species_overrides.tsv
```

This is useful when Expression Atlas uses an updated or alternative species name.

## 4. Full pipeline run

From inside the unpacked package directory:

```bash
./inst/scripts/run_python_first_then_r.sh \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_dir=analysis/expression_atlas \
  --force_download=false \
  --force_import=false \
  --create_duckdb=true \
  --import_backend=python \
  --expression_file_types=tpms,fpkms
```

This will:

1. build `species_registry.tsv`;
2. search Expression Atlas for candidate RNA-seq/baseline experiments;
3. build expected Expression Atlas FTP paths;
4. check remote files before downloading;
5. skip any local files that already exist and are non-empty;
6. select only experiments with downloadable TPM/FPKM matrices by default;
7. download available files for selected experiments, including matching SDRF and methods metadata;
8. normalise TPM/FPKM matrices to long Parquet with the Python streaming importer;
9. import SDRF/condensed-SDRF sample metadata into long and wide Parquet datasets;
10. create a DuckDB database with views over the Parquet files.


### Reimport existing downloads with the Python importer

If downloads already exist but old Parquet files are empty, do not redownload.
Rebuild only the Parquet files and DuckDB views:

```bash
./inst/scripts/04_python_import_expression_to_parquet.sh \
  --downloaded_files_tsv=../analysis/expression_atlas_ftp_full/manifests/atlas_downloaded_files.tsv \
  --output_dir=../analysis/expression_atlas_ftp_full \
  --force_import=true \
  --chunk_rows=250000

Rscript inst/scripts/06_create_duckdb_views.R \
  --output_dir=../analysis/expression_atlas_ftp_full \
  --duckdb_path=../analysis/expression_atlas_ftp_full/e3_expression.duckdb
```

## 5. If ExpressionAtlas searching is not available

You can provide manually curated experiment accessions instead.

Copy the template:

```bash
cp data/manual_experiments_template.tsv data/manual_experiments.tsv
```

Edit it so it contains at least:

```text
species_column	experiment_accession
Zea_mays	E-MTAB-5915
```

Then run:

```bash
Rscript inst/scripts/run_all.R \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --manual_experiment_tsv=data/manual_experiments.tsv \
  --output_dir=analysis/expression_atlas \
  --force_download=false \
  --force_import=false \
  --create_duckdb=true \
  --require_expression_matrix=true \
  --expression_file_types=tpms,fpkms
```

## 6. Optional Python download step

The R pipeline now has the duplicate-URL manifest bug fixed, so `run_all.R` should work. However, the remote file checking and download part can also be done in Python, which is often easier to debug on a cluster. This keeps the downstream import and Shiny/duckplyr work in R, but uses Python for HTTP checks, retries and downloads. The Python helper uses only the Python standard library.

Run discovery and build the FTP manifest in R:

```bash
Rscript inst/scripts/01_build_species_registry.R \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_tsv=../analysis/expression_atlas/manifests/species_registry.tsv

Rscript inst/scripts/02_search_atlas_experiments.R \
  --species_registry_tsv=../analysis/expression_atlas/manifests/species_registry.tsv \
  --output_tsv=../analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv

Rscript inst/scripts/03a_build_ftp_manifest.R \
  --experiment_manifest_tsv=../analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv \
  --output_dir=../analysis/expression_atlas
```

Then check/download the files with Python:

```bash
./inst/scripts/03b_download_atlas_files_python.sh \
  --output_dir=../analysis/expression_atlas \
  --force_download=false \
  --require_expression_matrix=true \
  --expression_file_types=tpms,fpkms \
  --timeout_seconds=30 \
  --retries=2
```

Then return to R for Parquet/DuckDB/duckplyr import:

```bash
Rscript inst/scripts/04_import_expression_to_parquet.R \
  --downloaded_files_tsv=../analysis/expression_atlas/manifests/atlas_downloaded_files.tsv \
  --output_dir=../analysis/expression_atlas \
  --force_import=false

Rscript inst/scripts/06_create_duckdb_views.R \
  --output_dir=../analysis/expression_atlas \
  --duckdb_path=../analysis/expression_atlas/e3_expression.duckdb
```

## 7. Run step-by-step instead of all at once

```bash
Rscript inst/scripts/01_build_species_registry.R \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_tsv=analysis/expression_atlas/manifests/species_registry.tsv

Rscript inst/scripts/02_search_atlas_experiments.R \
  --species_registry_tsv=analysis/expression_atlas/manifests/species_registry.tsv \
  --output_tsv=analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv

Rscript inst/scripts/03_download_atlas_files.R \
  --experiment_manifest_tsv=analysis/expression_atlas/manifests/atlas_candidate_experiments.tsv \
  --output_dir=analysis/expression_atlas \
  --force_download=false \
  --require_expression_matrix=true \
  --expression_file_types=tpms,fpkms

Rscript inst/scripts/04_import_expression_to_parquet.R \
  --downloaded_files_tsv=analysis/expression_atlas/manifests/atlas_downloaded_files.tsv \
  --output_dir=analysis/expression_atlas \
  --force_import=false

Rscript inst/scripts/06_create_duckdb_views.R \
  --output_dir=analysis/expression_atlas \
  --duckdb_path=analysis/expression_atlas/e3_expression.duckdb
```

## 8. Identifier aliases

Once you have either an exported `e3_ligases.tsv` or the inherited SQLite database, build an alias table.

From TSV:

```bash
Rscript inst/scripts/05_extract_identifier_aliases.R \
  --e3_tsv=/path/to/e3_ligases.tsv \
  --output_dir=analysis/expression_atlas
```

From SQLite using DuckDB's SQLite scanner:

```bash
Rscript inst/scripts/05_extract_identifier_aliases.R \
  --sqlite_path=/path/to/e3_ligases.sqlite \
  --table_name=e3_ligases \
  --install_sqlite_extension=false \
  --output_dir=analysis/expression_atlas
```

If the SQLite scanner extension is not already available in DuckDB, rerun with:

```bash
--install_sqlite_extension=true
```

That may require internet access on the machine running DuckDB.

The alias table captures:

- E3 entry IDs;
- protein accessions;
- entry names;
- split gene-name aliases;
- species names in the same internal `species_column` style used by the expression data.

## 8. Query expression data through duckplyr

Parquet-backed query:

```r
library(dplyr)
library(duckplyr)
library(E3AtlasDuckplyr)

expression_tbl <- read_expression_parquet_duckplyr(
  parquet_glob = "analysis/expression_atlas/parquet/atlas_expression_long/**/*.parquet"
)

filtered_tbl <- filter_expression_duckplyr(
  expression_tbl = expression_tbl,
  species_column = "Arabidopsis_thaliana",
  expression_unit = "TPM",
  minimum_expression = 1
)

filtered_tbl |>
  select(
    experiment_accession,
    species_column,
    gene_id,
    gene_name,
    sample_or_condition,
    expression_value,
    expression_unit
  ) |>
  head(100L) |>
  collect()
```

DuckDB-view-backed query:

```r
library(dplyr)
library(duckplyr)
library(E3AtlasDuckplyr)

expression_tbl <- read_duckdb_table_duckplyr(
  duckdb_path = "analysis/expression_atlas/e3_expression.duckdb",
  table_name = "atlas_expression_long"
)

expression_tbl |>
  filter(species_column == "Zea_mays") |>
  filter(expression_unit == "TPM") |>
  filter(expression_value >= 1) |>
  head(100L) |>
  collect()
```

## 9. Shiny pattern

Inside Shiny, create the lazy table once when the app starts, then filter reactively. Only collect a small display subset.

```r
expression_tbl <- read_expression_parquet_duckplyr(
  parquet_glob = "analysis/expression_atlas/parquet/atlas_expression_long/**/*.parquet"
)

filtered_expression <- reactive({
  expression_tbl |>
    filter(species_column == input$species) |>
    filter(expression_unit == input$expression_unit) |>
    filter(expression_value >= input$minimum_expression) |>
    select(
      species_column,
      experiment_accession,
      gene_id,
      gene_name,
      sample_or_condition,
      expression_value,
      expression_unit
    )
})

output$expression_table <- DT::renderDataTable({
  filtered_expression() |>
    head(1000L) |>
    collect()
})
```

## 10. Notes and limitations

- This is an import/query scaffold, not a final biological interpretation layer.
- Expression Atlas experiment discovery should be reviewed manually before relying on it for final prioritisation.
- Identifier mapping will need additional curation because E3 accessions, UniProt IDs, Ensembl/Ensembl Plants IDs, gene symbols and Atlas gene IDs may differ.
- The package starts by preserving observed aliases from the inherited E3 table. A later layer can add UniProt, Ensembl Plants BioMart or other mappings.
- Large matrices are not read into R memory during Parquet import; DuckDB SQL handles the wide-to-long conversion.


## Version 0.1.5 note

This version adds the default RNA-seq/normalised-expression filter. Candidate experiments are still discovered broadly, but after remote checks the downloader keeps only experiments where a TPM or FPKM matrix exists. It then downloads those matrices plus their matching SDRF/methods metadata. This avoids filling `downloads/` with metadata-only or microarray-only experiments that cannot be converted into the long expression Parquet table.

## Version 0.1.4 note

This version fixes a manifest-checking failure caused by a duplicate `url` column when unnesting remote-status results. It also adds an optional Python downloader for the remote-check/download stage.


## Python-first Expression Atlas workflow

For cluster runs, prefer the Python-first workflow documented in
`PYTHON_FIRST_WORKFLOW.md`. It uses Python for web discovery/downloads and R for
Parquet/DuckDB/duckplyr import.

Quick command from the package root:

```bash
./inst/scripts/run_python_first_then_r.sh \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_dir=../analysis/expression_atlas_python \
  --force_download=false \
  --force_import=false \
  --create_duckdb=true
```


## v0.2.1 note

The Python-first downloader now uses an FTP-scan discovery backend by default. This avoids brittle Expression Atlas / ArrayExpress XML searches by listing Expression Atlas experiment directories from the public FTP index, checking for real TPM/FPKM matrices, and then matching experiments back to the requested species using SDRF metadata where available.


## v0.3.1 notes

This version keeps the project broad across the tree of life: the pipeline imports expression data for any species listed in `data/species.txt`, not just plants. Plant-focused resources can be added later as separate source modules, but this package now treats Expression Atlas as the first cross-species expression source.

New in v0.3.1:

- Python/pyarrow remains the default expression importer.
- Long expression rows now include `source_database`, currently `ExpressionAtlas`.
- SDRF and condensed-SDRF files are imported into:
  - `atlas_sample_metadata_long`
  - `atlas_sample_metadata_wide`
- DuckDB views are created for:
  - `atlas_expression_long`
  - `atlas_expression_tpm`
  - `atlas_expression_fpkm`
  - `atlas_sample_metadata_long`
  - `atlas_sample_metadata_wide`
  - `atlas_expression_with_sample_metadata` when wide metadata are available.
- The joined view allows future Shiny filters on species, experiment, expression unit, tissue/organism part, developmental stage, genotype, treatment and condition where Atlas metadata provide those fields.

To rebuild metadata only from existing downloads:

```bash
./inst/scripts/05_python_import_sample_metadata_to_parquet.sh \
  --downloaded_files_tsv=../analysis/expression_atlas_ftp_full/manifests/atlas_downloaded_files.tsv \
  --output_dir=../analysis/expression_atlas_ftp_full \
  --force_import=true

Rscript inst/scripts/06_create_duckdb_views.R \
  --output_dir=../analysis/expression_atlas_ftp_full \
  --duckdb_path=../analysis/expression_atlas_ftp_full/e3_expression.duckdb
```

Example metadata-aware query:

```r
library(duckplyr)
library(dplyr)

expr_meta <- E3AtlasDuckplyr::read_expression_with_sample_metadata_duckplyr(
  duckdb_path = "../analysis/expression_atlas_ftp_full/e3_expression.duckdb"
)

expr_meta |>
  filter(species_column == "Zea_mays") |>
  filter(expression_unit == "TPM") |>
  filter(expression_value >= 1) |>
  select(
    experiment_accession,
    gene_id,
    sample_or_condition,
    organism_part,
    developmental_stage,
    treatment,
    expression_value
  ) |>
  head(20) |>
  collect()
```


## v0.3.2 notes

- Fixes a file-descriptor leak in the Python sample metadata importer that could
  trigger `OSError: [Errno 24] Too many open files` during large imports.
- Updates script bootstrapping so command-line scripts prefer the local source
  tree over an older installed package, avoiding missing-function errors after
  pulling a new patch.
- The expression Parquet files do not need to be rebuilt for this patch.
