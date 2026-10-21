# Python package

All analysis code is in `protein_pockets`. It has no imports from the E3 codebase.
Package-authored functions accept named arguments, include docstrings and are
covered by the unit/contract tests. Some upstream C-extension APIs inherently
require positional arguments.

| Module | Responsibility |
| --- | --- |
| `models.py` | Immutable input/configuration records and validation |
| `io.py` | Strict FASTA/manifest reading and JSON/TSV I/O |
| `structure.py` | PDB/mmCIF preparation, sequence checking and residue mapping |
| `tools.py` | Executable identity, command logs and process-tree timeouts |
| `parsers.py` | Native outputs, local confidence and prediction overlap |
| `ranking.py` | Explicit within-model ranking and labelled fallback |
| `pipeline.py` | Independent stage execution, status and verified checkpoints |
| `schema.py` | Explicit types, field descriptions and primary keys |
| `excel.py` | Python Excel export following parent-repository conventions |
| `reporting.py` | Matching TSV, DuckDB, Excel and HTML outputs |
| `cli.py` | `protein-pockets run` and `protein-pockets check` |
| `resources/report.html` | Offline table browser with embedded escaped JSON |
