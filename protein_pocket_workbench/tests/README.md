# Tests

From the package root:

```bash
python -m pip install --editable '.[dev]'
python -m pytest --cov=pocket_workbench --cov-report=term-missing
ruff check src tests --exclude _pipeline
bash -n scripts/run_comparisons_slurm.sh
```

Tests use synthetic known-transform models and temporary project directories.
The predictor's private namespace reuses the original separately tested 1.0.0
workflow; app import, worker integration and prediction-report merging are tested
here. Source preparation is exercised with real Gemmi parsing and PDB/mmCIF.

Optional real-browser viewer checks:

```bash
python -m playwright install chromium
POCKET_WORKBENCH_BROWSER_TESTS=1 python -m pytest tests/test_browser.py
```

These launch Chromium, block HTTP requests, initialise each bundled third-party
viewer and operate the 3D visibility/focus/confidence controls. No biological
coordinates or pocket scores are fabricated in a real project: the synthetic
demonstration is labelled explicitly.

For the 1.3.0 visibility/alignment regressions, also run
`POCKET_WORKBENCH_BROWSER_TESTS=1 python -m pytest tests/test_viewer_visibility.py`.
These test local pocket focus, context-only filtering, original/unknown rank
identity, transformed mobile context, model colours, compact range-aware rows,
FASTA versus alignment numbering, selected TSV downloads and FASTA-only selection.
`test_viewer_navigation.py` verifies direct saved-fit navigation and byte-identical
source evidence after browsing; `test_presentation.py` checks missing values,
directional matrices, collision-safe identifiers and strict/alternative plot identity.
# Quality rerun checks

`test_quality_rerun.py` tests confidence/PAE segmentation, retained short loops,
backbone and PAE rejection, exact token reconciliation, cut/context flags, author
numbering, original-input preservation, curated coordinate ranges, derived-sequence
identity, explicit HOG/source metadata, corresponding-region planning, no rank
promotion, typed DuckDB quality tables, legacy compatibility, Slurm argv quoting,
prepare-only/full-run/resume and an end-to-end run through both real aligners.
Third-party pocket predictions in these integration tests are explicitly
synthetic fixtures. The biological data and predictor binaries are not fabricated
or described as having been run.

