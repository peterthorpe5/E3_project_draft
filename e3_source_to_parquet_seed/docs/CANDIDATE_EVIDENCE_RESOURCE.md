# E3 cluster candidate evidence resource

## Purpose

The candidate evidence layer converts the completed E3 Discovery Engine result
into one compact row per E3-seeded sequence cluster. It is the first integration
resource used to finish the conservation and candidate-prioritisation component
of ARIA Milestone 1 and to prepare a defensible shortlist for Milestone 2.

The source E3 Discovery Engine DuckDB is attached read-only. The build does not
change the completed production analysis and does not duplicate its 25.8 million
sequence-level records in the output database.

## Scientific interpretation

An E3-seeded cluster contains at least one sequence matching an inherited E3
candidate accession. A strict member passes the configured representative-member
identity, coverage, bit-score and e-value criteria. This does not prove that every member is an E3 ligase. Strict sequence
evidence is stronger similarity evidence, not functional confirmation.

The first evidence resource therefore supports candidate discovery and ranking.
Domain architecture, curated family annotation, expression, orthology,
ligandability and experimental evidence must be added before final biological
prioritisation.

## Inputs

The build requires the completed production DuckDB, expected at:

```text
<full-run-root>/duckdb/e3_discovery_resource.duckdb
```

The production schema used to develop this release was inspected on 16 July
2026. A schema fixture is retained in
`tests/fixtures/production_duckdb_columns_20260716.tsv`.

## Outputs

```text
<output-root>/
├── candidate_evidence/
│   ├── e3_cluster_candidate_evidence.tsv
│   └── e3_cluster_candidate_evidence.parquet
├── duckdb/
│   └── e3_candidate_evidence.duckdb
├── logs/
│   ├── e3_build_candidate_evidence.log
│   └── run_e3_candidate_evidence_wrapper.log
├── provenance/
│   └── e3_cluster_candidate_evidence_manifest.json
└── qc/
    └── e3_cluster_candidate_evidence_validation.tsv
```

The DuckDB contains:

- `e3_cluster_candidate_evidence`;
- `e3_cluster_candidate_evidence_validation`;
- `e3_cluster_candidate_evidence_build_metadata`.

## Evidence represented in each row

Each row includes:

- representative sequence identifiers and source metadata;
- inherited seed sequence and seed-identifier counts;
- strict and non-strict seed counts;
- inherited seed categories, review status, GO flags, organisms and protein names;
- raw and strict cluster sizes;
- strict non-seed candidate counts and fractions;
- raw and strict biological sample and species-label breadth;
- separate 1KP and named-proteome breadth;
- named cereal, Solanaceae, legume and Brassicaceae coverage;
- representative-member identity and member-coverage summaries.

The 1KP species values are inherited labels and are not yet externally
normalised taxonomy identifiers.

## Validation contract

A formal build fails before publication unless all checks pass. The checks cover:

- one row per E3-seeded cluster;
- total raw and strict member reconciliation;
- matched, strict and non-strict seed reconciliation;
- strict non-seed candidate reconciliation;
- unique, non-null representatives with sequence metadata;
- per-cluster strict member decomposition;
- per-cluster seed decomposition;
- recalculated breadth matching the production cluster summary;
- strict evidence remaining a subset of raw evidence;
- direct seed counts and identifiers matching the production summary;
- complete seed-metadata joins;
- TSV and Parquet row counts and column order matching the DuckDB table.

Outputs are written to unique temporary paths and published with atomic file
replacement only after validation. If a build fails, previous formal outputs
remain untouched.

## Cluster command

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft/e3_source_to_parquet_seed

DISCOVERY_DUCKDB="/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results/full_onekp_plus_v0_1_14_20260715_100551/duckdb/e3_discovery_resource.duckdb"

OUTPUT_DIR="/home/pthorpe001/data/2026_E3_protac/E3_PROTAC_curated_working_copy_20260702_105742/derived_v0_4_0"

./run_e3_candidate_evidence.sh \
  "${DISCOVERY_DUCKDB}" \
  "${OUTPUT_DIR}" \
  --conda-env e3_discovery
```

Use `--overwrite` only for a deliberate controlled rebuild. The source DuckDB
SHA-256 is calculated by default and recorded in the manifest. It can be skipped
with `--skip-source-sha256`, but that omission is also recorded.

## Immediate downstream work

After this layer is built, the next additions should be separate, traceable
modules for:

1. E3 family/domain confirmation and contamination flags;
2. identifier mapping to the Expression Atlas resource;
3. expression breadth and relevant tissue/condition summaries;
4. inherited AlphaFold, FPocket and P2Rank evidence after method audit;
5. transparent candidate ranking with inclusion and exclusion reasons.
