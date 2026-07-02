# Data resource guide

This file describes the intended data layout for the E3 PROTAC source-first resource.

## Current layers

### Raw selected files

`raw_inherited_selected/` contains a curated copy of the inherited files selected for rebuild. The original inherited paths are preserved below this directory, but future derived output uses clearer folder names.

### Source-preserving Parquet

`derived/parquet/` contains mechanically converted source tables. These tables should not be over-interpreted yet. Their job is to preserve the original data with explicit provenance.

Expected groups include:

- `source_tables/`: CSV, TSV and Excel sheets converted to Parquet.
- `sequences/`: FASTA files converted to one row per sequence where safe.
- `text/`: SQL, TXT and other text files preserved line-by-line.
- `existing_parquet/` or `inherited_parquet/`: inherited Parquet files copied forward after validation.

### DuckDB views

`derived/duckdb/e3_protac_resource.duckdb` contains views over the Parquet files. These views make the data queryable by Shiny without copying whole tables into R.

### QC and provenance

`derived/qc/` contains manifests and catalogs. These are as important as the data tables because they show what was used, skipped, copied, converted or failed.

## Next biological views

The next stage should create curated DuckDB views rather than one giant Parquet file.

Recommended views:

- `protein_records`
- `protein_sequences`
- `source_file_manifest`
- `literature_evidence`
- `go_term_evidence`
- `ligandability_pocket_scores`
- `ligandability_pocket_details`
- `candidate_e3_summary`
- `sqlite_regression_query_results`

Later Orthofinder layer:

- `orthogroup_members`
- `hog_members`
- `orthogroup_species_counts`
- `hog_species_counts`
- `orthogroup_sequence_export`

## Why not one big Parquet file?

One giant Parquet file would make the early app look simpler, but it would make future updates painful. Protein records, sequences, ligandability, GO terms, literature evidence, expression, and Orthofinder/HOG data change at different times and come from different sources. Keeping them separate means one layer can be rebuilt without damaging the others.

DuckDB views are the right place to join layers for Shiny.
