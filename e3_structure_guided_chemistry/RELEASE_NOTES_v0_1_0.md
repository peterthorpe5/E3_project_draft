# e3_structure_guided_chemistry v0.1.0

Initial open-source structure-guided chemistry release for the ARIA plant E3
workflow.

## Scientific scope

- selects the top ten distinct Stage 08 evolutionary candidate groups by
  default;
- consumes checksum-bound Stage 09 structures, selected pockets, mapped pocket
  residues and conservation summaries;
- extracts transparent residue-derived three-dimensional pharmacophore points;
- combines feature chemistry and rotation-invariant feature-pair distances for
  selected-panel uniqueness assessment;
- gates hand-off on configured evolutionary conservation thresholds; and
- optionally applies RDKit rule-of-three descriptors and two-dimensional
  feature-compatibility ranking to a user-supplied open fragment table.

## Method and licence boundaries

- no commercial or separately negotiated software entitlement is required;
- the configuration rejects restricted tools and non-approved SPDX labels;
- every run publishes `COMPONENT_LICENCES.tsv`, `METHOD_STATUS.tsv` and
  `MILESTONE_COVERAGE.tsv`;
- AlphaFold3, FMOPhore and FrAncestor are explicitly `NOT_RUN`; and
- results are not labelled as FMO energies, docking, affinity, binding,
  selectivity or PROTAC efficacy.

## Workflow integration

End-to-end Stage `09c_computational_chemistry` is disabled and non-required by
default. When disabled, its normal `skipped_optional` manifest satisfies the
Stage 10 dependency without requiring this component environment.
