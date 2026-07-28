# e3_end_to_end_workflow v0.9.6

Release date: 2026-07-28

## Disabled-stage reporting repair

Version 0.9.6 corrects the reporting contract for optional stages that are
disabled while retaining their future scientific output paths in the
configuration.

The stage runner already behaved correctly during execution: it did not run
the disabled component, wrote `SKIPPED.tsv` and did not validate inactive
scientific outputs. The reporting layer nevertheless attempted to inspect
every configured output path. This caused `09b_structural_alignment` to fail
with `FileNotFoundError` while summarising
`structural_alignment/tables/structural_alignments.parquet`.

Disabled stages now:

- validate and summarise their explicit `SKIPPED.tsv` record;
- leave configured scientific output paths inactive;
- report `declared_outputs_validated: false`;
- record both configured and active declared-output counts; and
- publish normally with status `skipped_optional`.

A regression test uses a disabled stage with a non-empty configured output
list, matching the production configuration that exposed the defect.

No structural alignment was run or lost. No scientific schema, scoring rule,
controlled input, configuration digest or completed stage output is changed.
The existing production run can resume against the same immutable YAML after
the repaired package is installed.
