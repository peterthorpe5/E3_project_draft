# Protein Imager preparation validation — 28 October 2026

App version: **0.21.4**. Published baseline:
`3226e69152faca3224e09d74c8a3c1785b036c05` (app 0.21.3).

All **543 app tests passed** through `bash run_tests.sh`. Branch-inclusive backend
coverage was **96%**, passing the existing 95% gate. Compilation, PEP 8 at 100
characters, Google docstrings, JavaScript terminal-display tests and required
shell syntax checks passed. The universal wheel and source distribution built.
Streamlit AppTest exercises the UI; the existing numerical coverage configuration
excludes the Streamlit entry module.

## Verified data preparation

- Both External links routes prepare actual coordinate downloads for the selected
  HOG, without treating a one-row screen preview as the complete member set.
- Ligandability supports an individual canonical accession and a HOG selection.
- Plant and human/plant structure reviews supply their currently displayed group
  and combine model, alignment-member and supplementary member inventories.
- An explicit preparation action creates a HOG ZIP and individual mmCIF files.
  ZIP contents, accession filenames, source URLs, byte counts and SHA-256 values
  are checked against the underlying retrieved model bytes and audit records.
- The upload README explains extracting the ZIP and loading models/*.cif via
  Protein Imager's structural file chooser. Direct mmCIF downloads need no ZIP extraction.
- Coordinate-only retrieval does not fetch PAE. Existing Inspector requests keep
  the default PAE behaviour. Invalid policy values fail before network requests.
- Changing group, source or selected proteins removes earlier ready files.
  Failed retries clear earlier results. Partial results identify unavailable
  proteins; all-missing results offer an audit without claiming to provide models.
- Invalid/local identifiers and empty HOG catalogues produce explicit guidance.
  Opening a page or changing an individual download choice makes no model request.

## Scope and scientific limits

Protein Imager's public interface at https://3dproteinimaging.com/protein-imager/
lists CIF as an accepted structural-file format. The new tests use deterministic
offline metadata and mmCIF fixtures; no real E3 structures are downloaded during
the test suite and no third-party website upload is automated.

The downloads are full current AlphaFold coordinate files in their native
frames. Historical E3 models and recorded superpositions are not reconstructed
from portable C-alpha views. Pocket selections remain manual and require the
model corresponding to the recorded chain/residue identifiers. The update does
not recalculate pockets, change rankings or run a new biological campaign.

## Environment and recovery

Python 3.12.14; Streamlit 1.66.1; DuckDB 1.5.6; pandas 2.2.3; PyArrow 25.0.1;
BioPython 1.88; pytest 8.4.2; coverage 7.17.0.

The prior app 0.21.3 source and download were retained before editing. The
single-update delivery includes a verified incremental Git bundle, wheel,
patch, full check logs and checksums. Packaging validation applies the patch to
the exact baseline and compares the resulting Git tree and wheel module bytes
with the tested source. Existing unrelated workbench changes remain in the base.
