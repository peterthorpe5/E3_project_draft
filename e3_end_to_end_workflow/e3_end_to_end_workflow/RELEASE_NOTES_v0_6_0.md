# E3 end-to-end workflow v0.6.0

## Scientific workflow completion

- Adds a grant-aligned reviewed-reuse configuration for the existing 7,255-cluster candidate
  authority, 60-proteome OrthoFinder 2.5.5 result, Expression Atlas Parquet and retained
  AlphaFold/FPocket/P2Rank tables.
- Preserves OrthoFinder exactly at version 2.5.5 and validates the inherited result archive before
  downstream use.
- Implements native stages 06 through 11: domain annotations, full-group expression mapping,
  computational pre-structure prioritisation, reused-pocket selection, aligned pocket-region
  conservation, integrated DuckDB/TSV/Parquet/HTML and Python/Shiny hand-off.
- Treats the computational shortlist as a transparent recommendation for human review rather than
  claiming a signed biological approval.

## Domain, expression and missing evidence

- Downloads bounded InterPro protein annotations and Pfam member-database hits for selected group
  members; no local InterProScan, Pfam HMM library or HMMER run is required.
- Stores terminal annotation responses in an atomic persistent cache and supports checksum-bound
  offline cache manifests.
- Distinguishes `SUPPORTED`, `ANNOTATED_NO_CATALOGUED_E3_DOMAIN` and
  `ANNOTATION_UNAVAILABLE` domain evidence.
- Keeps species without a compatible domain or Expression Atlas resource explicitly unavailable;
  missing evidence is excluded from biological-negative denominators and retained in completeness
  fields.
- Maps expression to every selected target-species orthogroup member through audited identifier
  aliases rather than only to the seed accession.

## Reuse and future scaling

- Adds explicit per-stage evidence modes: validate, prepare, reuse, download, derive, generate,
  synthetic and disabled.
- Makes the target and mandatory species panels configuration-driven.
- Recursively inventories nested Hive-partitioned Expression Atlas Parquet resources.
- Supplies a separate future fresh-production template for a larger arbitrary proteome/species
  manifest, with configurable adapter commands and stage resources up to 32 CPUs and 180 GB.
- Adds MAFFT to the shared environment for reproducible pocket-bearing region alignments.

## Validation

- 107 Python tests pass.
- Enforced branch-aware package coverage is 90% after the scientific codebase expansion.
- PEP 8, PEP 257, shell syntax and Snakemake lint pass.
- The concurrent 15-job synthetic DAG passes, including 12 stage reports, aggregate benchmarks,
  the consolidated HTML report, controlled reruns and a final no-op dry run.
- A miniature real scientific integration test passes from domain/expression inputs through final
  DuckDB, HTML and application hand-off.
