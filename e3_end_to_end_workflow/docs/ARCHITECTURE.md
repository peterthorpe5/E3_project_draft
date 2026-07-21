# Architecture and release contract

## Purpose

The master package makes cross-package execution repeatable while keeping each scientific package
independent. A component may be upgraded without renaming old run outputs; the run configuration,
component logs and checksums identify exactly which implementation produced each release.

## Run directory

```text
<output_root>/<run_name>/
├── 00_inputs/
├── 01_prepared_proteomes/
├── 02_discovery/
├── 03_candidate_evidence/
├── 04_orthofinder/
├── 05_orthology/
├── 06_domains/
├── 07_expression/
├── 08_shortlist_gate/
├── 09_ligandability/
├── 10_integrated_resource/
├── 11_app_ready/
├── failed/
├── superseded/
└── workflow_logs/
```

Every stage directory contains `stage_manifest.json` and `logs/stage.log`. External tools receive
the temporary stage directory in both the `{stage_dir}` argv placeholder and `E3_STAGE_DIR`.
Publication uses an atomic rename on the output filesystem.

## Input manifest invariants

- `species_id` is unique and stable across releases.
- Every included FASTA is a regular file with a verified SHA-256.
- Seed accessions are unique and retain evidence type, source, E3 category, GO flags, organism,
  taxon, sequence checksum and inherited source-row provenance.
- The seed evidence authority is a deterministic gzip-compressed TSV derived from the full
  discovery-engine seed table; the sequence-bearing source table remains outside Git.
- Ligandability accessions require a human decision, reviewer, UTC time and rationale.
- A shortlist without at least one explicit `approve` decision is invalid.

## Production safety

`run.mode: production` changes validation behaviour. Every scientific stage other than controlled
input validation, the human shortlist gate and application handoff must provide a command as a YAML
argv list. Required stages cannot be disabled. A command's exit status and every declared non-empty
output are checked before publication. Before a downstream stage starts, every file in the upstream
manifest is checked again for size and SHA-256.

The production template deliberately contains `CHANGE_ME` commands because package-specific
adapters still need to be finalised against the exact cluster installations and run-specific paths.
This is preferable to silently embedding legacy paths or pretending a placeholder ran an analysis.

## Extension policy

A new species is a new row and FASTA checksum in `proteomes.tsv`, followed by a new immutable run
name. New evidence types should become new tables/views rather than columns injected into unrelated
authorities. DeepClust and OrthoFinder labels are always qualified by their source run identifiers.
