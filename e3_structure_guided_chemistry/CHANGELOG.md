# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.3.1

<!-- source: RELEASE_NOTES_v0_3_1.md; sha256: 8760a74bab14ee3c5c66d47ab3fb4c93275395275acbffd7a2894f5bdd39415c -->

- Adds `run-workflow-campaign`, which creates the complete computational
  candidate panel directly from current Stage 08 and Stage 09 authorities.
- Stores the generated panel, exclusions, selection audit and checksums beneath
  the chemistry provenance directory.
- Accepts the current Stage 09b structural summary and ranked member-pocket
  evidence without requiring a manually maintained panel.
- Retains all v0.3.0 chemistry gates, sensitivity tables and lossless integrated
  evidence.

## v0.3.0

<!-- source: RELEASE_NOTES_v0_3_0.md; sha256: f26cefbff3b15c48e48b6e078a6cf30826180752199c750fd4ac056b77355915 -->

Version 0.3.0 turns the top-200 refinement into a staged full-universe
Milestone 2 campaign while making every decision easier to audit and explain.

### Full-universe campaign

- adds an immutable configuration generator for a new upstream structural run;
- expands Stage 09 structure/pocket generation and Stage 09b three-dimensional
  alignment from the previous top 200 to all 1,972 ranked Stage 08 groups;
- adds one restart-safe Dundee launcher that submits upstream work first and
  chemistry only after the final upstream completion manifest exists;
- preserves every group without eligible structural evidence as an explicit
  exclusion rather than treating it as a negative chemistry result; and
- retains an optional rank cap for deliberately bounded sensitivity runs.

### Pocket selection and scientific gates

- treats checksum-valid structure availability, mapped residues, mapping
  fraction and pocket pLDDT as eligibility floors;
- selects the most druggable eligible pocket using deterministic tie-breakers;
- adds configured FPocket druggability and mapped-residue-count gates to the
  chemistry hand-off; and
- adds a stricter high-confidence review tier without changing the meaning of
  the configured hand-off.

### Evidence and interpretation

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

### Performance and validation

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

## v0.2.1

<!-- source: RELEASE_NOTES_v0_2_1.md; sha256: 5d9330c37d97564628e47290acb80d73dfa19cc5645e5694f2e6266a2c6bf1ca -->

Patch release for expanded-panel preparation when Stage 08 evolutionary groups
overlap on the same candidate accession and pocket.

### Candidate overlap handling

- retains the accession/pocket uniqueness safeguard used by the downstream
  within-panel pharmacophore comparison;
- assigns each group the highest-quality eligible pocket that has not already
  been assigned to an earlier-ranked group;
- records `ALL_ELIGIBLE_CANDIDATE_POCKETS_ALREADY_ASSIGNED` when an overlapping
  group has no unique alternative instead of aborting the complete panel;
- records the conflicting accession/pocket pairs and the retained evolutionary
  groups in the exclusion audit; and
- adds regression coverage for both alternative assignment and audited
  exclusion paths.

Scientific gates and the v0.2.0 configuration values are unchanged.

### Reproducible Dundee execution

- adds one idempotent project launcher covering installation, source checks,
  test validation, configuration validation, manifest preparation and Slurm
  submission;
- caches successful validation by exact Git commit outside the repository; and
- writes a submission receipt so re-running the launcher cannot create a
  duplicate Slurm job.

The patch passes 80 tests at 96.10% branch-aware coverage, together with the
PEP 8, Google-style docstring and shell syntax release gates.

## v0.2.0

<!-- source: RELEASE_NOTES_v0_2_0.md; sha256: f3380f5ba0b4da002dfc602e43934b0afd3dd7656f84d8f13fd6fac3e6061117 -->

Release-quality expanded-panel structure-guided chemistry for the ARIA plant
E3 workflow.

### Candidate authority

- removes automatic ranks 1–10 selection from the run path;
- requires an explicit manifest fixing evolutionary group, rank, accession,
  species, pocket, structure checksum and decision provenance;
- distinguishes `EXPANDED_COMPUTATIONAL_SCREEN` from
  `PROJECT_LEAD_APPROVED` without implying human approval;
- provides a quality-first top-200 manifest-preparation command; and
- publishes an explicit exclusion audit and checksummed preparation
  provenance.

### Scientific gates and outputs

- adds configurable mapping-fraction and conservative pocket-pLDDT gates;
- ensures high druggability cannot rescue a low-confidence pocket;
- records all failed hand-off reasons rather than silently discarding groups;
- recalculates uniqueness within the exact manifest panel;
- publishes a 27-combination conservation, confidence and uniqueness
  sensitivity table; and
- retains empty, schema-valid fragment tables in `prepare_only` mode.

### Reproducibility and licensing

- records the Git commit and tracked package-source state;
- production configuration requires a clean tracked checkout;
- copies the exact candidate manifest and configuration into run provenance;
- retains checksum binding for every scientific input and output;
- updates method status for the public FMOPhore code while making no FMO or
  FP-score claim; and
- excludes AlphaFold3 model parameters from execution under the strict SPDX
  open-source component policy.

### Validation repairs

- repairs the earlier slice-spacing, trailing-whitespace and case-sensitive
  Gemmi test defects;
- expands failure-path and regression coverage, including the pilot rank-nine
  low-confidence pocket;
- raises the enforced branch-aware coverage threshold from 90% to 95%; and
- passes 79 tests with 96.20% branch-aware coverage in the release checkout.

## v0.1.0

<!-- source: RELEASE_NOTES_v0_1_0.md; sha256: 406205b82684296f77fc872ffbf32c4348da11e84eca39c56b3805061c11e897 -->

Initial open-source structure-guided chemistry release for the ARIA plant E3
workflow.

### Scientific scope

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

### Method and licence boundaries

- no commercial or separately negotiated software entitlement is required;
- the configuration rejects restricted tools and non-approved SPDX labels;
- every run publishes `COMPONENT_LICENCES.tsv`, `METHOD_STATUS.tsv` and
  `MILESTONE_COVERAGE.tsv`;
- AlphaFold3, FMOPhore and FrAncestor are explicitly `NOT_RUN`; and
- results are not labelled as FMO energies, docking, affinity, binding,
  selectivity or PROTAC efficacy.

### Workflow integration

End-to-end Stage `09c_computational_chemistry` is disabled and non-required by
default. When disabled, its normal `skipped_optional` manifest satisfies the
Stage 10 dependency without requiring this component environment.
