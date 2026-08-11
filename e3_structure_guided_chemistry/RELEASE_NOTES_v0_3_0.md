# E3 structure-guided chemistry v0.3.0

Version 0.3.0 turns the top-200 refinement into a staged full-universe
Milestone 2 campaign while making every decision easier to audit and explain.

## Full-universe campaign

- adds an immutable configuration generator for a new upstream structural run;
- expands Stage 09 structure/pocket generation and Stage 09b three-dimensional
  alignment from the previous top 200 to all 1,972 ranked Stage 08 groups;
- adds one restart-safe Dundee launcher that submits upstream work first and
  chemistry only after the final upstream completion manifest exists;
- preserves every group without eligible structural evidence as an explicit
  exclusion rather than treating it as a negative chemistry result; and
- retains an optional rank cap for deliberately bounded sensitivity runs.

## Pocket selection and scientific gates

- treats checksum-valid structure availability, mapped residues, mapping
  fraction and pocket pLDDT as eligibility floors;
- selects the most druggable eligible pocket using deterministic tie-breakers;
- adds configured FPocket druggability and mapped-residue-count gates to the
  chemistry hand-off; and
- adds a stricter high-confidence review tier without changing the meaning of
  the configured hand-off.

## Evidence and interpretation

- joins Stage 08 ranking, Stage 09 pocket and conservation, chemistry, optional
  Stage 09b alignment and optional Stage 10 integrated evidence into one
  collision-safe, prefixed TSV/Parquet table;
- publishes a field dictionary for the integrated evidence;
- publishes pocket-selection and candidate-universe audits plus the full
  ranked-member-pocket evidence table;
- expands threshold sensitivity to a multidimensional grid and adds a
  one-threshold-at-a-time analysis for all seven gates; and
- expands the HTML report with plain-language limitations and review-tier
  meanings.

## Performance and validation

- computes pairwise uniqueness once per unordered pair, reducing unnecessary
  repeated work for larger panels;
- retains immutable configuration, checksums, Git provenance, TSV/Parquet
  scientific outputs and fail-closed validation; and
- passes 91 tests with 95.68% branch-aware coverage, PEP 8, Google-style
  docstring and shell-syntax quality gates.

The method remains a protein-pocket-derived pharmacophore hypothesis. It does
not establish ligand binding, affinity, selectivity, E3 catalytic activity or
PROTAC efficacy. FMOPhore, FrAncestor and AlphaFold3 remain explicitly
`NOT_RUN`.
