# Test and release status: E3 pocket review v0.3.1

Date: 30 July 2026

## Outcome

Release gate: **PASS**

The additive prioritised-group sequence export passed the complete structural
alignment and pocket-review package test suite.

## Automated validation

- 60 tests passed.
- Branch-aware total coverage: 93%.
- Configured minimum coverage: 90%.
- PEP 8 checks passed with a 100-character line limit.
- Google-style docstring checks passed.
- Shell syntax checks passed for all user-facing entry points and Slurm
  wrappers.

## Sequence-export regression coverage

The tests confirm:

- deterministic combined FASTA and TSV publication;
- exact evolutionary-group, lead-cluster, accession/name and species metadata;
- correct removal of alignment gaps from exported protein sequences;
- retention of alignment members without pocket or model evidence;
- explicit ranked-pocket evidence flags;
- rejection of all-gap sequences and invalid or empty FASTA exports;
- inclusion of both new files in checksum-bound resume validation.

## HTML and production-input regression coverage

The tests also confirm:

- expanded index-level scientific summaries and evidence columns;
- expanded group-level decision, sequence/model and structural evidence;
- working relative links to all report audit files;
- separation of strict rank-one and top-k sensitivity evidence;
- safe HTML escaping and fully offline browser data;
- deterministic preference for Parquet when a production run contains both
  Parquet and TSV copies of the same authority.

## Scientific scope

Version 0.3.1 changes reporting only. It does not recalculate or alter:

- evolutionary-group ranking;
- shortlist membership;
- pocket prediction or selection;
- rank-one or top-k structural comparison;
- final candidate gates or manual-review decisions.
