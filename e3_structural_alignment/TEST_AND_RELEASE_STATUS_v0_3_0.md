# e3_structural_alignment v0.3.0 test and release status

## Scope

This release adds the ranked top-group pocket-review HTML generator,
`e3-pocket-review`, and its local and Slurm entry points.

## Verified quality gates

- 57 Python tests passed.
- Complete package branch-aware coverage: 92.75%.
- New review modules:
  - `review_cli.py`: 96.30%;
  - `review_data.py`: 97.71%;
  - `review_models.py`: 100%;
  - `review_pipeline.py`: 99.46%;
  - `review_reporting.py`: 100%.
- PEP 8 checks passed with a 100-character line limit.
- Google-style docstring checks passed.
- All shell entry points passed `bash -n`.
- Direct, missing-input, malformed-FASTA, mismatched-coordinate,
  missing-model, missing-alignment, rank-drift, checksum-resume, forced
  supersession and failed-publication paths are directly tested.
- Generated group and index JavaScript passed `node --check`.
- A complete synthetic report build and checksum-valid no-op resume passed.

## Scientific safeguards

- Stage 10 `final_evolutionary_rank` is preserved without recalculation.
- Strict rank-one and top-k sensitivity evidence remain separate.
- Exact Stage 09 one-based FASTA coordinates are used for alignment highlights.
- Exact FASTA, alignment and structure coordinates are also published as TSV.
- The top-group comparison matrix preserves strict and sensitivity columns
  without calculating a replacement score.
- The evidence matrix filters without reordering rows, and each group page has
  interactive 3D, linear-position and residue-alignment views.
- Missing models and missing alignments are explicit report states.
- Structure checksums and alignment checksums are bound into the run digest.
- All embedded source checksums and all output checksums are recorded.
- HTML states that predicted pockets do not establish binding or PROTAC
  function.

## Runtime status

The package is ready for installation. Production report generation must wait
until the v0.11.0 top-100 sensitivity run has completed through Stage 10,
because the authoritative top-50 relation is a Stage 10 output.
