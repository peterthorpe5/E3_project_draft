# E3 orthology integration

`e3_orthology_integration` is the independent, production-facing package that reconciles the
ARIA E3 candidate scaffold with one explicitly identified OrthoFinder run. It does not modify the
completed Discovery Engine, candidate-evidence resource, OrthoFinder result, or inherited SQLite
database.

The default profile targets the authoritative inherited result `Results_Feb26`: OrthoFinder 2.5.5,
60 proteomes, and the Q9SA03 regressions `OG0001686` and `N0.HOG0002084`. Orthogroup labels are
treated as run-specific; they must never be merged across OrthoFinder runs by label alone.

## Scientific contract

The package retains all of the following as separate fields:

- OrthoFinder internal identifiers such as `1_22787`;
- original raw identifiers such as `sp|Q9SA03|FB27_ARATH`;
- controlled parsed accessions such as `Q9SA03`;
- parser and mapping methods;
- species, source row and source file;
- run-specific orthogroup and hierarchical orthogroup identifiers.

An OrthoFinder group may contain orthologues and paralogues. Membership supports evolutionary
comparison but does not by itself prove E3-ligase function.

## Stages

| Stage | Responsibility | Completion rule |
|---|---|---|
| `00_preflight` | Resolve inputs, calculate checksums, validate species | Every declared output exists and has a recorded checksum |
| `01_build_identifier_map` | Parse `SequenceIDs.txt` without discarding raw headers | TSV and Parquet plus ambiguity and summary tables validate |
| `02_build_membership` | Expand orthogroup and root HOG cells | Both membership authorities and summaries validate |
| `03_map_candidates` | Join bare candidate accessions to parsed memberships | Mapping, unmatched, ambiguity and cluster resources validate |
| `04_validate_integration` | Run structural, Q9SA03 and SQLite regressions | Every required check passes |
| `05_publish_portable_outputs` | Publish stable TSV/Parquet/QC/provenance views | All publication checksums match |

Each stage runs in a unique temporary directory. It is moved into its formal location only after
its complete output contract succeeds. A `SUCCESS` file is not trusted by itself: `--resume`
recalculates input and output checksums, checks package/stage versions, and compares the effective
configuration digest. Rerunning a stage moves downstream results to a recoverable `invalidated`
directory. Failed staging data are retained under `failed` for diagnosis.

## Installation

On the cluster:

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft/e3_orthology_integration
conda env create -f environment.yml
conda run -n e3_orthology python -m pip install --no-deps -e .
```

For an existing environment:

```bash
python -m pip install -e '.[dev]'
```

## Default Results_Feb26 run

Inspect the plan first:

```bash
./run_e3_orthology_integration.sh \
    --conda-env e3_orthology \
    --threads 4 \
    --dry-run
```

Run through Slurm using the project defaults:

```bash
./submit_e3_orthology_integration.sh \
    --account barton \
    --partition general \
    --memory 64G \
    --time 24:00:00 \
    --cpus-per-task 4 \
    -- \
    --conda-env e3_orthology \
    --threads 4 \
    --resume
```

The default formal output is:

```text
/home/pthorpe001/data/2026_E3_protac/analysis/e3_orthology_integration/
└── results_feb26_identifier_reconciliation_v0_1_0/
    ├── logs/
    ├── stages/
    ├── failed/
    ├── invalidated/
    └── superseded/
```

The wrapper log and Slurm stdout/stderr are also stored under this run directory. No runtime
results or logs are written inside the Git checkout by default. After submission, the wrapper
prints the job ID, absolute run directory, exact Slurm log paths and an `squeue` monitoring
command. The default walltime is 24 hours; the submitter rejects requests above the Dundee
cluster maximum of 72 hours.

The submitter keeps scheduler and application resources consistent. If `--threads` is omitted,
it is set from `--cpus-per-task`; if both are supplied, their values must match. Before invoking
`sbatch`, the wrapper removes any inherited `SLURM_CPUS_PER_TASK` value from a parent interactive
allocation. The batch job independently verifies that Slurm's value matches the request before
starting Python. This prevents a nine-CPU interactive shell, for example, from being misreported
as the allocation of a child job that requested four CPUs.

Within Python, `--threads` explicitly caps PyArrow's compute and I/O thread pools. The large
identifier and membership expansions remain memory-bounded streaming loops and are primarily
single-process; the option does not claim that every stage will keep every allocated CPU busy.

The submitter passes the preflight-validated absolute runner path into the batch job explicitly.
This is required because Slurm executes a copied batch script under `/var/spool/slurmd`; a batch
script must not try to locate the package relative to its temporary spool path.

From the package directory, the default run can be inspected with:

```bash
ls -lrth \
    ../../analysis/e3_orthology_integration/results_feb26_identifier_reconciliation_v0_1_0
```

The final publication stage contains `tables`, `qc`, and `provenance` directories. TSV is the
human-auditable authority and Parquet is the efficient analytical authority.

For downstream retrieval, `tables/candidate_group_member_sequences.tsv` and the equivalent typed
Parquet contain every member of every candidate-relevant orthogroup or hierarchical orthogroup.
Each row includes the run-scoped group identifier, species, OrthoFinder internal ID, original FASTA
identifier, parsed accession/entry, candidate linkage, sequence length, sequence SHA-256 and full
amino-acid sequence. The table is intentionally candidate-bounded; it does not duplicate every
sequence from unrelated groups in the 60-proteome run.

## A different or expanded run

All inputs are named options. A future run should use a new `--run-name`, a new species manifest,
and a YAML configuration or explicit regression arguments. If the new run is not meant to reproduce
the inherited database, explicitly use `--skip-sqlite-regression`; this choice is retained in
provenance.

```bash
./run_e3_orthology_integration.sh \
    --conda-env e3_orthology \
    --orthofinder-results-dir /data/new_run/Results_Aug01 \
    --results-directory-name Results_Aug01 \
    --candidate-evidence /data/new_candidates.parquet \
    --species-manifest /data/species_manifest_aug01.tsv \
    --expected-species-count 72 \
    --regression-accession Q9SA03 \
    --expected-raw-identifier 'sp|Q9SA03|FB27_ARATH' \
    --expected-orthogroup OG0001234 \
    --expected-hierarchical-orthogroup N0.HOG0001567 \
    --skip-sqlite-regression \
    --output-root /data/e3_orthology_integration \
    --run-name results_aug01_v0_1_0
```

Do not reuse February group labels unless the regression has been independently established for
the new run.

## Restart controls

- `--resume` reuses only checksum-validated successful stages.
- `--start-at STAGE` requires all preceding stages to validate before work starts.
- `--stop-after STAGE` runs a bounded portion of the workflow.
- `--force-stage STAGE` reruns that stage and invalidates later outputs.
- `--dry-run` reports decisions without creating analysis outputs.

Run `./run_e3_orthology_integration.sh --help` for the complete named-option interface.

## Generated files in a checkout

Editable installation and quality checks can create disposable local files. They are ignored by
Git and may be removed when no process is using the checkout:

```text
build/
*.egg-info/
.ruff_cache/
.pytest_cache/
.coverage
__pycache__/
logs/
slurm_logs/
```

The failure tracebacks emitted by `test_scientific_and_structural_failures` and
`test_failed_stage_is_retained_and_not_published` are deliberate negative-path tests. The suite
passes only when the final summary reports `OK` and the quality-gate script exits successfully.

## Tests and quality gates

```bash
./run_tests.sh
```

The test runner executes unit, integration and end-to-end tests, branch coverage, PEP 8 checks,
Google-style docstring checks, Python compilation and shell syntax validation. The package targets
100 characters per normal Python line and at least 95% branch-aware statement coverage.

## Version 0.1.4

This release adds a checksum-bound, candidate-relevant OrthoFinder group-member sequence table and
retains explicit group identifiers with every sequence. The v0.1.3 progress, Slurm CPU and PyArrow
thread controls remain in place. See `RELEASE_NOTES_v0_1_4.md` for the complete change record.
