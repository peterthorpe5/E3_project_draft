# HTML reporting contract

## Purpose

The workflow reports are review aids bound to validated machine-readable evidence. They explain what
ran, why it ran, what completed, what the declared outputs contain, how much computation was used and
what scientific interpretation is supported. They do not replace stage manifests, benchmark TSVs,
component validation reports or the underlying scientific data.

## Publication lifecycle

For each stage, the runner follows this order:

1. validate every direct upstream stage manifest, output size and SHA-256;
2. run the configured internal implementation or external argument vector;
3. validate every declared non-empty output;
4. stop and publish the process-tree resource monitor;
5. freeze the stage log;
6. inspect declared results using bounded, format-aware readers;
7. generate `report/stage_report.html` inside the temporary stage directory;
8. checksum the report and all other stage files;
9. write `stage_manifest.json`; and
10. atomically rename the temporary directory into the formal stage path.

A failed command, failed output contract or failed report build cannot publish a formal stage. The
temporary attempt and its benchmark evidence are retained under `failed/`.

The consolidated report is a separate final Snakemake rule. It requires all stage manifests, all
stage HTML files, the benchmark manifest and both run-level benchmark TSVs. It is published
atomically under `reports/`. Consequently, a partial run can never be labelled as a complete run.

## Stage report sections

Each stage report includes:

- stage status, purpose and scientific rationale;
- supported interpretation and a stage-specific limitation;
- run name, mode, configuration path/digest and package version;
- direct controlled inputs or prerequisite manifests with byte size and SHA-256;
- implementation type, exact command, working directory, resource request and timestamps;
- links to the stage log and unmodified external-command log when present;
- bounded summaries and previews of declared outputs;
- wall time, CPU time and efficiency, RSS/VMS, I/O, process/thread counts and Slurm context;
- embedded CPU-core and RSS time series; and
- the pre-report output inventory.

The final `stage_manifest.json` also checksums the HTML report itself. The report intentionally does
not list its own checksum inside its rendered pre-report inventory, avoiding a circular document.

## Result inspection

Inspection is conservative and bounded:

| Format | Reported evidence |
|---|---|
| TSV / TSV.GZ | streaming row count, column count/names and bounded preview |
| FASTA / compressed FASTA | sequence/residue counts, length statistics and first identifiers |
| Parquet | read-only row/column counts and bounded preview through DuckDB |
| DuckDB | read-only relation catalogue and bounded base-table row counts |
| SQLite | read-only relation catalogue and bounded base-table row counts |
| JSON | top-level shape/keys and bounded scalar metadata for files up to 10 MiB |
| text/log/Markdown | streaming line count and bounded non-empty preview |
| unrecognised binary | file type, byte size and SHA-256 only |

Malformed or unsupported content produces an explicit inspection warning. It does not invent a zero
count or reinterpret a component's scientific result. Declared output validation remains separate
from report inspection.

## Full-run report

`reports/e3_workflow_summary.html` contains:

- run identity and controlled input checksums;
- every recorded wrapper-to-Snakemake invocation, including dry runs and resumes;
- workflow wall/CPU/memory/I/O/output metrics with interpretation notes;
- embedded comparison charts for wall time, CPU time, peak stage RSS and output size;
- one scientific and computational summary for every configured stage; and
- links to detailed stage reports and manifests.

For a bounded production configuration, this is a complete report for the configured run. It lists
every explicitly skipped stage and marks application-release eligibility as false. A bounded
OrthoFinder analysis is therefore never presented as the completed integrated E3 application
resource.

All CSS and SVG are embedded. The report contains no remote script, font, image or stylesheet. Data
previews are HTML-escaped, and commands are stored as argument vectors before being rendered with
shell quoting.

## Scientific language

The report keeps evidence types distinct. In particular:

- DeepClust membership is sequence-similarity evidence and does not prove every member is an E3;
- OrthoFinder orthogroups and predicted orthologue relationships are run-specific computational
  evidence rather than functional proof;
- domain matches do not establish complete architecture or activity;
- expression supports context and prioritisation, not protein activity; and
- AlphaFold confidence, FPocket and P2Rank pockets do not prove ligand binding.

OrthoFinder remains pinned at exactly 2.5.5 for this project-specific workflow and is reported as
such. The wording does not generalise that version 2 is universally superior to version 3.
