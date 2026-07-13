# Legacy audit evidence register

## Core inherited code/configuration reviewed

| File | Audit use |
|---|---|
| `legacy_reference/Snakefile.inherited` | Reconstructed inherited workflow stages, DIAMOND parameters, append-mode concatenation, destructive decompression, paths and resource settings. |
| `legacy_reference/config.inherited.json` | Reviewed inherited workflow paths and configuration assumptions. |
| `legacy_reference/samples.inherited.json` | Reviewed sample discovery and identifier assumptions. |
| `legacy_reference/convert_seqs_to_parquet.py` | Assessed FASTA-to-Parquet memory model and metadata retention. |
| `legacy_reference/create_duckdb.py` | Assessed DuckDB table construction and rerun safety. |
| `legacy_reference/generate_config_file.py` | Assessed directory scanning, sidecar handling and sample-name generation. |
| `legacy_reference/retrieve_clusters.py` | Assessed E3 seed matching, representative/member handling and sequence export semantics. |

## Additional inherited evidence considered

The audit also considered the recovered benchmark/time files and project report
statements that described:

- a Snakemake/DIAMOND DeepClust workflow;
- approximate identity 50%, mutual coverage 50% and clustering e-value 0.1;
- approximately two minutes per ten proteomes in the later benchmark series;
- an extrapolated runtime below 36 hours for 10,000 proteomes;
- a 1KP+ run below four hours;
- 6,707 E3-seeded clusters.

These values are historical evidence. They are not embedded as expected values
in production tests because the complete original execution context, input
checksums and repeat structure were not sufficient for a formal regression
contract.

## Evidence classification

- **Direct code evidence:** behaviour visible in recovered source files.
- **Direct output evidence:** counts/timings recovered from output or log files.
- **Report statement:** narrative claim requiring production revalidation.
- **Audit inference:** conclusion supported by code/output but not explicitly
  documented by the inherited author.

## Preservation policy

The legacy files remain separate from production code. Their checksums should be
recorded in the project archive. Any future modification must be made to a copy
and labelled clearly; the recovered originals should remain read-only.
