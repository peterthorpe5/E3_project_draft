# Data dictionary

## General conventions

- Identifiers are UTF-8 strings.
- Missing text values are represented as empty strings in source-preserving
  fields or SQL NULL where the value is genuinely unavailable after joins.
- Percent values use the range 0-100.
- Paths are absolute in provenance tables and source metadata.
- Curated tables are available in DuckDB and as Zstandard-compressed Parquet.

## `sequence_records`

One row per input protein sequence.

| Field | Type | Meaning |
|---|---|---|
| `internal_id` | string | Stable workflow identifier; normally `sample_id::original_id`. |
| `sample_id` | string | Unique proteome/sample identifier from the manifest. |
| `species` | string | Species name supplied in the sample manifest. |
| `taxon_id` | string | Taxonomic identifier supplied in the sample manifest. |
| `proteome_id` | string | Source proteome identifier. |
| `original_id` | string | First token of the original FASTA header. |
| `description` | string | Full original FASTA header without `>`. |
| `entry` | string | Parsed accession, including UniProt accessions where recognised. |
| `sequence` | string | Normalised amino-acid sequence. |
| `sequence_length` | integer | Number of amino-acid characters. |
| `sequence_md5` | string | MD5 digest of the normalised sequence for identity/QC use. |
| `source_path` | string | Absolute path of the source FASTA. |
| `source_sha256` | string | Optional SHA-256 checksum of the source FASTA. |
| `source_record_number` | integer | One-based FASTA record number within the source file. |
| `sample_metadata_json` | string | Complete sample-manifest row as sorted JSON. |

## `known_e3_seeds`

One row per unique normalised known-E3 accession.

| Field | Type | Meaning |
|---|---|---|
| `seed_id` | string | Normalised E3 seed identifier. |
| `source_value` | string | Original value in the seed table. |
| `source_column` | string | Column selected as the accession field. |
| `source_row` | integer | Source-table row number including header offset. |
| `source_path` | string | Absolute path of the seed table. |
| `seed_metadata_json` | string | Complete source row as sorted JSON. |

## `raw_deepclust_membership`

One row per raw representative-member assignment returned by DeepClust.

| Field | Type | Meaning |
|---|---|---|
| `representative_id` | string | Cluster representative internal sequence ID. |
| `member_id` | string | Raw cluster member internal sequence ID. |
| `source_row` | integer | Source DeepClust row number. |

## `realigned_membership`

One row per DIAMOND representative-member realignment.

The parser normalises both query/subject field names (`qseqid`, `sseqid`,
`qlen`, `slen`) and the centroid/member names emitted by DIAMOND 2.2.3
(`cseqid`, `mseqid`, `clen`, `mlen`).

| Field | Type | Meaning |
|---|---|---|
| `representative_id` | string | Representative sequence ID. |
| `member_id` | string | Member sequence ID. |
| `pident` | double | Exact percentage identity reported by realignment. |
| `representative_length` | integer | Representative sequence length. |
| `member_length` | integer | Member sequence length. |
| `representative_start/end` | integer | Alignment coordinates on representative. |
| `member_start/end` | integer | Alignment coordinates on member. |
| `alignment_length` | integer | Realigned amino-acid alignment length. |
| `evalue` | double | DIAMOND e-value. |
| `bitscore` | double | DIAMOND bit score. |
| `representative_coverage` | double | Alignment length / representative length x 100. |
| `member_coverage` | double | Alignment length / member length x 100. |
| `passes_identity` | Boolean | Meets the configured identity threshold. |
| `passes_representative_coverage` | Boolean | Meets representative coverage threshold. |
| `passes_member_coverage` | Boolean | Meets member coverage threshold. |
| `passes_bitscore` | Boolean | Exceeds bit-score threshold. |
| `passes_evalue` | Boolean | Is below e-value threshold. |
| `passes_all` | Boolean | Passes every strict threshold. |
| `source_row` | integer | Source realignment row number. |

## `sequence_seed_matches`

Matches source sequences to supplied seed identifiers using accession, original
identifier or internal identifier.

## `raw_cluster_sequences`

The distinct union of representative and member sequence IDs for every raw
cluster. This table explicitly prevents representatives being omitted when a
DeepClust output does not include a self-membership row.

## `e3_seeded_clusters`

One row per raw cluster containing at least one known-E3 seed sequence.

| Field | Meaning |
|---|---|
| `representative_id` | Cluster identifier. |
| `known_e3_sequence_count` | Number of seed-matching source sequences in cluster. |
| `known_e3_seed_count` | Number of distinct supplied seed IDs represented. |
| `known_e3_seed_ids` | Semicolon-separated seed IDs. |

## `e3_seeded_cluster_members`

All sequences in E3-seeded raw clusters, joined to source metadata and available
realignment statistics.

Important fields include `passes_strict_thresholds` and `is_known_e3_seed`.
Rows with missing realignment evidence remain visible and do not pass the strict
criteria by default.

## `threshold_pass_membership`

All representative-member realignments in the complete dataset for which
`passes_all` is true. This table is not restricted to E3-seeded clusters.

## `strict_e3_seeded_cluster_members`

The subset of `e3_seeded_cluster_members` that passes all strict thresholds.
The name deliberately avoids the term "confirmed E3".

## `e3_seeded_cluster_summary`

One row per E3-seeded cluster, containing seed counts, raw/strict member counts,
sample/species counts and descriptive identity/coverage statistics.

## `workflow_thresholds`

Name-value table recording the strict criteria embedded in the resource.

## QC outputs

### `qc/sample_summary.tsv`

Per-sample sequence count, residue count, source path and checksum metadata.

### `qc/resource_validation.tsv`

Pass/fail/warning findings for identifier uniqueness, cluster-to-sequence
mapping, E3-seeded cluster presence and strict-member presence.

## Provenance outputs

### `provenance/run_manifest.json`

Validated configuration, platform/software versions and checksums/sizes for key
workflow products.

### `provenance/*_command.json`

Exact argument array and working directory for each external DIAMOND stage.

## Version 0.1.12 evidence-separation tables

- `all_matched_e3_seed_sequences`: every input sequence matching a supplied
  inherited E3 seed, with cluster and strict-alignment status.
- `strict_matched_e3_seed_sequences`: matched seed sequences passing all strict
  representative-alignment thresholds.
- `non_strict_matched_e3_seed_sequences`: matched seed sequences retained even
  though they do not pass all strict representative-alignment thresholds.
- `strict_nonseed_candidate_members`: strict-pass E3-seeded cluster members not
  present in the supplied seed list. These are candidates, not confirmed E3s.
- `realignment_content_summary`: row counts, self/non-self counts, strict-pass
  count and observed minimum/maximum identity and coverage.
- `workflow_key_metrics`: compact count summary for review and comparison.
