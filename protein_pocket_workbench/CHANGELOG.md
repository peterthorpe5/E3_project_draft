# 1.2.0 — 23 October 2026

- Added a complete quality-aware batch rerun: contiguous confidence/PAE region
  preparation, fpocket, P2Rank prediction/rescoring, both structural aligners,
  full-representative MSA/tree and portable review publication.
- Added a Maddy Slurm preset writing `results/pockets_quality_regions_v1`
  and a generic named-option worker. The Maddy preset uses partition barton,
  matching the earlier working prediction queue; scheduler overrides remain possible.
- Added exact same-model PAE reconciliation, explicit optional region ranges,
  original author-numbered region CIFs and full retained/rejected/exclusion audits.
- Added artificial-cut/uncertain-context pocket flags, a conservative primary
  screen and corresponding-region comparison planning without rank promotion.
- Added an Input quality page, quality-filtered model browsing, typed DuckDB
  quality tables, numeric Excel audits and offline quality HTML.
- Added checksum-protected resume, separate retry resources/review exports and
  explicit partial-result status. Original full-length inputs/results are preserved.
- Added quality methods, glossary definitions, installation and Slurm documentation.

# 1.1.0 — 23 October 2026

- Added a batch-first Dundee Slurm workflow that reuses existing pocket predictions.
- Added independent global USalign/TMalign fits, bounded parallel workers and
  checksum/settings-based reuse of completed fits.
- Added residue identity/chemical evidence and separate rank-one/top-k,
  same-member-pocket dual-aligner agreement.
- Added a full single-model 3D pocket explorer and expanded saved-fit controls.
- Added pocket-annotated FASTA position tracks and residue highlights with exact
  mapping audits.
- Added HOG/generic group comparison, explicit source links and local-model
  compatibility ZIPs for the external AlphaFold 3 Multi-Model Inspector.
- Added portable review publication with offline HTML, Excel, TSV, DuckDB and
  a reusable native resource archive.
- Replaced deprecated embedding calls with `st.iframe`; requires Streamlit 1.66+.
- Made the app browse prepared results by default; local workers require opt-in.
- Added execution diagnostics, deployment instructions and 68-term glossary.

Existing native schema-1.0 resources remain readable. A new batch build
materialises the expanded DuckDB columns.
