# Output schema

All analytical datasets are written as TSV and Zstandard-compressed Parquet by
default. The same Parquet datasets are materialised into
`duckdb/e3_ligandability.duckdb`; the DuckDB does not retain external-drive
view paths.

## accession_status

One row per submitted accession.

Key fields:

- `accession`
- `status`: `SUCCESS`, `MISSING_MODEL` or `FAILED`
- `stage`: final or failed stage
- `message`
- `model_path`
- row counts for pocket and command records

## alphafold_metadata

Normalised API/input metadata and model-selection provenance.

Key fields include accession, global metric, pLDDT fractions, model/asset URLs,
model version, prediction candidate counts, selection rule and published model
path.

## asset_manifest

One row per copied, downloaded or reused model asset, including path, size,
SHA-256 digest, source/URL and publication action.

## model_quality

One row per successfully parsed model.

Key fields:

- residue count;
- mean, median, minimum and maximum pLDDT;
- pLDDT category counts;
- fractions at 70 and 90;
- maximum within-residue atom pLDDT range;
- API-versus-model differences and tolerance flags;
- model screening-threshold result.

## fpocket_pockets

One row per FPocket pocket. Metric names are normalised from the FPocket info
file while the source path and pocket number are retained.

## p2rank_pockets

One row per P2Rank prediction, including the complete original row as JSON, its
source row and the inferred original FPocket pocket number.

## joined_pockets

FPocket pockets with matching P2Rank fields prefixed by `p2rank_`. Unmatched
FPocket pockets remain present with `p2rank_match_status=UNMATCHED`.

## pocket_residue_mappings

One row per predicted pocket residue. It includes both pocket identifiers and
resolved model identifiers, mapping status/method and model pLDDT. Unmapped and
ambiguous residues remain explicit rows.

## pocket_quality

One row per pocket with mapping and confidence summaries.

Important fields:

- `predicted_pocket_residue_count`
- `mapped_pocket_residue_count`
- `ambiguous_pocket_residue_count`
- `unmapped_pocket_residue_count`
- `mapping_fraction`
- `passes_mapping_threshold`
- `mapped_fraction_plddt_ge_70`
- `mapped_fraction_plddt_ge_90`
- `conservative_fraction_plddt_ge_70`
- `conservative_fraction_plddt_ge_90`
- unmapped and ambiguous residue identifier JSON

The conservative fractions are the appropriate default for filtering because
they do not reward missing residue mappings.

## external_commands

One row per external-tool command with command string, working directory,
stdout/stderr paths, elapsed time, return code, executable paths and P2Rank
model.

## validation

The formal run-level data-integrity checks. A completed command is not accepted
as a valid scientific run unless required checks pass.

## resource_metadata

A small DuckDB-only table recording resource name and package version.

## provenance/run_manifest.json

Contains input checksum, package/environment information, external-tool
versions, effective configuration, Git state, dataset row counts, validation
counts and output-file checksums.
