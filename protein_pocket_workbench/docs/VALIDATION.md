# Release validation: 1.3.0

Validated on 28 October 2026 with Python 3.12.14, Streamlit 1.66.1,
Playwright 1.51.0 and Chromium 134 on Linux.

- **135 tests passed; 3 optional real-aligner tests skipped.**
  The current JUnit and coverage records are `test_results.xml` and `coverage.json`.
- Eleven real-browser tests initialise the offline structure, pocket-alignment,
  alignment/tree and live-app views, with HTTP blocked for standalone viewers.
- Pocket visibility tests cover default close-up, selected lining preserved under
  context filters, original/unknown rank identity, transformed mobile context,
  distinct model colours and changed-display-pair warnings.
- Sequence-view tests cover compact range-aware rows, all-replicate mode,
  active legends/counts, FASTA versus MSA numbering, filtered TSV downloads and
  distinct FASTA-only residue selections.
- Presentation tests cover missing/non-finite evidence, zero-valued scores,
  collision-safe labels, directional matrices, and consistent strict/alternative
  overlap and point-colour decisions.
- All ten app routes render against prepared evidence. Group/evidence jumps
  open the selected saved fit. Hashes of every native project file remain
  identical after those browsing operations, including DuckDB and result JSON.
- Existing tests cover quality preparation, synthetic prediction integration,
  exact pocket mappings, rank preservation, typed DuckDB/Excel, export and resume.
- Visual QA inspected the revised single-model and aligned-pair 3D pages,
  pocket-marked alignment, model page, comparison page and input-quality summary
  using explicitly synthetic known-transform models. Internal screenshots are
  not distributed as biological examples.
- Compared against the original 1.2.0 archive, **35 scientific-core, inherited
  prediction, script and environment files are byte-identical**. This includes
  preparation, prediction, fitting, sequence analysis, import, database, batch
  orchestration and all supplied Slurm scripts. Evidence changes add derived
  presentation fields; saved analytical decisions are not recomputed.
- Ruff passed for `src` and `tests`, excluding the inherited private engine.
  All six delivered Bash scripts passed `bash -n`.
- A final wheel built and installed into an independent target. Imports, version,
  packaged methods, all asset checksums and the private prediction report
  resource were verified from that installed wheel.

Backend/CLI line-and-branch coverage is **85.86%**. UI code and the
inherited private engine are excluded from the denominator; route/navigation
and real-browser tests cover UI behaviour separately.

## Limits and compatibility

The real BRCA1 coordinates/native project and an authenticated Dundee/de.NBI
session were unavailable here. No real BRCA1 prediction, cluster submission or
live deployment was performed. The real-aligner tests were skipped because
USalign and TMalign executables were not installed in this development runtime.
The 1.2.0 validation previously exercised those tools; their implementation and
Conda pins are unchanged, but that does not constitute a fresh 1.3.0 binary run.
Actual fpocket/P2Rank executables and a new Conda solve were not exercised here.

The viewer opens existing 1.0–1.2 native resources without rebuilding DuckDB or
rerunning analyses. New plots derive their values from saved matches. Earlier
exported HTML retains its embedded viewer until a fresh `review` export is made.
A review export regenerates presentation from saved evidence, not the analyses.

The software-version change can alter workflow/cache fingerprints even though
scientific implementations are unchanged. Keep an active/resumable 1.2.0 HPC
workflow on its existing software and environment. Install the viewer update
separately on the viewing machine and open completed copied resources.

## Reproduce

```bash
python -m pip install --editable '.[dev]'
python -m playwright install chromium
POCKET_WORKBENCH_BROWSER_TESTS=1 python -m pytest tests -q
ruff check src/pocket_workbench tests --exclude _pipeline
```

To include optional real-aligner tests, set
`POCKET_WORKBENCH_TEST_USALIGN=/absolute/path/to/USalign` and
`POCKET_WORKBENCH_TEST_TMALIGN=/absolute/path/to/TMalign` before running pytest.
The supplied scientific environments follow the E3 pins: USalign 20241201 and
TMalign 20240303. Every production fit records the executable identity actually used.
