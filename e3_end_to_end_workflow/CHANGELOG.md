# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.16.0

- Adds an optional, restartable human-and-plant structural extension to both
  completed-release and full start-to-finish execution modes.
- Selects exact human members from the same root HOGs, computes only missing
  human AlphaFold/FPocket/P2Rank evidence and preserves each recorded plant
  structural reference.
- Publishes combined pocket conservation, US-align/TM-align superpositions and
  a separate app-ready review bundle without modifying plant-only results.
- Republishes the plant-only portable review from existing Stage 09b viewers so
  the enhanced plant tab requires no structural recomputation.
- Adds durable Slurm-controller and local launchers, checksum-bound task reuse,
  exact human sequence inventories and a reviewed top-200 cluster template.

## v0.15.0

<!-- source: RELEASE_NOTES_v0_15_0.md; sha256: dd205ea122c6530514e9a2cd995ce601720f6a1ac104e5669d773a2d9d646ca6 -->

This release connects the current full-universe structure-guided chemistry
campaign to the normal workflow DAG and application resource.

- Stage 09c now depends on the completed Stage 09b structural comparison.
- The production template uses generated ligandability and can run the
  checksum-bound all-group chemistry campaign without a hand-written candidate
  manifest.
- Stage 10 imports the chemistry target, pharmacophore, sensitivity, integrated
  evidence and optional ranked-pocket relations into DuckDB.
- Fresh-run validation rejects unresolved placeholders anywhere in the YAML,
  rather than checking only tool and command fields.
- Both application hand-offs continue to use the same integrated DuckDB and
  run-directory contracts.

The strict fresh-run review still requires real, package-compatible adapters for
fresh discovery, orthology and expression acquisition before a new expanded
proteome panel can be submitted. The template keeps these requirements explicit
and fails closed while they are unresolved.

## v0.14.1

<!-- source: RELEASE_NOTES_v0_14_1.md; sha256: 639a7738cb7731a167ceaf6f329356202cadf7b14e0914f347f81329b2202b49 -->

This patch release adds an optional controller-only Slurm quality-of-service
setting for long, restartable structural campaigns.

### Change

- `submit_e3_controller_slurm.sh --controller-qos NAME` adds `--qos NAME` to
  the Snakemake controller allocation only. Child scientific jobs continue to
  use their configured account and partition settings.
- The selected quality of service is recorded in `controller.slurm.tsv`.
- Scheduler names remain strictly validated and the default is unchanged when
  `--controller-qos` is omitted.

This supports the 1,972-group Milestone 2 structural campaign without changing
the scientific methods or allocating long-duration resources to every child
job.

## v0.14.0

<!-- source: RELEASE_NOTES_v0_14_0.md; sha256: 29c153e4c7b4d0c1f1c1b08a30a0ac732adf6a61f0bfadec9953c89f4437ef01 -->

Version 0.14.0 corrects the Stage 08 structure-selection contract and adds an
optional open-source computational-chemistry hand-off.

### Stage 08 correction

- `structure_group_limit` is now applied to distinct primary evolutionary
  groups, rather than to DeepClust cluster rows.
- Every DeepClust contributor to a selected group receives the same
  `computational_structure_selected` flag.
- `structural_analysis_accessions_all_members` now contains members of all
  selected evolutionary groups.
- Stage QC separately reports candidate clusters, distinct evolutionary
  groups, contributing clusters, all members and selected representatives.
- The obsolete blank `structural_accession_count` QC field has been removed.

This is a scientific-output change. Re-run Stage 08 in a new versioned run;
do not overwrite an immutable v0.13.0 result.

### Optional Stage 09c

- Adds `09c_computational_chemistry` after ligandability and before resource
  integration.
- The stage is disabled and non-required by default. A disabled stage produces
  the normal `skipped_optional` manifest and does not block Stage 10.
- When enabled, the stage imports residue-derived pharmacophore, evolutionary
  stability, between-group uniqueness and optional open-fragment tables into
  the integrated DuckDB.
- The supplied component uses only open-source dependencies and refuses any
  configuration that allows commercial or restricted-licence tools.
- FMOPhore, FrAncestor and AlphaFold3 are explicitly recorded as `NOT_RUN`;
  their names are never used for results from the open alternative.

### Operational notes

- The production template declares all group-level Stage 08 authorities.
- The workflow runner may create `logs/command.log` before the chemistry
  command starts; the component accepts that runner-owned directory while
  still rejecting pre-existing scientific outputs.

## v0.13.0

<!-- source: RELEASE_NOTES_v0_13_0.md; sha256: 8c7421df110db0d652bed1cb42a99b4f0fbd70f7774abd74466466e07faf5cde -->

Version 0.13.0 consumes the corrected Expression Atlas v0.5.0 data contract.

- uses median expression for Atlas five-number contexts;
- applies the inclusive `>= 0.5` expression boundary;
- prefers TPM per species/experiment and records FPKM fallback;
- retains candidate-by-context tissue, stage, treatment and condition output;
- separates `NOT_MAPPED`, `NO_EXPRESSION_RECORDS` and measured low/zero states;
- rejects missing/duplicate metadata contexts and stale expression/metadata
  checksum bindings;
- restricts domain assessed/supported species to configured target species;
- adds known-answer, corruption, boundary and off-target-denominator tests.

Validation: 224 tests passed, one optional environment test skipped, with
90.56% branch-aware coverage.

## v0.12.0

<!-- source: RELEASE_NOTES_v0_12_0.md; sha256: 32111f98fae282d8497db24792495166cd9169f33f4ca0eb1a57dd7cfdea2d4c -->

### Expression evidence-state correction

- `NOT_MAPPED` candidate members now retain null measurement and support fields
  instead of potentially misleading numerical zeroes.
- A uniquely mapped gene with no imported Atlas measurements is reported as
  `NO_EXPRESSION_RECORDS` and excluded from the assessed-expression denominator.
- Genuine measured limited or zero expression remains distinct from missing or
  unmapped evidence.
- `candidate_expression_context_summary` retains experiment, unit, sample,
  organism part (tissue), developmental stage, genotype, cultivar, treatment,
  condition and bounded expression summaries for every uniquely mapped gene.
- The integrated DuckDB publishes this normalised context relation for app-side
  species, tissue and candidate filtering.
- The primary top-200 result remains immutable; these rules apply to new or
  explicitly rerun Stage 07 and downstream releases.

## v0.11.0

<!-- source: RELEASE_NOTES_v0_11_0.md; sha256: 0d6a9f84865ba40485c8de1a32a3188ce4b658859de841637baaa7c755070d81 -->

### Milestone-1 sensitivity and release cycle

This release preserves the completed v0.10.2 50-group result as the stringent
primary analysis and adds a separate exploratory configuration:

`config/grant_aligned_structural_sensitivity_top100_v0_11_0_20260729.cluster.yaml`

The new profile:

- retains all 38 strict pre-structure passes and extends structural review to
  the ordered top 100 evolutionary groups;
- retains the independently selected rank-one pocket result;
- compares the selected reference pocket with the top five pockets in each
  member;
- requires US-align and TM-align to support the same candidate member pocket;
- reports alternative-pocket rescues separately from the primary result;
- publishes named druggability and top-k gate-sensitivity scenarios;
- exports canonical and ordered top-50 review tables for manual selection of
  up to ten experimental priorities;
- publishes ranked-pocket, sensitivity-comparison, member-summary and
  evolutionary-group-summary relations in DuckDB, Parquet and TSV formats;
- rebases temporary shard paths before provenance publication; and
- treats intentionally disabled optional stages as outside the configured
  release scope rather than as application-release blockers.

The sensitivity scenarios do not overwrite `grant_aligned_final_pass`.

### Quality evidence

The end-to-end suite enforces PEP 8, Google-style docstrings, direct unit and
integration tests, and at least 90% aggregate coverage. The Python application
suite remains above 95% coverage. The R Shiny package retains its testthat
suite; run it in the documented R environment before cluster release.

## v0.10.2

<!-- source: RELEASE_NOTES_v0_10_2.md; sha256: c18c504877c42d45ced6dced5d3a44955cdc6336030f5c16a432bf4647f66873 -->

Release date: 28 July 2026

Version 0.10.2 repairs three defects exposed by the production
`grant_aligned_structural_completion_top20_v0_10_0_20260728` run.

### Scientific and data-lineage corrections

- Stage 09 now reads exact candidate protein sequences from the checksum-validated
  `candidate_group_member_sequences.parquet` authority published by Stage 05.
- Each sequence length and SHA-256 value is verified before pocket residues are
  mapped to FASTA coordinates.
- Prepared proteomes and reused OrthoFinder working FASTAs remain explicit
  fallbacks for workflows that do not publish the Stage 05 authority.
- Stage 09 fails closed when selected pockets exist but zero exact sequences are
  resolved, instead of publishing an empty conservation-members table.
- The Stage 09 validation table now reports available and unavailable sequence
  counts.

### Structural asset publication corrections

- Generated ligandability asset paths are rebased from temporary
  `.task_NNNN.running.UUID` locations to stable `task_NNNN` shard locations.
- Every rebased asset is required to exist and match its recorded byte count and
  SHA-256 checksum before the aggregate manifest is published.
- Stage 09b now fails if selected accessions resolve zero structural models or if
  no selected multi-accession group resolves at least two models for comparison.
- Stage 09b validation and provenance now record resolved-model and comparable-group
  counts.

### Test isolation

- `run_tests.sh` now creates an isolated temporary synthetic run and configuration.
  Stale checksum-bound tokens from an earlier release can no longer cause the
  release gate to fail.

### Production recovery

The 559 successful ligandability shards from the existing Dundee run remain
reusable. Stage 09 must be reaggregated with v0.10.2. The old Stage 09b shard
cache must be archived because its completion markers describe zero-model
outputs; Stage 09b and downstream integration must then be rerun.

No scoring threshold, target-species definition, grant gate or experimental
candidate limit is changed by this release.

## v0.10.1

<!-- source: RELEASE_NOTES_v0_10_1.md; sha256: 2c4d6627c00975d1d7f6f25f45537dcbe3eb586bd75bfe0f1cd28a1d6059453b -->

### Stage 09 FASTA-coordinate aggregation hotfix

Version 0.10.1 fixes a Stage 09 aggregation failure observed after the
distributed ligandability campaign completed successfully.

#### Corrected behaviour

- Import Python's `math` module before using `math.inf` as the deterministic
  sort value for residues without an exact FASTA coordinate.
- Retain residues whose model-to-FASTA mapping is unavailable and sort them
  after residues with validated integer coordinates.
- Add a regression case covering `fasta_position=None` and the
  `LABEL_SEQUENCE_ID_UNAVAILABLE` status.

#### Resume contract

- No configuration, shortlist, component output or completed shard is changed.
- The existing v0.10.0 structural run can be resumed in place.
- Checksum-valid Stage 09 ligandability shards remain reusable.
- Stage 09 aggregation reruns and publishes its outputs atomically before
  Stage 09b begins.

## v0.10.0

<!-- source: RELEASE_NOTES_v0_10_0.md; sha256: 694bebc92360676f454491e00a459b8740356efebede7ab64bd44d3eaac2eb33 -->

### Structural-completion decision release

Version 0.10.0 adds the production path from the completed v0.9.7
pre-structure resource to an auditable structural and decision-ready result.

#### Scientific contract

- Preserve the completed parent run and checksum-validate every imported Stage
  02-08 output.
- Rank distinct primary OrthoFinder evolutionary groups while retaining every
  contributing DeepClust cluster in a separate relation.
- Select one deterministic, likely-full-length representative per target
  species and evolutionary group, with every alternative retained in an audit
  table.
- Assess at most 50 evolutionary groups and 600 primary structures.
- Keep three-dimensional evidence out of score reweighting until its thresholds
  have been reviewed; report it as an explicit final support/eligibility gate.
- Publish a top-20 computational review shortlist so project leads can select
  ten experimental priorities.

#### Cluster execution

- Scatter ligandability into at most 600 independent four-core tasks.
- Scatter US-align/TM-align analysis into at most 50 independent four-core
  group tasks.
- Use Snakemake's global `--max-jobs 100` limit to cap concurrent cluster work.
- Retain checksum-bound task markers and a hidden work cache so successful
  shards survive controller or aggregate-stage retries.

#### Final reporting

- Add `10_integrated_resource/final_results` as the explicit decision folder.
- Add a formatted multi-sheet Excel workbook with frozen header rows, filters,
  readable widths, metadata, settings and interpretation guidance.
- Publish one-row-per-evolutionary-group, top-20, strict prediction,
  DeepClust-contributor and exclusion-audit tables in TSV and Parquet.
- Add a dedicated Final recommendations section to both the R Shiny and Python
  applications while retaining the complete normalised result browser.

#### Validation

- Production structural configuration loads with 600 ligandability slots, 50
  structural slots and a top-20 decision limit.
- Parent checksum failures, shard resume state, union aggregation, nested
  offline browser assets and component-process failures have dedicated
  regressions.
- The complete production structural Snakemake scatter DAG builds in dry-run.
- The standard 16-job synthetic DAG, controlled rerun, resume and final no-op
  remain release gates.

## v0.9.7

<!-- source: RELEASE_NOTES_v0_9_7.md; sha256: ccb7a40ee1a318b9d486923d120feb7ee6740c203586f6e2603974cec75ff7b0 -->

Release date: 2026-07-28

### Empty Stage 09 schema compatibility repair

Version 0.9.7 corrects Stage 10 integration when the validated Stage 09
`pocket_conservation_summary.parquet` contains zero rows and was created with
the earlier generic empty-table schema.

The legacy writer represented every empty Parquet column as `VARCHAR`.
Stage 10 then attempted expressions such as
`COALESCE(structured_species_count, 0)`. DuckDB rejected the mixed
`VARCHAR` and integer types during query binding, before reading any rows.

Stage 10 now:

- explicitly casts legacy Stage 09 numeric and Boolean columns to their
  scientific types;
- remains strict if a non-empty legacy file contains malformed values;
- assigns the established no-evidence defaults when no matching pocket row
  exists; and
- preserves `NOT_ASSESSED` for disabled three-dimensional structural
  alignment.

New empty Stage 09 pocket-conservation Parquet outputs now retain their
intended numeric and Boolean schema. A regression test recreates the exact
zero-row, all-`VARCHAR` legacy table and demonstrates that the repaired final
query completes.

No controlled input, production configuration, completed upstream result,
scoring weight or configuration digest is changed. The existing production
run can resume against the same immutable YAML after the repaired package is
installed.

## v0.9.6

<!-- source: RELEASE_NOTES_v0_9_6.md; sha256: ba2bbd34ab16247d6f1edb3a11ebf00342ac12d98de9e25d35cd5a26a41bb8b3 -->

Release date: 2026-07-28

### Disabled-stage reporting repair

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

## v0.9.5

<!-- source: RELEASE_NOTES_v0_9_5.md; sha256: f8cad1c1eaebb2c7c208de10c0f9da613610bd87339dd2ed7ac3ba9b14edd9e1 -->

Release date: 2026-07-27

### Stale Slurm controller metadata

Version 0.9.5 corrects the controller duplicate guard for a normal Dundee
Slurm response after an earlier job has aged out of the live queue.

`squeue --jobs JOB_ID` can return a non-zero exit status with:

```text
slurm_load_jobs error: Invalid job id specified
```

This response means that the recorded controller job is no longer present in
the live queue. The launcher now treats this specific diagnostic as
`NOT_IN_QUEUE` and permits a checksum-safe resume. Other non-zero responses,
timeouts and unrecognised states remain fatal, so a genuine scheduler outage
cannot permit a duplicate controller.

### Cluster-portable tests

Routine tests no longer require scheduler subprocesses to complete within a
five-second wall-clock assertion. The Dundee cluster can exceed that threshold
because of scheduler and shared-filesystem latency even when the configured
hard timeout behaves correctly. Regression coverage continues to verify the
required exit status, diagnostics, refusal behaviour and accepted stale-job
path.

No scientific schema, scoring rule, controlled input or production
configuration is changed. Existing checksum-valid stage outputs remain the
restart authority.

## v0.9.4

<!-- source: RELEASE_NOTES_v0_9_4.md; sha256: bd0b8c978de21eacf75d9a55607e3a2d494472fa2dee0513c18a89ea2f665f6a -->

Release date: 2026-07-27

### Slurm query portability

Version 0.9.4 corrects two regressions found during the first Dundee cluster
acceptance run of v0.9.3.

Scheduler queries now use a hard timeout that also terminates stubborn child
processes. This keeps the documented query limit valid across the different GNU
coreutils and process behaviours observed on the development system and the
Dundee cluster.

The `MinJobAge` query is now treated according to its actual purpose:

- `squeue` and `sbatch` remain mandatory for safe duplicate detection and
  controller submission;
- an observed `MinJobAge` below 120 seconds remains a fatal compatibility
  error;
- an unavailable, timed-out or unparsable `scontrol` response produces a
  visible warning but does not block submission; and
- active-controller state still fails closed whenever `squeue` itself cannot
  return a trustworthy result.

The submission path no longer reports the generic unexpected-error trap after
an already diagnosed compatibility failure.

### Regression coverage

The Slurm launcher tests now cover:

- a scheduler child process that survives `TERM`;
- hard timeouts for `squeue`, optional `sacct` and advisory `scontrol` queries;
- successful submission when `scontrol` fails or times out;
- continued rejection of a successfully observed low `MinJobAge`;
- absence of misleading unexpected-error diagnostics for anticipated failures;
  and
- all v0.9.3 duplicate, stale-metadata and scheduler-rejection cases.

No scientific schema, scoring rule, controlled input or production
configuration is changed. Existing checksum-valid stage outputs remain the
restart authority.

## v0.9.3

<!-- source: RELEASE_NOTES_v0_9_3.md; sha256: 76b061ee4fca66596288b28a99512e14bd4be868dbe1cee6492e751dc032673f -->

Release date: 2026-07-27

### Slurm controller submission reliability

Version 0.9.3 separates active-controller duplicate protection from optional
historical accounting. A new controller submission now queries `squeue` only.
It therefore remains possible to resume an interrupted run when `slurmdbd` and
`sacct` are unavailable.

The launcher now:

- reports the submission preflight, run name, immutable configuration and
  scientific-job status backend before calling `sbatch`;
- permits resume only when the previous controller is absent from `squeue` or
  has a recognised terminal state;
- blocks duplicate submission when the prior controller is active;
- fails closed, with a visible diagnostic, when `squeue` fails or returns an
  unrecognised state;
- treats `sacct` as optional, time-bounded enrichment for `--status` only;
- bounds every `squeue`, `scontrol` and optional `sacct` query, with a
  configurable 15-second default;
- validates stale controller metadata before using its recorded job ID;
- reports scheduler rejection explicitly; and
- reports the accepted Slurm job ID if a later launcher operation fails.

Scientific child-job tracking remains explicitly configured to use `squeue`.
The supported executor remains
`snakemake-executor-plugin-slurm>=2.7.1,<3`, and a minimum `MinJobAge` of
120 seconds is required before submission. Dundee reports
`MinJobAge = 300 sec`, which satisfies this condition.

### Regression coverage

The Slurm launcher tests now cover:

- fresh submission;
- stale controller metadata with unavailable `sacct`;
- active-controller duplicate rejection;
- successful terminal-state resumption;
- failed and unrecognised `squeue` responses;
- bounded hanging and failed `sacct` status lookups;
- rejected `sbatch` calls; and
- malformed controller metadata.

No scientific schema, scoring rule, controlled input or production
configuration is changed by this release. Existing checksum-valid stage
outputs remain the restart authority.

## v0.9.2

<!-- source: RELEASE_NOTES_v0_9_2.md; sha256: 3da20ad6a0fabafe4786414db75fd3b28f1dc69551395e8344a9848b3af2f0fc -->

Release date: 2026-07-27

### Slurm controller source-path repair

Version 0.9.1 submitted the controller body as a batch script and correctly requested the workflow
source directory through `sbatch --chdir`. Slurm nevertheless executes a temporary copy of a batch
script from its spool directory. The controller body derived its source tree from
`${BASH_SOURCE[0]}` and therefore searched for `run_e3_end_to_end.sh` under
`/var/spool/slurmd` before Snakemake could start.

Version 0.9.2 passes the already validated absolute workflow source root from
`submit_e3_controller_slurm.sh` to the internal controller job through a required named option.
The job canonicalises that path, verifies the runner and repeats the existing source-to-install
provenance check before launching Snakemake.

A regression test executes a copy of the controller body from a simulated Slurm spool directory
and verifies that it invokes the runner from the explicitly supplied source tree.

### Safe continuation

Controller job `62079` failed before launching Snakemake or any scientific child job. It did not
alter the existing run state. Resume the same immutable configuration and run name after installing
or applying v0.9.2. Keep every checksum-valid completed stage; do not delete the run root and do
not force Stage 05.

## v0.9.1

<!-- source: RELEASE_NOTES_v0_9_1.md; sha256: 5b0a78adb7a0c4aeb9c98cb1616760edef139d0a4f7654d9b67351f75b54302b -->

Release date: 2026-07-27

### Stage 07 Expression Atlas scalability repair

The failed production attempt ended immediately after the normal Stage 07 preamble and did not
publish any declared Stage 07 outputs. The retained log alone cannot distinguish a Slurm
out-of-memory kill from another external termination, because it contains no caught Python or
DuckDB exception. Static inspection nevertheless identified a concrete high-memory execution path
that required correction before another production attempt.

Stage 07 now:

- scans only checksum-validated `atlas_expression_long` partitions whose species occur among the
  selected orthology-group members;
- configures DuckDB to use the stage thread request, limit its managed memory to 75% of the Slurm
  memory request and spill larger intermediates inside the atomic stage working directory;
- reduces the full measurement table to candidate-relevant gene identities before the
  alias-to-gene join, avoiding the previous measurement-level join explosion;
- materialises the mapping and expression summary once each, then publishes Parquet and TSV from
  those bounded tables rather than re-running the analytical queries;
- removes the DuckDB spill directory only after successful query completion; and
- records total, selected and skipped partition counts plus the DuckDB resource limits in
  `qc/expression_validation.tsv`.

Checksum verification, exact identifier tiers, explicit ambiguous/unmapped states and the rule
that unavailable evidence is not a biological negative are unchanged.

### Installation provenance

The repository launcher no longer claims a hard-coded release independently of the imported
Python package. `e3-workflow diagnose-install` reports the active Python executable, CLI path,
distribution version, imported module path and expected source path. Every workflow launcher now
fails before submission if the installed command comes from another version or checkout.

The Slurm submitter performs this check with `conda run --name`, so it verifies the same Conda
environment that the controller job will use rather than whichever Python happens to be active on
the login node.

### Repository layout

Version 0.9.1 is intended to be installed from the true repository-root
`e3_end_to_end_workflow/` directory. The accidental nested `E3_project_draft/` upload is not a
second valid installation root.

### Safe continuation

Stages 00 through 05 of
`grant_aligned_reuse_q9sa03_only_v0_7_3_20260724` remain valid and must not be deleted. After
installing v0.9.1 from the correct source tree, resume the same immutable configuration. Snakemake
will rerun the failed unpublished Stage 07 work and retain checksum-valid completed prerequisites.

The exact Slurm terminal state should still be recovered with `sacct` and the Stage 07 worker log
where available; the scalability correction does not retrospectively prove that the previous job
was killed for memory.

## v0.9.0

<!-- source: RELEASE_NOTES_v0_9_0.md; sha256: b3fa93e9457f8d150be5b8b84293126fa0520a0fa8ed446b9f2f7cfcf3fce225 -->

Release date: 2026-07-25

### Central configuration

- Adds schema version 2 while retaining schema-version-1 compatibility.
- Adds a validated `tools` registry containing executable, reviewed version, Conda environment
  and scalar component parameters.
- Exposes tool values to external argv templates through documented
  `tool_<tool>_<setting>` placeholders.
- Records the resolved central tool registry in every stage manifest.
- Adds `path_base` so generated configurations preserve the base file's relative paths.

### Parameter sensitivity

- Adds `prepare-sweep` for Cartesian or one-at-a-time parameter experiments.
- Permits existing paths below `analysis.` and `tools.` only.
- Adds deterministic run names, configuration checksums, parameter-set checksums and a
  `maximum_runs` expansion guard.
- Adds `compare-sweep`, which publishes run status, candidate-level sensitivity and candidate
  stability as TSV.
- Refuses incomplete comparisons unless `--allow-incomplete` is explicit.

### Complete fresh execution

- Adds `validate-fresh` and repository-root `run_e3_pipeline_fresh.sh`.
- Requires production mode, schema version 2, a central tool registry and all 13 stages.
- Rejects previous discovery, candidate, OrthoFinder, expression, domain-result and
  ligandability authorities.
- Requires generation commands for external scientific stages and rejects unresolved
  `CHANGE_ME` markers.
- Caps the root fresh launcher at ten concurrent scientific jobs.
- Uses the v0.8.0 Slurm-owned controller, so execution continues after logout.

### Documentation

- Adds a searchable MkDocs Material manual under `docs_site/`.
- Adds strict GitHub Pages build/deploy automation.
- Documents quick starts, configuration, fresh execution, Slurm/local operation, parameter
  sweeps, new datasets, every stage, every component package, outputs and troubleshooting.
- Updates the printable operator guide to v0.9.0.

## v0.8.0

<!-- source: RELEASE_NOTES_v0_8_0.md; sha256: 36cfb43d94768346e591c563c7353350850fb3e05a75d0c74857095265756993 -->

Date: 24 July 2026

### Purpose

Version 0.8.0 adds a scheduler-owned Snakemake-controller mode so a complete E3 run can continue
after the submitting terminal disconnects without leaving the controller on a login node.

### Added

- `submit_e3_controller_slurm.sh`
  - submits the controller with `sbatch`;
  - defaults to one CPU, 4,000 MiB and a three-day controller allocation;
  - supports separate controller and scientific-job account, partition, memory and runtime
    controls;
  - records `workflow_control/controller.slurm.tsv` atomically;
  - reports current state through `squeue` and completed state through `sacct`;
  - serialises submission with `controller_submission.lock`; and
  - rejects a second pending or running controller for the same run.
- `scripts/slurm_e3_controller_job.sh`
  - runs through an explicit Conda executable and named environment;
  - reports the resolved Python and workflow version;
  - holds the existing per-run `controller.lock`;
  - invokes the standard runner with the Slurm profile; and
  - preserves the normal exit status in Slurm accounting.

### Retained

- `run_e3_end_to_end.sh --profile local` remains the complete non-Slurm path.
- `submit_e3_end_to_end.sh` remains a legacy detached login-node option for sites that explicitly
  permit it.
- Stage manifests, controlled reruns, atomic publication, failed-stage retention and all
  scientific output contracts are unchanged from v0.7.6.

### Documentation and repository integration

- The repository root now has `run_e3_pipeline.sh`, with `slurm`, `local` and legacy
  `login-detached` modes.
- The repository root README now documents every package, whole-pipeline configuration, expected
  directory organisation, expression-data reuse, a new-dataset procedure, monitoring and package
  quick starts.
- A visually validated A4 operator-guide PDF is provided at
  `docs/E3_PROJECT_OPERATOR_GUIDE_v0_8_0.pdf`.
- The fresh-production template no longer proposes stage walltimes above Dundee's 72-hour maximum.

### Scientific impact

This is an orchestration and operations release. It does not change candidate evidence,
OrthoFinder interpretation, domain mapping, expression mapping, ranking equations, ligandability,
pocket conservation or structural-alignment methods.

### Upgrade

Install the updated package:

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft/e3_end_to_end_workflow
conda activate e3_end_to_end_workflow
python -m pip install --no-deps --editable .
./run_tests.sh
```

Submit from the repository root:

```bash
cd ..
./run_e3_pipeline.sh \
    --mode slurm \
    --config e3_end_to_end_workflow/config/my_immutable_run.yaml \
    --max-jobs 4 \
    --account barton \
    --partition general \
    --resume
```

## v0.7.6

<!-- source: RELEASE_NOTES_v0_7_6.md; sha256: ba10c756b60131e689c59a12c3ca3efb67e80eb3c66693acd87c4a3015553d42 -->

This patch corrects downstream orthology-table resolution after the v0.7.5 component-publication
fix.

### Root cause

The independently restartable orthology component intentionally retains internal stage products
for provenance. After v0.7.5 materialised the six portable files at the master stage-05 contract,
the completed stage therefore contained multiple same-named Parquet files:

```text
orthology/tables/
orthology/stages/03_map_candidates/tables/
orthology/stages/05_publish_portable_outputs/tables/
```

The domains, expression, prioritisation and final-integration adapters recursively searched the
whole stage directory and incorrectly required exactly one matching basename. The scientific
files were not ambiguous: only the public master-stage contract is authoritative downstream.

### Correction

- Resolves orthology tables only at the supported public contracts:
  `orthology/tables/<name>` or `tables/<name>`.
- Ignores component-internal `orthology/stages/...` provenance copies.
- Still fails closed if zero or two public contract files exist.
- Applies the same resolver to stages 06, 07, 08 and 10.
- Adds a regression with three same-named orthology Parquet files.

### Safe continuation

Completed stages, including stage 05, remain valid. Install v0.7.6 and resume the same run without
deleting its run directory. Snakemake will rerun failed downstream stages and retain completed
ones whose configuration and input checks remain valid.

## v0.7.5

<!-- source: RELEASE_NOTES_v0_7_5.md; sha256: d2d5fcc63c2bdb727e5c9093e52f2b67619a78c2a96076e14589f8209149b0ee -->

This patch corrects the stage-05 component-publication mismatch observed on 24 July 2026.

### Root cause

The `e3_orthology_integration` command completed all six of its internal stages and published its
portable products below:

```text
orthology/stages/05_publish_portable_outputs/{tables,qc,provenance}
```

The master workflow correctly retained that nested component run for provenance, but validated its
stable stage-05 contract below:

```text
orthology/{tables,qc}
```

The master stage therefore reported six missing outputs even though the component command returned
zero and its scientific validation had completed.

### Correction

- Materialises only the declared portable orthology outputs from the component publication stage
  into the master stage-05 contract.
- Uses hard links where supported and a checksum-verified copy fallback.
- Preserves the complete nested component run, manifests, logs and checksums.
- Fails closed if any component product is absent, empty or declared outside `orthology/`.
- Adds regression tests for successful materialisation and both failure modes.

### Safe continuation

The failed outer stage was retained under the run's `failed/` directory. Stages 00 through 04 are
unchanged and can be reused. After installing v0.7.5, resume the same immutable run through
`05_orthology`; do not rerun OrthoFinder or delete the authoritative `Results_Feb26` archive.

## v0.7.4

<!-- source: RELEASE_NOTES_v0_7_4.md; sha256: 70e0e1290587f5812572206cf033a50ab6d963858d646124e4c8038713714423 -->

This patch fixes the bounded Slurm-launch failure observed on 24 July 2026.

### Root cause

The launcher appended the target produced by `--stop-after` after Snakemake's
`--default-resources` option. That option accepts a variable-length sequence of `NAME=VALUE`
expressions. With no later option to terminate the sequence, Snakemake interpreted the stage
manifest target as a fifth resource expression and raised:

```text
ValueError: dictionary update sequence element #4 has length 1; 2 is required
```

The controller therefore failed before building the DAG or submitting a scientific Slurm job.

### Correction

- Places an explicit workflow target before the variable-length default-resource arguments.
- Retains command-line `--account` and `--partition` overrides for Slurm execution.
- Adds a behavioural regression test that runs the shell wrapper with fake executables and verifies
  the exact bounded-target and resource argument order.
- Keeps the v0.7.3 production stage-00 report correction unchanged.

### Safe continuation

The failed v0.7.3 start did not submit a scientific job. After installing v0.7.4, the same immutable
configuration and run name can be resumed with `--resume --stop-after 05_orthology`.

## v0.7.3

<!-- source: RELEASE_NOTES_v0_7_3.md; sha256: f4a8ddc4de78c8266d99fd3f7b5e88483258af26d93ce0ab94b3a9bc38389c7d -->

This patch fixes the production stage-00 HTML-report failure observed on 23 July 2026.

### Root cause

The controlled-input validator correctly accepted the complete grant-aligned reuse input set, but
the report presenter recognised only the three older labels `proteomes`, `seeds` and `shortlist`.
When the production run supplied `candidate_evidence`, report generation raised
`KeyError: 'candidate_evidence'` after the scientific output had already validated.

### Correction

- Provides explicit report roles for every current production input authority.
- Uses a conservative human-readable fallback for future validated input identifiers.
- Keeps input paths, file sizes and SHA-256 checksums in both stage and consolidated reports.
- Adds a regression test that executes production-mode stage `00_inputs` through HTML publication.
- Adds unit coverage for the complete current reuse label set and an unknown future label.

### Validation

- 124 Python tests passed.
- Enforced branch-aware coverage passed at 90%.
- PEP 8, Google/PEP 257 docstring and Python compilation checks passed.
- Snakemake lint passed.
- The complete 13-stage synthetic workflow, bounded rerun, resume and final no-op dry run passed.

## v0.7.2

<!-- source: RELEASE_NOTES_v0_7_2.md; sha256: 0e0b2d024556bcead50e7d507121da04c16366d873fe908f00f900a31cc81d11 -->

- Adds `tables/e3_candidate_master_results.parquet`, one wide row per candidate
  group for the requested single-file hand-off.
- Retains all one-to-many evidence as normalised DuckDB relations.
- Adds a relation catalogue with app section, row granularity and source
  provenance.
- Extends the stage-11 hand-off with DuckDB and master-Parquet app
  configurations and checksums.
- Makes source-layout tests independent of editable installation by adding
  `src/` to `PYTHONPATH` in `run_tests.sh`.
- Resolves the previous 89%/90% quality-gate failure: all 111 tests pass at 90%
  branch-aware coverage.

## v0.7.1

<!-- source: RELEASE_NOTES_v0_7_1.md; sha256: 58d20e61c4150b3250bfcf44d8f18c102f2f5b9451f4d4c5024d45e25277cbf6 -->

- Extends optional stage `09b_structural_alignment` with separate same-position and conserved-pocket
  conclusions, local residue matching and chemical-group conservation.
- Publishes a self-contained graphical structural report and an offline interactive browser with
  marked pocket residues for every US-align/TM-align comparison.
- Maps pocket residues back to one-based FASTA coordinates only when model label numbering, range
  and amino-acid identity all validate. Unmappable residues remain explicit rather than guessed.
- Adds `pocket_sequence_coordinates.tsv` and typed Parquet to stage 09.
- Carries structural residue correspondences, position status and local conservation summaries into
  the integrated DuckDB and final candidate resource.
- Adds explicit OrthoFinder orthogroup and hierarchical-group identifiers to final candidate
  records.
- Adds a candidate-relevant group-member sequence table with OrthoFinder identifiers, species,
  original protein identifiers, candidate links, sequence length, SHA-256 and full amino-acid
  sequence.
- Preserves backward compatibility: configurations without `09b_structural_alignment` still publish
  an explicit optional skip and complete the downstream workflow.

## v0.7.0

<!-- source: RELEASE_NOTES_v0_7_0.md; sha256: e6707b93426162f1553b0925bb5c20e131475be96055ae3fe6ba785c61b0f7d2 -->

### Reproducible detached cluster execution

- Adds `submit_e3_end_to_end.sh` as the normal one-command cluster entry point.
- Keeps the lightweight Snakemake controller detached on the login node while scientific rules are
  submitted through the Slurm executor.
- Prevents nested controller execution inside a Slurm allocation by default.
- Prevents duplicate controllers for the same run with a persistent `flock` lock and records the
  controller PID, configuration and durable submission log.
- Adds named `--account` and `--partition` overrides while preserving stage-specific resource
  requests from the run YAML.
- Removes embedded Python from the foreground shell. Configuration path and run-root resolution use
  shell operations plus the tested `e3-workflow run-root` command.

### Optional three-dimensional pocket evidence

- Adds optional stage `09b_structural_alignment` without renumbering established stages 10 and 11.
- Integrates the separate `e3_structural_alignment` package, which uses US-align and TM-align global
  superpositions and then compares selected pocket coordinates in the same reference frame.
- Records global TM-scores, RMSD, transform files, pocket-centroid distances, symmetric
  nearest-neighbour overlap and transparent threshold decisions.
- Runs independent reference-to-member alignments concurrently up to the configured stage thread
  allocation.
- Publishes an explicit checksummed `skipped_optional` manifest when the stage is disabled.
- Keeps the existing sequence-aligned pocket-region result distinct from direct 3D pocket
  equivalence.
- Allows 3D evidence to be included in prioritisation only through the explicit
  `analysis.structural_alignment.use_for_prioritisation` switch. It defaults to `false` pending a
  reviewed multi-structure validation run.

### Compatibility and scaling

- Existing v0.6.0 run YAML files remain valid: an absent `09b_structural_alignment` section defaults
  to disabled and optional.
- The reviewed `Results_Feb26` archive remains the sole inherited 60-proteome OrthoFinder authority.
- The five-proteome configuration remains a bounded fresh-OrthoFinder validation and is not
  reclassified as the production panel.
- Future species remain manifest/configuration rows rather than shell-script constants.

## v0.6.0

<!-- source: RELEASE_NOTES_v0_6_0.md; sha256: 1e76b1be6ee08cc21805d03ecb6cfce27466a11d10291e4dc2f9a86bdae2c128 -->

### Scientific workflow completion

- Adds a grant-aligned reviewed-reuse configuration for the existing 7,255-cluster candidate
  authority, 60-proteome OrthoFinder 2.5.5 result, Expression Atlas Parquet and retained
  AlphaFold/FPocket/P2Rank tables.
- Preserves OrthoFinder exactly at version 2.5.5 and validates the inherited result archive before
  downstream use.
- Implements native stages 06 through 11: domain annotations, full-group expression mapping,
  computational pre-structure prioritisation, reused-pocket selection, aligned pocket-region
  conservation, integrated DuckDB/TSV/Parquet/HTML and Python/Shiny hand-off.
- Treats the computational shortlist as a transparent recommendation for human review rather than
  claiming a signed biological approval.

### Domain, expression and missing evidence

- Downloads bounded InterPro protein annotations and Pfam member-database hits for selected group
  members; no local InterProScan, Pfam HMM library or HMMER run is required.
- Stores terminal annotation responses in an atomic persistent cache and supports checksum-bound
  offline cache manifests.
- Distinguishes `SUPPORTED`, `ANNOTATED_NO_CATALOGUED_E3_DOMAIN` and
  `ANNOTATION_UNAVAILABLE` domain evidence.
- Keeps species without a compatible domain or Expression Atlas resource explicitly unavailable;
  missing evidence is excluded from biological-negative denominators and retained in completeness
  fields.
- Maps expression to every selected target-species orthogroup member through audited identifier
  aliases rather than only to the seed accession.

### Reuse and future scaling

- Adds explicit per-stage evidence modes: validate, prepare, reuse, download, derive, generate,
  synthetic and disabled.
- Makes the target and mandatory species panels configuration-driven.
- Recursively inventories nested Hive-partitioned Expression Atlas Parquet resources.
- Supplies a separate future fresh-production template for a larger arbitrary proteome/species
  manifest, with configurable adapter commands and stage resources up to 32 CPUs and 180 GB.
- Adds MAFFT to the shared environment for reproducible pocket-bearing region alignments.

### Validation

- 107 Python tests pass.
- Enforced branch-aware package coverage is 90% after the scientific codebase expansion.
- PEP 8, PEP 257, shell syntax and Snakemake lint pass.
- The concurrent 15-job synthetic DAG passes, including 12 stage reports, aggregate benchmarks,
  the consolidated HTML report, controlled reruns and a final no-op dry run.
- A miniature real scientific integration test passes from domain/expression inputs through final
  DuckDB, HTML and application hand-off.

## v0.5.1

<!-- source: RELEASE_NOTES_v0_5_1.md; sha256: ae0542f126009960ddc5687c11367e34875aaae6aef0a2faeb5da05730ec5873 -->

This production-readiness release enables the first bounded, real five-proteome OrthoFinder run.
It does not change the selected OrthoFinder version or downstream scientific logic.

### Production preparation

- Added a native production implementation for `01_prepared_proteomes`.
- Requires filename-safe, unique species identifiers.
- Validates FASTA structure, non-empty records and unique primary sequence identifiers.
- Copies every selected FASTA into the run's isolated OrthoFinder input directory.
- Verifies copied files against the controlled source SHA-256 values.
- Publishes sequence, residue, byte and checksum statistics in `prepared_proteomes.tsv` and HTML.

### Bounded branches

- Controlled-input validation is now branch-aware.
- Proteomes remain mandatory for every run.
- Known-E3 seed evidence is required when Discovery is enabled.
- A signed shortlist is required only when the human-review gate is enabled.
- An OrthoFinder-only production run therefore cannot be forced to invent a future shortlist.
- Added the immutable `five_proteome_orthofinder_v0_1_0_20260722` cluster configuration.
- Consolidated reports distinguish a complete bounded run from a complete application release and
  list every explicitly skipped stage.
- Successful full runs retry Snakemake incomplete-marker cleanup across bounded filesystem latency.

### Verification

- 83 tests pass.
- Branch-aware coverage remains 95%.
- PEP 8, PEP 257, Python compilation and shell syntax pass.
- OrthoFinder remains pinned exactly at 2.5.5.
- The controlled GitHub `data/` resources are not modified or bundled.

## v0.5.0

<!-- source: RELEASE_NOTES_v0_5_0.md; sha256: 7210ae0897d6240a9b91b67a87f2369b387f0fb4b844397d6d238f12768bf3ea -->

This feature release adds verbose, checksum-bound HTML reporting to the existing orchestration
package. It does not replace component packages or alter the scientific dependency graph.

### Reporting

- Added one self-contained HTML report to every successfully published stage.
- Added a consolidated full-run HTML report after all twelve stages and benchmark aggregation.
- Added explicit purpose, rationale, supported interpretation and scientific limitation text for
  every stage.
- Added exact external argument vectors and an append-only shell-to-Snakemake invocation history.
- Added input paths/checksums, output checksums, validation state, logs and software/run provenance.
- Added embedded SVG charts for per-stage CPU/RSS time series and run-level wall time, CPU time,
  peak stage RSS and output-size comparisons.
- Added bounded, read-only result summaries for TSV, compressed TSV, FASTA, compressed FASTA,
  Parquet, DuckDB, SQLite, JSON and text outputs.
- Added a report manifest and completion TSV, with atomic publication and superseded/failed report
  retention.

### Workflow contract

- Stage reports are generated only after declared outputs validate and are themselves checksummed in
  `stage_manifest.json`.
- The complete report requires all stage reports plus the completed benchmark authority.
- Partial `--stop-after` runs publish reports only for completed stages and never a false full-run
  report.
- Added `reporting.preview_rows`, `reporting.max_table_columns` and
  `reporting.max_chart_items` controls.
- Added DuckDB 1.4–1.x as a package dependency for read-only Parquet and DuckDB inspection.
- Added a full-run-only compatibility cleanup for stale Snakemake 9 multi-output markers; partial,
  failed and interrupted runs never reach the cleanup boundary.
- Preserved OrthoFinder 2.5.5, restart tokens, atomic stage publication, safe concurrency and all
  controlled `data/` assets.

### Verification

- 74 tests pass.
- Branch-aware coverage remains 95%.
- PEP 8, PEP 257, shell syntax and Python compilation pass.
- Snakemake lint passes.
- The 15-job concurrent synthetic DAG passes, including twelve stage reports, benchmark aggregation
  and the complete report.
- Controlled OrthoFinder-to-orthology rerun, downstream resume and final clean dry-run pass.

## v0.4.1

<!-- source: RELEASE_NOTES_v0_4_1.md; sha256: f52be7e0ec11b31bf3f10435de10e2581a5c9fc3075336156c6323830e5737a3 -->

This is a restart-bookkeeping compatibility fix for the existing v0.4.0 workflow.

### Snakemake metadata handling

- Retained `drop-metadata: true` in both the local and Slurm profiles. Successful jobs therefore do
  not leave transient Snakemake metadata, while interrupted jobs remain subject to
  `rerun-incomplete`.
- Removed the redundant post-success `--cleanup-metadata` call. Snakemake 9 returns exit status 1
  when asked to clean records that have already been dropped, which caused the cluster quality run
  to stop after an otherwise successful 14-job synthetic workflow.
- Added a regression test requiring the wrapper to rely on the profile policy and forbidding a
  second metadata-cleanup call.

No scientific-stage code, stage dependencies, benchmark measurements, OrthoFinder settings,
controlled data assets or completed analysis outputs are changed by this release.

## v0.4.0

<!-- source: RELEASE_NOTES_v0_4_0.md; sha256: 92420b00c692cda366df5f0d91169b77e4d5565c25fc99264a3efef0e3c4bae5 -->

This is an in-place provenance, dependency and benchmarking upgrade to the existing master
workflow.

### OrthoFinder execution contract

- Added an exact Bioconda pin for OrthoFinder 2.5.5 to the package Conda environment.
- Retained Snakemake 9 and the Slurm executor plugin in the same self-contained environment.
- Replaced the stage-04 placeholder with the environment-owned `orthofinder` executable.
- Declared version-2 output checks for identifier maps, orthogroups, the root hierarchical grouping
  and the species tree.
- Recorded the project decision that the reviewed OrthoFinder 2.5.5 phylogeny was preferred for
  this dataset. This does not claim that version 2 is generally superior to version 3.

### Resource benchmarking

- Added sampled process-tree CPU, RSS, VMS, process, thread and I/O measurements to every stage.
- Added precise wall-clock and cumulative CPU timings, allocation efficiency, requested-resource
  utilisation and host/scheduler context.
- Added compressed time-series output plus TSV and JSON summaries within every stage directory.
- Added broader runner timings through checksum inventory, alongside the sampled scientific-stage
  scope and optional full Slurm job accounting.
- Added a final aggregation rule with per-stage and whole-workflow TSV summaries.
- Added best-effort Slurm `sacct` enrichment without making accounting availability a scientific
  completion dependency.
- Retained measurements for failed stage attempts under the run's `failed` directory.
- Made checksummed manifests and configuration-bound control tokens the restart authority and added
  post-success cleanup of transient Snakemake metadata to prevent stale incomplete markers.
- Added unit and synthetic end-to-end coverage for monitoring, serialisation and aggregation.

No inherited OrthoFinder outputs, existing run results or version-controlled data resources are
modified by this release.

## v0.3.0

<!-- source: RELEASE_NOTES_v0_3_0.md; sha256: e99dd2eeba31dc3ce439a5d30fdcf9732ad8738075e25c4ad5b5d74e55e79993 -->

This release upgrades the existing master orchestration package; it does not replace or duplicate
the scientific logic in any component package.

### Changes

- The shell entry point remains the user-facing command and always launches the package Snakefile.
- Human-readable plan and stage logs explain what every stage does, why it is required, its
  prerequisites, requested resources and expected outputs.
- External component output is streamed to both the console and persistent stage logs.
- The serial stage chain is replaced by the scientific dependency graph. Discovery Engine, fresh
  OrthoFinder and expression work can run concurrently when resources permit.
- Each stage declares threads, memory and runtime for resource-aware local or Slurm scheduling.
- `--resume`, `--start-at`, `--stop-after`, `--force-stage`, `--threads` and `--max-jobs` are formal
  named shell options.
- Configuration-bound stage tokens provide a controlled rerun mechanism without deleting results.
- Multi-prerequisite manifests are revalidated by size and SHA-256 before downstream joins.
- Unit, synthetic end-to-end, shell syntax, style, documentation and coverage gates are retained.

## v0.2.0

<!-- source: RELEASE_NOTES_v0_2_0.md; sha256: c12a9d64af6068eb6161a125261dbbc3d3eeb221394717ffc1cee069b8888524 -->

This release fixes the initial package quality gates and establishes the controlled known-E3 seed
evidence contract.

### Changes

- Removed all blank lines after function docstrings that triggered `pydocstyle D202`.
- Removed surplus end-of-file blank lines that triggered `pycodestyle W391`.
- Added transparent reading and writing of `.tsv.gz` manifests.
- Added `e3-workflow build-seed-evidence` with named options, deterministic gzip and provenance.
- Added the expanded seed-evidence schema and validation.
- Updated the production template to consume `data/known_e3_seed_evidence.tsv.gz`.
- Added `nodefaults` to prevent the cluster's legacy `R` channel contaminating environment solves.
- Corrected an unreachable test defect exposed after the style gates were repaired.
- Added unit and CLI tests for seed evidence and compressed TSV handling.

The external production-stage adapters remain intentionally unconfigured and continue to fail
closed. This release is suitable for package testing and input preparation, not yet for launching
the genuine full scientific pipeline.
