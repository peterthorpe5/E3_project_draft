# E3 structural-alignment and pocket-review package v0.3.1

Date: 30 July 2026

## Additive sequence export

The ranked pocket-review report now publishes two explicit sequence resources:

- `sequences/prioritised_group_sequences.fasta`: a combined, ungapped protein
  FASTA for every sequence in each reviewed group alignment;
- `tables/prioritised_group_sequences.tsv`: a tab-separated audit table
  containing rank, evolutionary-group and lead-cluster identifiers, original
  accession/name, species when available, reference and ranked-pocket-evidence
  flags, sequence length, ungapped sequence, aligned sequence and the source
  alignment checksum.

The export uses the authoritative Stage 09 `aligned.fasta` files and retains
alignment members even when no ranked pocket or structural model is available.
It does not alter group ranking, pocket selection, structural comparison or any
candidate decision.

## Expanded production HTML

The top-level ranked index now exposes the evidence needed for rapid manual
triage rather than requiring reviewers to open several separate tables:

- pre-structure rank and pass state;
- target- and structural-species coverage;
- minimum member druggability and integrated score;
- strict and top-k 3D position and conservation conclusions;
- sequence, pocket-evidence and model coverage;
- formal final-pass counts and direct audit-file downloads.

Each group page now includes the configured gate components, decision and
missing-evidence reasons, a complete sequence/model inventory, expanded
residue-level structural metrics and direct links to every downloadable audit
resource.

## Production input compatibility

Automatic input discovery now prefers the stable
`top_computational_review_shortlist.parquet` authority and accepts normal
production directories containing both Parquet and TSV copies. This resolves a
v0.3.0 discovery defect that could reject a valid completed workflow because
both formats were present.

## Validation

Regression tests cover:

- combined TSV and FASTA publication;
- deterministic identifiers and output order;
- removal of alignment gaps from exported protein sequences;
- retention and explicit flagging of alignment members without pocket evidence;
- rejection of all-gap sequences, empty exports and invalid FASTA line widths;
- deterministic Parquet preference when production TSV/Parquet pairs coexist;
- expanded summary, group-level evidence and download links in the HTML;
- checksum-bound resume behaviour for the new outputs.
