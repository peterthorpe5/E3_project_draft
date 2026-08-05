# e3_end_to_end_workflow v0.14.0

Version 0.14.0 corrects the Stage 08 structure-selection contract and adds an
optional open-source computational-chemistry hand-off.

## Stage 08 correction

- `structure_group_limit` is now applied to distinct primary evolutionary
  groups, rather than to DeepClust cluster rows.
- Every DeepClust contributor to a selected group receives the same
  `computational_structure_selected` flag.
- `structural_analysis_accessions_all_members` now contains members of all
  selected evolutionary groups.
- Stage QC separately reports candidate clusters, distinct evolutionary
  groups, contributing clusters, all members and selected representatives.
- The obsolete blank `structural_accession_count` QC field has been removed.

This is a scientific-output change. Re-run Stage 08 in a new versioned run;
do not overwrite an immutable v0.13.0 result.

## Optional Stage 09c

- Adds `09c_computational_chemistry` after ligandability and before resource
  integration.
- The stage is disabled and non-required by default. A disabled stage produces
  the normal `skipped_optional` manifest and does not block Stage 10.
- When enabled, the stage imports residue-derived pharmacophore, evolutionary
  stability, between-group uniqueness and optional open-fragment tables into
  the integrated DuckDB.
- The supplied component uses only open-source dependencies and refuses any
  configuration that allows commercial or restricted-licence tools.
- FMOPhore, FrAncestor and AlphaFold3 are explicitly recorded as `NOT_RUN`;
  their names are never used for results from the open alternative.

## Operational notes

- The production template declares all group-level Stage 08 authorities.
- The workflow runner may create `logs/command.log` before the chemistry
  command starts; the component accepts that runner-owned directory while
  still rejecting pre-existing scientific outputs.
