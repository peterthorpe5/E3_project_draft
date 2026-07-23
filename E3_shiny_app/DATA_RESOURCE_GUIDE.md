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

## Integrated biological relations

The end-to-end workflow now materialises curated DuckDB relations for candidate
evidence, OrthoFinder membership, candidate-relevant group-member sequences,
domain evidence, expression mapping, prioritisation, ligandability, pocket
conservation, FASTA coordinates and optional 3D alignment.

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

OrthoFinder relations include:

- `orthogroup_members`
- hierarchical-group members
- `orthogroup_species_counts`
- hierarchical-group species counts
- `orthogroup_sequence_export`

## Candidate master Parquet and detailed relations

Stage 10 now also writes `e3_candidate_master_results.parquet`, one wide row per
candidate group. This is the portable one-file summary requested for project
reporting and it supports every summary-level app section.

It does not place unlike row granularities into one flat table. Multiple protein
members, sequences, pockets, domain hits and residue matches remain separate
relations in DuckDB. This preserves every result without duplicating candidate
rows or hiding provenance. DuckDB and duckplyr remain the production query
layer; the master Parquet is the convenient summary hand-off.
