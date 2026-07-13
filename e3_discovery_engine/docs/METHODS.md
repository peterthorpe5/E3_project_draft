# Computational methods

## Scope and scientific claim

The workflow identifies sequence clusters that contain at least one previously
identified E3 candidate. It does not assign E3-ligase function to every sequence
in those clusters. Cluster membership is treated as sequence-similarity evidence
that can be combined later with domain annotation, curated literature, Gene
Ontology evidence, structural information and experimental validation.

## Inputs

The production workflow requires two explicit input manifests.

1. A tab-delimited proteome sample manifest. Each row represents one proteome
   FASTA and includes a unique `sample_id`, `fasta_path`, species, taxon ID and
   proteome ID. Additional columns are retained as JSON metadata.
2. A delimited known-E3 seed table. The accession column is named explicitly in
   the configuration. Every source row and all accompanying metadata are
   preserved.

Input FASTA files may be plain text or gzip-compressed. Source files are opened
read-only and are never decompressed in place, renamed or deleted.

## Configuration validation

The YAML configuration is validated before execution. Validation covers required
sections, identifiers, file paths, positive resource values, identity mode,
threshold ranges, benchmark repeat count and list-valued DIAMOND options.
Relative paths are resolved against the configuration file rather than the
current working directory.

## Sequence preparation

FASTA records are streamed to avoid loading a complete proteome collection into
memory. Amino-acid sequences are normalised to upper case and checked against a
permissive protein alphabet that includes standard residues and recognised
ambiguous/rare symbols.

The recommended identifier mode is `prefix_sample`. It creates an internal
identifier by combining the sample ID and the original FASTA identifier. This
prevents accidental collisions when two proteomes use the same local gene or
protein identifier. The following information is retained for each sequence:

- internal identifier;
- sample ID;
- original FASTA identifier and full description;
- parsed accession/entry where available;
- species, taxon ID and proteome ID;
- sequence, length and MD5 checksum;
- source FASTA path and optional SHA-256 checksum;
- complete sample metadata as JSON.

The combined FASTA and sequence Parquet table are written through temporary
files and published atomically only after successful completion. Parquet output
is compressed with Zstandard and written in configurable batches.

## Known-E3 seed preparation

Known-E3 accessions are normalised, deduplicated and written to TSV and Parquet.
Blank rows are counted. Duplicate rows are counted rather than silently lost.
The original accession value, source column, source row, source path and complete
source metadata are retained.

## DIAMOND database and clustering

A DIAMOND protein database is built from the combined FASTA. The production
environment pins DIAMOND 2.2.3 and uses exact traceback identity during
DeepClust where supported. A legacy reproduction environment pins DIAMOND
2.1.23 and uses approximate identity to recreate the inherited behaviour as
closely as possible.

The default production clustering parameters are:

- identity: 50% using exact `--id`;
- mutual coverage: 50%;
- clustering e-value: 0.1;
- SEG masking enabled;
- threads and memory limit supplied by configuration.

These settings define broad cluster formation. They are intentionally separated
from the stricter post-realignment criteria used for final interrogation.

## Representative-member realignment

DIAMOND `realign` is run for the raw clusters and exports explicit tabular
fields:

- representative and member sequence identifiers;
- exact percentage identity;
- representative and member lengths;
- alignment coordinates and alignment length;
- e-value and bit score.

The parser validates the required header, identifier presence, numeric values
and positive sequence lengths. Representative and member coverage are computed
from alignment length and sequence length and capped at 100%.

## Strict post-realignment filtering

Each realigned representative-member relationship is classified independently
using the configured thresholds. The default production criteria are:

- percentage identity >= 50%;
- representative coverage >= 50%;
- member coverage >= 50%;
- bit score > 20;
- e-value < 1e-10.

Separate Boolean fields record the outcome of every criterion, plus a combined
`passes_all` field. This provides an auditable distinction between raw
DeepClust membership and strict sequence-similarity evidence.

## E3-seeded cluster identification

The complete sequence membership of each raw cluster is defined as the union of
its representative and member identifiers. Known-E3 seed matching is tested
against the sequence accession, original identifier and internal identifier.
A cluster is E3-seeded when at least one sequence in that union matches at least
one supplied known-E3 seed.

The workflow does not infer that all members are E3 ligases. It provides:

- all raw E3-seeded cluster members;
- members that pass all strict realignment thresholds;
- the known-E3 seed sequences responsible for seeding each cluster;
- summary counts by cluster, sample and species.

## DuckDB and Parquet resource

Source Parquet tables are materialised into a DuckDB resource. Curated tables
are then constructed for seed matching, raw membership, strict membership and
cluster-level summaries. Each interrogation table is also exported as a
standalone compressed Parquet file.

The resource is built at a temporary path and atomically moved into place only
after validation. Validation checks include unique internal sequence IDs,
complete sequence mapping for cluster identifiers, the presence of E3-seeded
clusters and the number of strict members.

## FASTA exports

Three FASTA products are written:

1. E3-seeded cluster representatives;
2. all sequences in E3-seeded clusters;
3. sequences in E3-seeded clusters that pass every strict threshold.

Headers retain the internal sequence ID and selected source metadata. These
outputs remain candidate sets, not functional annotations.

## Benchmarking

Every major Snakemake rule uses the benchmark directive. Formal configurations
use three repeated measurements. Benchmark aggregation records rule name,
repeat number, wall-clock time, CPU time, peak memory and I/O measurements where
reported by Snakemake. A summary table and runtime figure are generated.

For formal scaling work, rule-level measurements are accompanied by dataset
metadata including proteome count, sequence count, total amino-acid residues,
input size, hardware, thread count and scheduler context.

## Provenance and logging

Each stage writes a persistent log. External DIAMOND commands are represented as
argument arrays and stored in JSON together with the working directory. The run
manifest records the validated configuration, software versions, platform,
file sizes and SHA-256 checksums.

## Software quality controls

The repository includes unit tests mapped to every Python function, integration
tests for DuckDB/Parquet construction, a synthetic end-to-end test and an
opt-in end-to-end test using a real DIAMOND executable. PEP8 checks, compilation,
coverage measurement and repository-contract checks are run by `run_tests.sh`.
