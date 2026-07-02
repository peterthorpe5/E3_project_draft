# E3 source-to-Parquet seed rebuild

Version: **0.2.0**

This package is a source-first scaffold for rebuilding the inherited E3/plant
PROTAC data resource into a clean, auditable Parquet + DuckDB layout.

It deliberately does **not** treat the inherited SQLite database as the source of
truth. The SQLite database is still useful as a reference and regression target,
but the cleaner long-term route is:

```text
curated inherited source files
    -> source-preserving Parquet tables
    -> curated biological Parquet tables
    -> DuckDB views
    -> Shiny app
```

The immediate purpose of this package is to make the inherited data manageable
without losing provenance.

---

## What changed in v0.2.0

This version fixes the first real run problem seen on macOS external-drive
copies:

```text
_duckdb.InvalidInputException:
No magic bytes found at end of file .../._concated_seqs.parquet
```

That file is a macOS AppleDouble/resource-fork sidecar. It has a `.parquet`
suffix but is not a real Parquet file. DuckDB quite correctly refuses to read it.

v0.2.0 now:

- skips macOS sidecar files such as `._file.parquet` throughout scanning,
  inherited-Parquet copying, and DuckDB view creation;
- validates Parquet files using the `PAR1` header/footer before asking DuckDB to
  create views;
- writes clearer derived folder names instead of carrying vague inherited names
  such as `Main_folder` into our working output paths;
- keeps the original inherited path in provenance columns, so no traceability is
  lost;
- adds a dry-run/delete helper for removing macOS sidecar files;
- expands the unit test suite from 13 to 26 tests.

---

## Design principles

### 1. Source-first, not SQLite-first

The inherited SQLite database may contain mistakes or historical joins that are
hard to audit. Therefore the rebuild starts from the copied source files where
possible.

The SQLite DB should be used later for regression tests, for example:

- do old example SQL queries still return the same candidates?
- do row counts broadly agree where they should?
- did we deliberately improve or correct any inherited behaviour?

### 2. Keep separate Parquet tables

Do **not** collapse everything into one large Parquet file.

The preferred structure is several logical Parquet layers:

```text
derived/parquet/source_tables/
derived/parquet/sequences/
derived/parquet/text/
derived/parquet/inherited_parquet/
derived/duckdb/e3_protac_resource.duckdb
derived/qc/
```

DuckDB then creates views over those Parquet files.

This gives several advantages:

- easier to debug individual source files;
- easier to replace one layer later;
- safer when adding new species;
- safer when Orthofinder/HOG results are added;
- less chance of creating one opaque table full of mixed biological concepts.

### 3. Preserve metadata aggressively

Every generated table should carry as much provenance as possible.

For tabular source files, the package adds columns such as:

```text
_row_number_in_source
_source_file
_source_kind
_source_sheet
_source_file_sha256
_source_file_size_bytes
_source_file_mtime_utc
_ingested_at_utc
_original_columns_json
```

For FASTA source files, the package keeps:

```text
sequence_record_number
inferred_accession
fasta_header
sequence
sequence_length
sequence_md5
_source_file
_source_file_sha256
_source_file_size_bytes
_source_file_mtime_utc
_ingested_at_utc
```

This is intentional. Some of the metadata may look excessive now, but it will be
useful later when debugging joins, checking source versions, or defending the
rebuild.

### 4. Better folder names in our derived outputs

The inherited project uses vague folder names such as `Main_folder` and
`Other_things`. In the derived outputs, v0.2.0 maps these to clearer names.

Examples:

```text
Main_folder/E3_database
    -> curated_e3_database

Main_folder/Reports
    -> inherited_reports

Main_folder/Other_people_data
    -> literature_reference_datasets

Other_things/Drost_lab_E3_ligases
    -> e3_ligase_discovery_inputs

Other_things/Drost_lab_ligandability
    -> ligandability_inputs

Other_things/Denbi/denbi_data/E3_discovery_engine
    -> deepclust_discovery_engine

Other_things/Drost_lab_proteomes
    -> proteome_source_inputs

Other_things/Desktop
    -> inherited_desktop_outputs
```

Important: this only affects **derived output paths and view names**. Original
source paths are still preserved in `_source_file` and in the manifest.

---

## Installation

A conda environment is recommended.

```bash
conda create -n e3_parquet_rebuild -c conda-forge \
  python=3.11 pandas pyarrow openpyxl duckdb python-duckdb

conda activate e3_parquet_rebuild
```

Or install into an existing environment:

```bash
conda install -c conda-forge pandas pyarrow openpyxl duckdb python-duckdb
```

---

## Run the tests

From the package directory:

```bash
python -m unittest discover -s tests -v
```

The package was prepared with `unittest` because this is reliable on the user's
current systems and matches the preferred project style.

Expected result for v0.2.0:

```text
Ran 26 tests

OK
```

---

## Expected working-copy layout

The package expects a curated working copy similar to:

```text
E3_PROTAC_curated_working_copy_YYYYMMDD_HHMMSS/
├── raw_inherited_selected/
├── manifests/
└── derived/
```

The `raw_inherited_selected/` directory should contain only the selected source
files copied from Erin's inherited external-drive data.

Do not run this over the entire external drive. The point is to work from a
small, explicit, curated source set.

---

## Standard run

Set your project root:

```bash
PROJECT_ROOT="/Volumes/ExtremeSSD/E3_PROTAC_curated_working_copy_20260702_105742"
```

Then run:

```bash
./run_e3_seed_pipeline.sh "${PROJECT_ROOT}"
```

This does three main steps:

1. build a manifest;
2. convert source files to Parquet;
3. create DuckDB views over the generated Parquet files.

---

## If you already ran v0.1 and only DuckDB creation failed

You do **not** need to rerun the full conversion immediately.

You can run just the sidecar report and DuckDB view step with v0.2.0.

First, report sidecar files:

```bash
python scripts/e3_clean_macos_sidecars.py \
  --root "${PROJECT_ROOT}/derived" \
  --out-tsv "${PROJECT_ROOT}/derived/qc/macos_sidecar_report.tsv"
```

If the report only contains `._*` and `.DS_Store` style files, delete them:

```bash
python scripts/e3_clean_macos_sidecars.py \
  --root "${PROJECT_ROOT}/derived" \
  --out-tsv "${PROJECT_ROOT}/derived/qc/macos_sidecar_deleted.tsv" \
  --delete
```

Then recreate DuckDB views:

```bash
python scripts/e3_create_duckdb_views.py \
  --derived-dir "${PROJECT_ROOT}/derived" \
  --duckdb-path "${PROJECT_ROOT}/derived/duckdb/e3_protac_resource.duckdb"
```

v0.2.0 should also skip those invalid files automatically, but deleting sidecars
from the derived directory keeps the working copy cleaner.

---

## Should inherited Parquet files be included?

Yes, but carefully.

The inherited Parquet files should be included as their own layer, not merged
into one giant table. They are useful because Erin had already started to move
some DeepClust outputs into Parquet.

In the current curated source set, the important inherited Parquet files are
likely:

```text
deepclust_discovery_engine/concat_file/concated_seqs.parquet
deepclust_discovery_engine/diamond_files/realigned_clusters.parquet
deepclust_discovery_engine/output/E3_deepclust_alignment_results.parquet
```

These should remain under:

```text
derived/parquet/inherited_parquet/
```

They are not yet the final biological tables. They are source-preserving inputs
for the next layer.

Do not include every Parquet file blindly. The safest rule is:

- include genuine Parquet files that are directly relevant to E3 discovery,
  DeepClust clustering, source sequence mapping, or alignment evidence;
- skip benchmark repeats unless we specifically need them;
- skip macOS sidecars and invalid files;
- keep the source manifest and copied-Parquet catalogue.

---

## Output files to inspect after a successful run

After running, inspect:

```text
derived/qc/source_file_manifest.tsv
derived/qc/tabular_table_catalog.tsv
derived/qc/fasta_table_catalog.tsv
derived/qc/text_file_catalog.tsv
derived/qc/copied_existing_parquet_catalog.tsv
derived/qc/duckdb_view_catalog.tsv
```

Useful commands:

```bash
column -t -s $'\t' "${PROJECT_ROOT}/derived/qc/tabular_table_catalog.tsv" | less -S
column -t -s $'\t' "${PROJECT_ROOT}/derived/qc/fasta_table_catalog.tsv" | less -S
column -t -s $'\t' "${PROJECT_ROOT}/derived/qc/copied_existing_parquet_catalog.tsv" | less -S
column -t -s $'\t' "${PROJECT_ROOT}/derived/qc/duckdb_view_catalog.tsv" | less -S
```

---

## Current intended biological layers

This package creates a source-preserving layer first. The next package version
should begin creating curated biological tables such as:

```text
protein_records.parquet
protein_sequences.parquet
identifier_aliases.parquet
literature_evidence.parquet
go_term_evidence.parquet
ligandability_pocket_scores.parquet
ligandability_pocket_details.parquet
deepclust_cluster_members.parquet
```

Later, Orthofinder/HOG integration should add:

```text
orthogroup_members.parquet
hog_members.parquet
orthogroup_species_counts.parquet
hog_species_counts.parquet
orthogroup_sequence_exports.parquet
```

The Shiny app should query DuckDB views built over these tables, not load source
CSV/XLSX/FASTA files directly.

---

## What not to do

Avoid:

- creating one huge merged Parquet file too early;
- losing original source paths;
- coercing identifiers into numeric columns;
- trusting the inherited SQLite DB without regression checks;
- using vague inherited folder names for new outputs;
- including Orthofinder wholesale before we have identified the exact files
  needed.

---

## Coding standards

All new Python code should follow the project standard:

- PEP8-style formatting;
- docstrings for public helpers/scripts;
- defensive error handling;
- logging to file and console;
- `unittest` tests;
- source-preserving data handling;
- no silent destructive behaviour.

The same standards should apply to any later R code:

- explicit functions;
- tests where practical;
- logging/messages suitable for HPC;
- no full-table collection in Shiny;
- DuckDB filtering before collecting into R.
