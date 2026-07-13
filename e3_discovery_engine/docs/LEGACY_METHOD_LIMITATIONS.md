# Limitations and implementation defects in the inherited workflow

## Scope

The inherited workflow is a useful research prototype and appears to support the
broad claim that DIAMOND DeepClust can generate clusters containing known E3
candidates at useful scale. This audit separates:

- confirmed implementation defects;
- methodological limitations;
- undocumented assumptions;
- missing validation/evidence.

These findings do not imply that all inherited results are wrong. They explain
why the code should not be reused unchanged for formal Milestone 1 delivery.

## Confirmed implementation defects

### Append-mode concatenation

The inherited workflow used `cat ... >> combined.fasta`. Re-running after a
partial or complete output existed could append every proteome again and silently
duplicate the database.

**Correction:** the production workflow writes a new temporary combined FASTA
and atomically publishes it after validation.

### Destructive decompression

The inherited workflow used `gunzip` on source inputs, which normally removes
the compressed source file.

**Correction:** the production parser reads `.gz` directly and never modifies
source data.

### Representative handling was implicit

The inherited E3-cluster selection checked known E3 accessions against the
member identifier only. The final cluster-sequence export also relied on member
identifiers despite being described as representatives plus members.

**Risk:** a representative could be omitted if DIAMOND did not emit it as a
self-member.

**Correction:** cluster sequence membership is the explicit union of
representative and member identifiers, and seed matching is performed across the
complete union.

### Rerun-unsafe database creation

Inherited DuckDB creation did not consistently replace or atomically publish
all tables/database outputs.

**Correction:** the production resource is built at a temporary path, validated
and then moved into place.

## Methodological limitations

### E3-seeded clusters are not E3 annotations

The inherited narrative could be read as treating all sequences in a cluster as
E3 ligases. The workflow actually identifies clusters containing at least one
known E3 candidate.

**Correction:** production table names, documentation and reporting language
state this explicitly.

### Broad clustering thresholds

The inherited command used approximate identity 50%, mutual coverage 50% and an
e-value of 0.1. These settings can be useful for discovery but are relaxed for
individual functional inference.

**Correction:** broad raw clustering is retained as a discovery layer, followed
by exact representative-member realignment and a separate strict filter.

### Approximate identity was not exact percentage identity

The inherited version used DIAMOND `--approx-id`, an estimate related to bit
score rather than an exact count of aligned identical residues.

**Correction:** production mode requires a DIAMOND version supporting exact
`--id` for clustering and always records exact `pident` from realignment.

### Milestone thresholds were not applied as a final filter

The inherited workflow did not explicitly enforce the complete requested set of
identity, bidirectional coverage, bit-score and e-value criteria after
realignment.

**Correction:** every criterion and the combined result are stored per
representative-member relationship.

### Similarity may be domain-local

A sequence can cluster with an E3 because of a shared domain while lacking the
complete architecture or residues required for E3 function.

**Correction:** results are candidates for downstream domain, orthology,
structure, expression and experimental analyses.

## Scalability and data-engineering limitations

### Whole-dataset in-memory sequence conversion

The inherited converter stored all sequences, including full amino-acid strings,
in a Python dictionary and pandas DataFrame before writing.

**Risk:** excessive memory use or failure for tens of millions of proteins.

**Correction:** the production workflow streams FASTA and writes compressed
Parquet in configurable batches.

### Insufficient identifier controls

The inherited workflow assumed sequence identifiers were globally unique across
proteomes.

**Risk:** collisions could merge unrelated proteins or break cluster-to-sequence
joins.

**Correction:** internal IDs are normally prefixed by sample ID; preserve mode
fails on duplicates.

### Weak sample/configuration generation

The inherited generator could scan unrelated/hidden files, produce incomplete
sample names and relied on fixed paths.

**Correction:** an explicit TSV manifest is validated, retains metadata and
rejects duplicate IDs/paths and macOS sidecar files.

### Uncompressed or poorly documented outputs

Large intermediate tables were not consistently compressed or accompanied by
stable schemas.

**Correction:** production outputs use named Arrow schemas and Zstandard
Parquet, with a field-level data dictionary.

## Reproducibility and software-quality limitations

### Hard-coded environments and resources

Paths such as `/home/ubuntu/kitchen/...`, fixed thread counts and fixed memory
values were embedded in the workflow.

**Correction:** environment, threads, memory and output paths are configuration
values resolved independently of the working directory.

### No inherited unit or integration tests

The recovered audit found no Python unit tests.

**Correction:** every Python function is mapped to tests; integration, synthetic
end-to-end and optional real-DIAMOND end-to-end tests are included.

### Limited logging and provenance

The inherited workflow did not provide structured stage logs, exact command
records, checksums or a complete run manifest.

**Correction:** production runs retain console/file logs, command JSON,
software versions, configuration and file checksums.

### Limited output validation

The inherited code did not comprehensively verify non-empty outputs, identifier
uniqueness or complete cluster-to-sequence mapping.

**Correction:** Python validation and Snakemake `ensure(non_empty=True)` checks
prevent silent release of incomplete outputs.

## Benchmark limitations

The recovered timings make the headline scaling claim plausible, but the
historical benchmark was not sufficient as a formal modern benchmark because it
lacked some combination of:

- repeat runs;
- complete hardware and scheduler context;
- total sequence and residue counts;
- explicit cache state;
- consolidated rule-level measurements;
- observed peak memory reporting;
- a documented explanation for large differences between early and later test
  series;
- clear separation of measured runtime from extrapolation.

**Correction:** formal production benchmarking uses repeated Snakemake benchmark
records, dataset manifests, hardware/software metadata and separate reporting of
observed versus extrapolated values.

## Legacy result interpretation

The inherited 6,707-cluster result should be retained as a historical reference.
A production rerun may differ because of source-file recovery, duplicate handling,
identifier normalisation, DIAMOND version, exact identity and strict filtering.
The appropriate validation is a documented legacy-reproduction run followed by
a separately labelled production analysis.
