# Tests and validation

## Unit and output-contract tests

```bash
python -m pip install --editable '.[dev]'
python -m pytest --cov=protein_pockets --cov-report=term-missing
ruff check .
ruff format --check .
bash -n scripts/run_slurm.sh
```

Coverage includes branches, with a 95% enforced minimum. Tests cover input and
threshold validation, PDB/mmCIF author/insertion-code mapping, unique FASTA
fragments, AF3-style atom confidence, alternate locations, native descriptor
parsing, empty predictions, invalid scores, original cavity IDs after rescoring,
conservative unmapped-residue denominators, transparent ranking/fallback,
independent tool failures, resumable state integrity, locks, typed empty DuckDB
tables, Excel formats, HTML escaping and CLI behaviour.

`conftest.py` contains clearly artificial structures and deterministic native
tool-output contracts. These exercise software behaviour rather than producing
biological results. Tests use the real parsers, preparation and exporters, while
emulating only external command execution in most orchestration tests.

## Real external-tool smoke test

The official P2Rank 2.5.1 distribution includes an experimental MMP1 structure,
`test_data/1fbl.pdb`. Set explicit tool and model paths:

```bash
POCKET_TEST_PDB=/path/to/p2rank_2.5.1/test_data/1fbl.pdb \
POCKET_TEST_FPOCKET=/path/to/fpocket \
POCKET_TEST_P2RANK=/path/to/p2rank_2.5.1/prank \
python -m pytest -m external
```

This test runs fpocket, independent P2Rank prediction and P2Rank rescoring, then
checks a complete report and non-empty cavity table. It uses `--confidence none`
for the experimental B fields. It validates command/output compatibility, not
accuracy on BRCA1 or a particular AlphaFold dataset. Without these variables the
external test is explicitly skipped.

For a browsable smoke report outside pytest, prepare a one-row manifest pointing
to that structure and run the ordinary command with `--confidence none`.

No access to Maddy's denbi files is assumed. Her models still need their own first
run and structural review on the server.
