# Release checklist

## Code and tests

- [ ] `python -m compileall -q src tests` passes.
- [ ] `pycodestyle src tests --max-line-length=88` passes.
- [ ] All unit tests pass.
- [ ] Function-test matrix reports no unmapped source function.
- [ ] Integration tests pass.
- [ ] Synthetic end-to-end test passes.
- [ ] Real-DIAMOND end-to-end test passes in the pinned environment.
- [ ] Coverage report is reviewed and any uncovered operational branch is
      justified.
- [ ] Snakemake dry run passes with the release configuration.

## Inputs and configuration

- [ ] Sample manifest has been reviewed and versioned.
- [ ] Known-E3 seed table has been reviewed and versioned.
- [ ] Source checksums are complete.
- [ ] Species, taxon, proteome and release metadata are populated where known.
- [ ] Output root is new and clearly labels legacy or production mode.
- [ ] Thread, memory and benchmark repeat settings match the execution platform.
- [ ] DIAMOND identity mode is deliberate and compatible with the pinned version.

## Execution and QC

- [ ] Every expected output is non-empty.
- [ ] `resource_validation.tsv` contains no failures.
- [ ] Cluster identifiers map to sequence metadata.
- [ ] E3-seeded cluster count is plausible and investigated if unexpected.
- [ ] Raw and strict member counts are reviewed.
- [ ] Representative/all-member/strict-member FASTAs are present.
- [ ] Logs contain no unreviewed warnings or tracebacks.
- [ ] Command JSON and run manifest are present.

## Benchmarking

- [ ] At least three formal repeats completed where required.
- [ ] Dataset sequence/residue counts are recorded.
- [ ] Hardware, scheduler, filesystem and software versions are recorded.
- [ ] Wall time, CPU time and observed peak memory are reported.
- [ ] Extrapolated and measured values are clearly separated.
- [ ] Figures are regenerated from the released machine-readable tables.

## Scientific reporting

- [ ] Results are described as clusters containing at least one known E3
      candidate.
- [ ] No statement implies every cluster member is an E3 ligase.
- [ ] Raw and strict membership are distinguished.
- [ ] Legacy reproduction and production analysis are not conflated.
- [ ] Limitations and downstream validation requirements are stated.

## Packaging

- [ ] Release version and changelog are updated.
- [ ] Git commit/tag is recorded.
- [ ] Generated data are not accidentally bundled into the source release.
- [ ] No passwords, tokens, user-specific absolute paths or macOS sidecars exist.
- [ ] Source archive checksum is written.
- [ ] Documentation files and example configuration are included.
