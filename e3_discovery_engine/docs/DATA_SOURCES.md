# Data sources and provenance requirements

## Purpose

This file defines the metadata required before a dataset is accepted into a
formal Milestone 1 run. It should be completed for every production sample
manifest rather than relying on folder names or institutional knowledge.

## Proteome source metadata

Record, where available:

- species scientific name;
- NCBI taxonomy ID;
- strain, cultivar, accession or haplotype;
- proteome identifier;
- source repository and release/version;
- original download URL or accession;
- download date;
- licence or access restriction;
- gene-model version;
- whether the proteome is primary/canonical, representative or complete;
- whether alternative isoforms are included;
- compressed and uncompressed file names;
- SHA-256 checksum;
- sequence count and total residues;
- curator notes and inclusion rationale.

## Known-E3 seed metadata

The seed table should retain:

- accession supplied to the workflow;
- preferred gene/protein name;
- organism and taxon ID;
- source publication/database;
- evidence category;
- E3 family/category if known;
- keyword/GO/domain evidence;
- date and method of curation;
- any exclusion or uncertainty flag.

The workflow preserves all additional columns as JSON, but the table should
still use explicit, documented columns where possible.

## Inherited data

Inherited files are evidence and provenance sources, not automatically trusted
production inputs. Keep them read-only under `legacy_reference` or a separate
raw-data area. Record checksums before transformation.

The inherited report and code suggest that the previous workflow used:

- a curated list of approximately 43,000 E3 candidate accessions;
- selected plant/eukaryotic proteomes and a 1KP+ sequence collection;
- DIAMOND DeepClust with approximate identity 50%, mutual coverage 50% and
  clustering e-value 0.1;
- an E3-seed lookup to retain clusters containing known candidates.

Every production input must be reidentified from manifests and checksums rather
than inferred from these descriptions alone.

## Sample manifest template

Required columns:

```text
sample_id	fasta_path	species	taxon_id	proteome_id
```

Recommended additional columns:

```text
strain_or_cultivar	source_database	source_release	download_date
licence	gene_model_version	isoform_policy	curator_notes
```

## Versioning policy

- Never replace a formal input file in place.
- Create a new sample manifest for each dataset release.
- Use a new output root for every formal run.
- Store configuration, manifests and checksums with the results.
- Distinguish legacy reproduction from production analysis in directory names.
