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

## Version 0.1.12 additions

- [ ] `psutil` is present in the production environment.
- [ ] Every major stage writes a non-empty `resource_metrics/*.tsv` file.
- [ ] `resource_usage_summary.tsv` contains non-zero peak RSS values.
- [ ] `realignment_content_summary.tsv` agrees with input and cluster counts.
- [ ] All matched seed, strict seed and strict non-seed candidate outputs exist.
- [ ] The provenance manifest records the Python DuckDB version and Git state.

## Version 0.1.13 Slurm checks

- [ ] `bash -n` passes for submission, worker and status scripts.
- [ ] Static tests confirm `--account=barton --partition=general`.
- [ ] Generated full-run manifest contains 15 inherited source files.
- [ ] `onekp_dataset` uses `header_parser=onekp_scaffold` with strict parsing.
- [ ] Job-local scratch is available and large enough for DIAMOND temporary data.
- [ ] Slurm memory exceeds the configured DIAMOND memory limit.
- [ ] The cluster `e3_discovery` environment contains DIAMOND 2.2.3 and Snakemake.
- [ ] The full job creates scientific QC, resource summaries, Slurm accounting and a compact review bundle.
- [ ] CPU time is checked against `sacct` before it is used in a formal report.

## Version 0.1.14 FASTA and submission checks

- [ ] Confirm strict mode still rejects empty records with path, record and
  header-line context.
- [ ] Confirm 1KP skip mode records permitted exclusions and preserves original
  source record indices.
- [ ] Confirm the configured maximum skipped-empty-record safeguard is enforced.
- [ ] Confirm `qc/skipped_fasta_records.tsv` is a declared Snakemake output.
- [ ] Confirm the login-node preflight reports every missing input together.
- [ ] Confirm Conda older than 24.7.1 is rejected before `sbatch`.
- [ ] Confirm failed Snakemake dry runs print the complete dry-run log.
