# Release validation: 1.2.0

Validated on 23 October 2026 in Python 3.12.14 with Streamlit 1.66.1.

- **115 tests passed**, including five real Chromium viewer/live-app tests.
- Ten app routes render with prepared evidence; browsing mode hides analysis
  submission controls and explicit opt-in restores them.
- Real USalign and TMalign recover a known rigid transform and retain unequal
  independent fit lengths (32 reference versus 24 mobile CA atoms).
- A complete synthetic batch ran both structural tools concurrently, built
  the representative MSA/bootstrap tree, rebuilt DuckDB and published reviews.
- Exact alignment gaps, unmapped pocket residues, hostile identifiers,
  rank-one/top-k separation and same-member-pocket tool agreement are tested.
- The Inspector ZIP contains valid mmCIF coordinates, an exact model-index
  manifest and explicit missing-metric statuses.
- Portable reviews include HTML, numeric formatted Excel, DuckDB, local
  structure/sequence views and a reopenable native project archive.
- Quality tests cover contiguous confidence/PAE regions, short internal loops,
  invalid token mappings, original numbering/input preservation, curated ranges,
  cut/context flags, HOG/source metadata and no rank promotion.
- The complete quality workflow was exercised with explicitly synthetic pocket
  predictor fixtures and both real structural aligners. Real preparation, import,
  FAMSA, tree construction, DuckDB and portable export were used.
- Prepare-only/full-run/resume tests confirm prediction reuse, refusal of changed
  settings/prepared inputs, preserved previous results and numbered review exports.
- New quality app pages, numeric Excel tables and typed DuckDB tables are checked.
- Offline quality-review link audit: all 14 generated HTML pages had valid local targets.
- Ruff passed; all six delivered Bash scripts passed `bash -n`.
- A wheel built and installed independently. Both new viewer templates,
  packaged methods and the private predictor report resource were verified.

Backend/CLI line-and-branch coverage is **86.45%**. UI code and the inherited
private prediction engine are excluded from that denominator; UI routes and
real browser behaviour are checked separately. Machine-readable results are
in `coverage.json` and `test_results.xml`.

The real test binaries reported USalign **20261019** and TMalign **20240303**.
The delivered scientific Conda environment intentionally follows the E3
repository pins: USalign **20241201**, TMalign **20240303**. A Conda solve and
execution of the older pinned USalign build were not performed here. Every
production fit retains its actual executable checksum, reported version,
command, matrix and raw output.

The inherited fpocket/P2Rank runner was not exercised with actual predictor
binaries in this workspace. Its integration tests use clearly labelled synthetic
records, not fabricated biological predictions. The new Conda environment file
was not solved here; the wheel and its resources were built/installed/checked.

No Dundee/de.NBI login session or real BRCA1 coordinate/FASTA files were
available in this development workspace. Slurm submission, installation on
those machines and the real BRCA1 analysis remain deployment steps. The
included BRCA1 example contains the earlier real pocket-report tables only.
Synthetic structures and scores are explicitly labelled and are not BRCA1
results.

The external Inspector link/naming convention follows the E3 source. Generated
mmCIF bundles were parsed locally; the independently maintained external site
was not used for a live upload.

## Reproduce tests

```bash
python -m pip install --editable '.[dev]'
python -m playwright install chromium
POCKET_WORKBENCH_BROWSER_TESTS=1 \
POCKET_WORKBENCH_TEST_USALIGN="$(command -v USalign)" \
POCKET_WORKBENCH_TEST_TMALIGN="$(command -v TMalign)" \
python -m pytest tests -q
ruff check src/pocket_workbench tests --exclude _pipeline
```
