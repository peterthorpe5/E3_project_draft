# e3_structure_guided_chemistry v0.2.1

Patch release for expanded-panel preparation when Stage 08 evolutionary groups
overlap on the same candidate accession and pocket.

## Candidate overlap handling

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

## Reproducible Dundee execution

- adds one idempotent project launcher covering installation, source checks,
  test validation, configuration validation, manifest preparation and Slurm
  submission;
- caches successful validation by exact Git commit outside the repository; and
- writes a submission receipt so re-running the launcher cannot create a
  duplicate Slurm job.

The patch passes 80 tests at 96.10% branch-aware coverage, together with the
PEP 8, Google-style docstring and shell syntax release gates.
