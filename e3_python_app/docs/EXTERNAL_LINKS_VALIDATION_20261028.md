# External links and Protein Imager validation — 28 October 2026

App version: **0.21.2**. Base app version: 0.21.1 at repository commit `bdb84f2`.
The preceding LoL-align integration is retained in commit `fda558f`.

## Completed checks

- All **502 app tests passed** through `bash run_tests.sh`.
- Branch-inclusive backend coverage was **96%**, passing the existing 95% gate.
  The numerical coverage configuration excludes the Streamlit entry module;
  application rendering and navigation are exercised with Streamlit AppTest.
- Compilation, PEP 8 (100-character lines), Google docstrings, JavaScript
  terminal-trimming tests and required shell syntax checks passed.
- The 0.21.2 Python wheel and source distribution built successfully.

The new full-app checks visit both directory routes without a selected model
bundle, reject accidental model/confidence preparation, inspect all five tool
URLs and assert that the directory offers no unprepared ZIP download. Pocket
shortcuts are checked both with and without compatible evidence. Existing
plant and human/plant structure reviews retain their pair-action expander and
exact-pair FASTA download while exposing the new Protein Imager link.

The maintained source-page catalogue is checked against actual navigation.
Shared directory routes resolve to one page, with no extra scientific stage.
Existing canonical-accession/pair URL validation remains covered by the
external-action tests. No raw prediction API endpoint or the previously
withheld RCSB computed-model pair hand-off is exposed by this directory.

## Scope and external service

The implementation was checked against the public Protein Imager interface at
https://3dproteinimaging.com/protein-imager/. It supports manual local structure
loading and residue selections. The app action opens that interface and gives
same-model pocket-residue guidance; it does not upload a structure, pre-populate
pocket selections, generate predictions or change recorded E3 results.

Regression tests use local fixtures without contacting external services.
Actual Protein Imager availability and rendering are outside the app's test
boundary. No biological pocket comparison or new 1,972-group campaign was run.

## Test environment and recovery

Python 3.12.14; Streamlit 1.66.1; DuckDB 1.5.6; pandas 2.2.3; PyArrow 25.0.1;
BioPython 1.88; Plotly 6.9.0; pytest 8.4.2; coverage 7.17.0.

Before editing, the previous complete LoL-align package and unmodified app
source were retained separately, with a pre-change Git tag at `fda558f`.
The delivery ZIP includes the complete four-component source snapshot,
individual/combined Git patches, a verified incremental Git bundle, test/build
logs and checksums. GitHub publication and remote-main merging were not performed.
