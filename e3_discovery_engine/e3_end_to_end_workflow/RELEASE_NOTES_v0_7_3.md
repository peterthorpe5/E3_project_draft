# e3_end_to_end_workflow v0.7.3

This patch fixes the production stage-00 HTML-report failure observed on 23 July 2026.

## Root cause

The controlled-input validator correctly accepted the complete grant-aligned reuse input set, but
the report presenter recognised only the three older labels `proteomes`, `seeds` and `shortlist`.
When the production run supplied `candidate_evidence`, report generation raised
`KeyError: 'candidate_evidence'` after the scientific output had already validated.

## Correction

- Provides explicit report roles for every current production input authority.
- Uses a conservative human-readable fallback for future validated input identifiers.
- Keeps input paths, file sizes and SHA-256 checksums in both stage and consolidated reports.
- Adds a regression test that executes production-mode stage `00_inputs` through HTML publication.
- Adds unit coverage for the complete current reuse label set and an unknown future label.

## Validation

- 124 Python tests passed.
- Enforced branch-aware coverage passed at 90%.
- PEP 8, Google/PEP 257 docstring and Python compilation checks passed.
- Snakemake lint passed.
- The complete 13-stage synthetic workflow, bounded rerun, resume and final no-op dry run passed.
