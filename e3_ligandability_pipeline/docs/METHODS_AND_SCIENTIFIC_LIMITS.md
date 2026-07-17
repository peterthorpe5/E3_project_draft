# Methods and scientific limits

## AlphaFold record selection

For an accession queried through AlphaFold DB, the workflow prefers a record
whose CIF filename follows the canonical monomer form
`AF-<accession>-F1-model_v<version>.cif`. Exact accession matches are preferred
and the highest recoverable model version is selected. The selection rule and
candidate counts are written to metadata.

This explicit rule matters because AlphaFold DB can return more than one
prediction context. It prevents an arbitrary first API record from being used
silently.

## Download and reuse

HTTP downloads use one retry-enabled session, finite timeouts and status
checking. Files are written to temporary siblings, validated and renamed only
after validation succeeds. Existing files are reused only when they pass the
same content validators.

The asset manifest records path, size, SHA-256 digest, URL/source and whether
the file was downloaded, copied or reused.

## Model pLDDT

The AlphaFold mmCIF stores pLDDT in `_atom_site.B_iso_or_equiv`. Atom rows are
collapsed to residues. Carbon-alpha pLDDT is used when present; otherwise the
median over residue atoms is used. The within-residue atom-value range is
retained to expose unexpected variation.

Model summaries include residue count, mean/median/minimum/maximum pLDDT,
counts and fractions at 70 and 90, and the maximum atom-level variation within
a residue.

The primary eligibility field is
`fraction_residues_ge_70 >= minimum_fraction_residues_ge_70`, whose default is
0.50. This is a screening rule, not proof that the whole model or a particular
binding site is reliable.

## FPocket and P2Rank

The workflow invokes P2Rank's `fpocket-rescore` route with an explicit
FPocket executable. The default P2Rank model is `rescore_2024`, retained as an
explicit experimental method choice for predicted structures.

Every command is represented as an argument list rather than shell-expanded
text. The command runs in an accession-specific staging directory. Stdout,
stderr, elapsed time, return code, executable paths and model choice are
retained. The final output directory is replaced only after successful command
completion and detection of both an FPocket info file and P2Rank predictions
CSV.

A zero command exit is necessary but not sufficient for publication.

## Pocket residue mapping

FPocket pocket atom mmCIF files are parsed into unique residue identifiers.
Model residues are indexed by:

- label chain and `label_seq_id`; and
- author chain, `auth_seq_id` and insertion code.

Label numbering is preferred. Author numbering is a checked fallback. If both
schemes identify different model residues, the mapping is recorded as
ambiguous. No residue is silently dropped.

For each pocket, the workflow records:

- predicted residue count;
- mapped residue count;
- ambiguous residue count;
- unmapped residue count;
- mapping fraction;
- exact ambiguous/unmapped identifiers;
- mapped pLDDT summaries;
- mapped-residue pLDDT fractions;
- conservative pLDDT fractions using all predicted residues as denominator.

A pocket passes the mapping rule only when the mapping fraction reaches the
configured threshold and no ambiguous residues remain. The default threshold
is 0.95.

## Output validation

The release validation contract checks:

- accession uniqueness;
- successful accessions have model-quality records;
- threshold flags agree with numeric model quality;
- pocket mapping totals reconcile;
- mapping row counts agree with pocket summaries;
- mapping identifiers are not duplicated.

A run can be configured to continue after one accession fails so that all
failures are reported. The default still marks the complete run unsuccessful
when any accession fails.

## Scientific limits

The workflow does not establish:

- E3 ligase biochemical function;
- membership of a phylogenetic orthogroup;
- substrate specificity;
- ligand binding;
- pocket druggability in vivo;
- conservation of cavity shape or chemistry across a family;
- PROTAC recruitment or degradation performance.

Milestone 2 still requires curated family alignments, residue correspondence,
cavity chemical-group conservation, shape comparison, known ligand evidence
and expert structural/chemical review.
