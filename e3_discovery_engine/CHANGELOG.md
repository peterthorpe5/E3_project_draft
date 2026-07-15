# Changelog

## 0.1.14 - 2026-07-15

- Audit the inherited 25,241,940-record 1KP protein FASTA and document the two
  header-only records with no amino-acid sequence:
  `scaffold-IHWO-2001393-Marchantia_paleacea-mycorrizal` and
  `scaffold-VRGZ-2004363-Petalonia_fascia`.
- Keep empty protein records fatal by default for every ordinary and named
  proteome input.
- Permit the generated `onekp_dataset` manifest row to skip at most ten empty
  records, preserving a deliberately conservative safeguard above the two
  observed records.
- Write every skipped record to `qc/skipped_fasta_records.tsv` with source
  sample, record index, header line, header, identifier and reason.
- Add source-record and skipped-record counts to `qc/sample_summary.tsv` and
  the preparation result summary while retaining original source record
  indices for all accepted sequences.
- Improve FASTA validation errors so they include the source path, source
  record number, header line and complete offending header.
- Add a login-node preflight before `sbatch` that validates the usable Conda
  version, the inherited sample list, seed table, production environment and
  every required FASTA together.
- Fall back to `legacy_reference/samples.inherited.json` when the source-tree
  `samples.json` was not included in the cluster backup.
- Print the complete Snakemake dry-run log automatically when a dry run fails.
- Move the full cluster run and review-bundle naming to `v0_1_14`; existing
  local configurations and all earlier result folders remain unchanged.
- Expand the automated suite to 215 tests, with 212 passing and three optional
  external-DIAMOND tests skipped; total source coverage remains 98%.

## 0.1.13 - 2026-07-15

- Add sequence-level parsing of inherited 1KP scaffold identifiers, retaining
  the combined source file while recovering the four-letter 1KP sample code
  and source species for each protein record.
- Add strict 1KP header validation so malformed records stop preparation rather
  than being silently collapsed into one artificial combined sample.
- Add generation of the 15-source full 1KP+ cluster manifest and YAML directly
  from the inherited `samples.json` and verified cluster paths.
- Extend sequence Parquet, DuckDB, QC and summary outputs with physical source
  file, biological sample, biological species, 1KP code and parser-status
  fields.
- Add configurable DIAMOND temporary storage and path-alias roots for Slurm
  jobs using fast job-local scratch.
- Improve Linux CPU accounting with POSIX self-and-completed-child resource
  counters and retain Slurm `sacct` output as an independent accounting source.
- Add University of Dundee Slurm submission, worker and status scripts using
  account `barton` and partition `general`.
- Add completion/failure markers, restart-safe Snakemake execution, persistent
  provenance, scientific QC validation and automatic compact review bundles.
- Add preflight storage checks requiring configurable free space in persistent
  results storage and job scratch before the full run begins.
- Retain scratch after failure for diagnosis and remove job-created scratch
  only after successful completion.
- Retain the existing local macOS configurations and driver scripts.
- Expand tests for 1KP metadata, generated cluster configs, Slurm contracts,
  storage checks, scratch handling, DIAMOND tmpdir propagation and CPU
  accounting.

## 0.1.12 - 2026-07-14

- Add cross-platform process-tree resource monitoring with `psutil` for every
  major workflow stage, including aggregate peak resident memory (RAM), wall
  time, user CPU time, system CPU time and process count.
- Write per-stage resource records, a stage summary table and peak-RAM PNG/PDF
  figures independently of Snakemake's platform-dependent memory fields.
- Add automatic realignment-content checks confirming one row per input
  sequence, one representative self-alignment per cluster, complete numeric
  evidence and agreement with raw DeepClust membership.
- Preserve every matched inherited E3 seed explicitly, split strict and
  non-strict matched seeds, and expose strict non-seed candidate members as a
  separate DuckDB table, Parquet export and FASTA file.
- Add automatic key-metric, per-sample, realignment, cluster-size and
  cross-species TSV summaries.
- Record installed Python package versions, including Python DuckDB, plus the
  Git commit and dirty working-tree state in the run manifest.
- Retain the `tantan` production masking default and all strict scientific
  thresholds unchanged.
- Expand the unit and integration suite to cover the new monitoring,
  provenance, validation, summary and candidate-separation functions.

## 0.1.11 - 2026-07-14

- Ignore macOS AppleDouble sidecar files such as `._benchmark.tsv` when
  discovering Snakemake benchmark tables on external volumes.
- Ignore benchmark tables located below hidden directories.
- Accept UTF-8 benchmark files with or without a byte-order mark while still
  rejecting malformed visible benchmark files with a clear validation error.
- Add regression tests for AppleDouble files, hidden directories, UTF-8 BOM
  handling and malformed benchmark input.
- No scientific thresholds, clustering behaviour, E3-seed logic or DuckDB
  schemas changed.

## 0.1.10 - 2026-07-14

- Corrected the production masking default from target-only `seg` to symmetric
  `tantan` for DIAMOND DeepClust self-alignment.
- Added defensive validation that rejects `seg` and unsupported asymmetric
  masking before launching DIAMOND.
- Added a focused diagnostic for `asymmetric masking for self alignment`.
- Updated real-DIAMOND end-to-end tests to exercise the production `tantan`
  setting.
- Updated README, methods and operations documentation.
- No clustering thresholds, E3-seed logic or output schemas changed.

## 0.1.9 - 2026-07-14

- Fix DIAMOND 2.2.x clustering failures when the configured output root
  contains whitespace, such as `/Volumes/One Touch/...`.
- Create or reuse a deterministic whitespace-free symbolic-link alias and use
  the alias for all `makedb`, `deepclust` and `realign` input/output paths.
- Keep files physically in the configured result directory and record the
  mapping in `provenance/diamond_path_alias.json`.
- Add optional `diamond.path_alias_root` configuration for an explicitly
  chosen whitespace-free alias parent.
- Shell-quote external command logging with `shlex.join` so diagnostic logs
  show argument boundaries accurately.
- Add unit and CLI integration tests for alias creation, reuse, conflicts,
  provenance and whitespace-free DIAMOND command arguments.
- Extend the optional real-DIAMOND end-to-end suite with a workflow root that
  deliberately contains spaces.
- No scientific thresholds, clustering criteria or downstream interpretation
  changed.

## 0.1.8 - 2026-07-14

- Quote every Snakemake-expanded input, output, log, configuration, benchmark,
  and output-directory path used in shell commands.
- Support repository and result paths containing spaces, including macOS
  external volumes such as `/Volumes/One Touch`.
- Create each rule's log directory before shell redirection occurs.
- Add regression tests that reject unquoted workflow path placeholders.
- No scientific thresholds or clustering behaviour changed.

## 0.1.7 - 2026-07-14

- Expanded every Python function and method docstring using a consistent
  PEP 257-compatible Google style.
- Documented purpose, arguments, return or yield values, and relevant raised
  exceptions, including private helpers and nested generator functions.
- Expanded dataclass documentation with field-level ``Attributes`` sections.
- Added an automated source-documentation contract test covering module, class,
  function and method docstrings.
- Added a code-documentation standard describing the required format for future
  development. No workflow behaviour or scientific logic changed.

## 0.1.6 - 2026-07-14

- Fixed parsing of native DIAMOND 2.2.3 `realign` output, which labels
  representative/member sequence lengths as `clen` and `mlen` rather than
  the requested `qlen` and `slen`.
- Retained support for both query/subject and centroid/member field naming,
  including DIAMOND's capitalised `Bitscore` header.
- Added regression tests using the exact 12-column header observed in the
  external macOS DIAMOND run, a complete Parquet conversion test and the
  Python-managed end-to-end resource build using native DIAMOND field names.
- Corrected README wording so the DeepClust header requirement and tolerant
  historical-file parser are described consistently.

## 0.1.5 - 2026-07-14

- Restored DIAMOND's flag-only `--header` option for `deepclust`. DIAMOND
  2.2.x `realign` requires this native header and rejects a headerless
  clustering-membership file.
- Verified from recovered inherited DeepClust outputs that DIAMOND 2.2.x emits
  the native header `centroid<TAB>member`; the parser accepts this format.
- Added command-construction and parser regression tests for the exact native
  header contract.
- Added a focused diagnostic hint for `Clusters file is missing header line`.

## 0.1.4 - 2026-07-13

- Fixed conversion of real DIAMOND 2.2.3 DeepClust output. Cluster membership
  is now parsed using the documented positional two-column format and no
  longer requires a specific header spelling.
- Added support for recognised header variants including representative/member,
  cseqid/mseqid, centroid/member and cluster-representative labels.
- Made the cluster parser tolerant of both native-header and headerless
  two-column files. Release 0.1.5 restores the native header because DIAMOND
  2.2.x `realign` requires it.
- Applied the configured masking mode consistently to DeepClust and realign.
- Treat a header-only realignment table as a valid zero-row result, which can
  occur when all clusters are singletons, while logging a prominent warning.
- Added unit and integration tests for headerless clustering, header variants,
  comments, malformed rows, empty realignment output and DuckDB construction
  with zero realigned pairs.

## 0.1.3 - 2026-07-13

- Fixed DIAMOND 2.2.3 exact-identity clustering failure: `--id` requires
  alignment traceback, which is incompatible with compositionally adjusted
  matrix modes.
- Added explicit `diamond.comp_based_stats` configuration and pass
  `--comp-based-stats` to both `deepclust` and `realign`.
- Production and end-to-end profiles now use mode `0`; legacy approximate
  reproduction uses mode `1`.
- Added defensive rejection of modes 2-6 for exact identity/realignment.
- Added focused diagnostic hints for the DIAMOND error
  `Traceback with adjusted matrix not supported`.
- Added unit and configuration regression tests for this compatibility rule.

## 0.1.2 - 2026-07-13

- Fixed DIAMOND 2.2.x command construction to use the supported `--db`
  option for `deepclust` and `realign`; `--database` is not accepted by the
  DIAMOND 2.2.3 binary.
- Updated the real-DIAMOND end-to-end test to use `--masking none` rather than
  the unsupported legacy value `0`.
- Added defensive validation for identity mode and masking values.
- Added regression tests that reject `--database` and invalid masking values.

## 0.1.1 - 2026-07-13

- Fixed a macOS-specific unit-test failure caused by `/tmp` resolving to `/private/tmp`.
- Corrected Conda environment files for macOS-64 by removing the invalid
  `channel_priority` key and pinning PyArrow 24.
- Renamed the production Conda environment to `e3_discovery`.
- Added DIAMOND log-tail reporting to external-tool exceptions.
- Added an optional persistent output directory for the external DIAMOND
  end-to-end test to simplify debugging.

## 0.1.0 - 2026-07-13

Initial production rewrite of the inherited Milestone 1 E3 discovery engine.

- Added non-destructive streaming FASTA preparation.
- Added metadata-preserving sequence and seed Parquet tables.
- Added explicit DIAMOND command construction and version checks.
- Added exact realignment outputs and strict post-realignment filters.
- Added E3-seeded cluster DuckDB and curated Parquet resources.
- Added FASTA exports with non-overclaiming names.
- Added benchmark aggregation, plots and provenance manifests.
- Added structured logging, defensive validation and atomic outputs.
- Added unit, integration, synthetic end-to-end and optional external tests.
- Preserved the inherited implementation under `legacy_reference/`.

