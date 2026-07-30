# Stage 09 duplicate-pocket aggregation hotfix

Date: 30 July 2026  
Affected run: `grant_aligned_structural_sensitivity_top100_v0_11_0_20260729`

## Failure

Stage 09 published 3,330 checksum-validated ligandability assets and then stopped
during aggregation with:

```text
ERROR: Duplicate selected pocket key: A0A8I6YKD5/5
```

The campaign contained 1,110 accession-level shard tasks and 1,096 unique
accessions. Fourteen proteins were therefore used in more than one selected
evolutionary-group context. This reuse is valid, but the Stage 09 coordinate
mapper incorrectly required an accession/pocket combination to be globally
unique.

Repeated accession shards also placed identical pocket evidence into the
aggregate tables. Without canonicalisation, duplicate copies of one physical
pocket could consume more than one of the five retained sensitivity ranks.

## Repair

- Preserve every distinct evolutionary-group context for a reused protein.
- Replicate its validated residue coordinates into each relevant group context.
- Canonicalise identical accession/pocket shard evidence before top-k ranking.
- Require duplicate joined-pocket and pocket-quality evidence to agree exactly.
- Stop with an explicit error if repeated scientific evidence conflicts.
- Reject exact duplicate group/accession/pocket contexts.
- Keep the existing shard task ordering unchanged so the completed campaign can
  resume without invalidating or rerunning its checksum-controlled shard cache.

The strict rank-one result and the top-five sensitivity result remain separate.
This repair changes aggregation semantics only; it does not alter the scoring
thresholds or accept an alternative pocket without agreement from both structural
aligners.

## Validation

- 215 end-to-end workflow tests passed.
- Branch-aware workflow coverage: 90.43%.
- Complete isolated synthetic DAG passed.
- Final no-op resume passed.
- 13 repository-level tests passed.
- PEP 8, 100-character line limit and Google-style docstring checks passed.
- Direct regression coverage includes the observed `A0A8I6YKD5/5` failure shape,
  repeated group contexts, unique top-k ranks, exact duplicate rejection,
  conflicting joined-pocket evidence, conflicting quality evidence and malformed
  pocket identifiers.

## Resume policy

Resume the existing run in place with the unchanged configuration and `--resume`.
Do not delete the run root, force Stage 09 or change the task table. Completed
ligandability shards remain the restart authority and will be reused.
