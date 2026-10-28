# Selected-HOG external tools validation — 28 October 2026

App version: **0.21.3**. Exact base: published app 0.21.2 commit
`49ebc1d1142e9e6f971aa8dd8b1bd8dd6f5ea71c`.

All **526 app tests passed** through `bash run_tests.sh`. Branch-inclusive backend
coverage was **96%**, passing the existing 95% gate. Compilation, 100-character
PEP 8 checks, Google docstrings, JavaScript terminal-display tests and required
shell syntax checks passed. The universal wheel and source distribution built.
The numerical coverage configuration excludes the Streamlit entry module;
Streamlit AppTest exercises the application controls directly.

## Selected data and preparation

- Both External links routes expose HOG, protein/pair and model selections.
  Populated Mol*/AlphaFold/EMERALD URLs reflect the current pair roles.
- A preview cap of one row does not truncate the selected HOG's two-member test
  inputs or model request. All HOG choices are collected without a preview cap;
  oversized interactive member groups fail explicitly rather than truncating.
- Exact pair FASTA uses HOG/species/raw-identifier sequence authority. Other
  HOGs, orthogroup rows and non-members cannot substitute sequences. Duplicate
  accession text across species retains distinct exact sequence identities.
- Missing/invalid/conflicting sequences, local accessions, absent membership
  and empty HOG metadata have explicit outcomes. Unsupported links are omitted.
- Explicit model preparation offers the audited Inspector ZIP and an individual
  Protein Imager mmCIF. Extraction verifies the accession's record, unique file,
  size and SHA-256. Invalid ZIPs, duplicate files and audit mismatches fail closed.
- HOG, source and model-selection changes remove prepared downloads. A failed
  retrieval cannot expose an earlier ZIP. Choosing an already prepared model
  makes no additional network request.
- HOG metadata and exact member queries are cached across protein-pair reruns
  and invalidated by the loaded resource identity.
- Existing pair links, FASTA actions, structural reviews and model-bundle page
  remain covered by the complete app suite. Research-job provenance now records
  the executing app version even when editable-install metadata is stale.

The new UI preparation tests use deterministic offline model fixtures and make
no external service requests. They establish selection, provenance and file
hand-off behaviour, not live service availability or biological model validity.
Current AlphaFold DB downloads do not establish identity with historical E3
pocket models. Protein Imager loading and pocket selection remain manual.

## Environment and recovery

Python 3.12.14; Streamlit 1.66.1; DuckDB 1.5.6; pandas 2.2.3; PyArrow 25.0.1;
BioPython 1.88; pytest 8.4.2; coverage 7.17.0.

The prior 0.21.2 package was recovered and retained unchanged before editing.
The update includes one incremental Git patch, a verified recovery bundle,
the app wheel and full check logs. Packaging checks apply the patch to the
exact base, compare the resulting Git tree with the tested source, and verify
that wheel module bytes match that source. No HPC campaign was run or server
deployment performed by these changes.
