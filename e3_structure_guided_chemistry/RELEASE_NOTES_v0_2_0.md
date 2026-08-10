# e3_structure_guided_chemistry v0.2.0

Release-quality expanded-panel structure-guided chemistry for the ARIA plant
E3 workflow.

## Candidate authority

- removes automatic ranks 1–10 selection from the run path;
- requires an explicit manifest fixing evolutionary group, rank, accession,
  species, pocket, structure checksum and decision provenance;
- distinguishes `EXPANDED_COMPUTATIONAL_SCREEN` from
  `PROJECT_LEAD_APPROVED` without implying human approval;
- provides a quality-first top-200 manifest-preparation command; and
- publishes an explicit exclusion audit and checksummed preparation
  provenance.

## Scientific gates and outputs

- adds configurable mapping-fraction and conservative pocket-pLDDT gates;
- ensures high druggability cannot rescue a low-confidence pocket;
- records all failed hand-off reasons rather than silently discarding groups;
- recalculates uniqueness within the exact manifest panel;
- publishes a 27-combination conservation, confidence and uniqueness
  sensitivity table; and
- retains empty, schema-valid fragment tables in `prepare_only` mode.

## Reproducibility and licensing

- records the Git commit and tracked package-source state;
- production configuration requires a clean tracked checkout;
- copies the exact candidate manifest and configuration into run provenance;
- retains checksum binding for every scientific input and output;
- updates method status for the public FMOPhore code while making no FMO or
  FP-score claim; and
- excludes AlphaFold3 model parameters from execution under the strict SPDX
  open-source component policy.

## Validation repairs

- repairs the earlier slice-spacing, trailing-whitespace and case-sensitive
  Gemmi test defects;
- expands failure-path and regression coverage, including the pilot rank-nine
  low-confidence pocket;
- raises the enforced branch-aware coverage threshold from 90% to 95%; and
- passes 79 tests with 96.20% branch-aware coverage in the release checkout.
