# Protein Imager recorded pocket export — 28 October 2026

App release: **0.21.5**, incremental from 0.21.4.

## Export contract

The source is the selected indexed portable pocket-review group's embedded
`reviewData` payload. Group ID/type, lead cluster and review rank must agree with
the validated index. Legacy pages without that payload explicitly provide no
pocket source. Duplicate proteins, residue locators, pocket ranks/numbers and
unknown pocket memberships are rejected. The original page SHA-256 binds the
prepared result to its evidence.

The export preserves the recorded pocket scores and residue memberships. All
coordinates are native and retain numbering; no alignment transform or new pocket
prediction is applied. Missing proteins, missing coordinates and retained pockets
without mapped coordinates have explicit audit records/counts.

A model supplies original pocket atoms only when its SHA-256 matches the model
checksum in the report and the entire original C-alpha locator set, residue
identities and native coordinates agree (rounding tolerance 0.00011 Angstrom per
coordinate). A matching current download or optional original mmCIF upload can
supply it. Original input/all-atom files are bounded; each file is at most 100 MiB,
and combined model input/output budgets are bounded to 512 MiB. Existing canonical
accession, remote-host and download limits remain enforced.

An absent original model produces explicitly named `CA_only` protein/pocket
mmCIFs from the original recorded trace. These preserve locations, not side chains
or an atomistic cavity. Their B factors are zero placeholders; recorded pLDDT is
kept in the supplementary residue table. No unchecked current-model overlay is
supplied as a verified pocket structure.

## Verification

- Complete application checks: `bash run_tests.sh`, including compilation,
  PEP 8 style, Google-style docstrings, branch-inclusive backend coverage gate,
  application regressions, JavaScript checks and shell syntax.
- Backend pocket tests verify exact original checksums, current-model eligibility,
  all-atom subset counts, unchanged coordinates, distinct label/author numbering,
  overlapping pocket membership, retained scores/pLDDT, missing models/pockets,
  one-byte newer-model rejection, malformed evidence, indexed source binding,
  ZIP contents/checksums and size limits. Generated mmCIFs are read independently
  with Biopython's coordinate parser.
- Full-application tests exercise all five page routes, canonical one-protein
  selection, automatic review group binding, pocket downloads and explicit
  C-alpha-only messages. Editing report contents invalidates previous files;
  an index/payload group conflict disables preparation.
- The release patch is applied to the exact 0.21.4 base and its resulting full
  Git tree is compared with the tested source. Wheel module bytes and version,
  recovery bundles, ZIP CRC and extracted file checksums are verified.

## Limits

The Protein Imager website accepts manual mmCIF upload and supports selecting
and styling separate loaded structures. The exporter does not generate its
undocumented `.3dpi` project format, choose website colours, or send files to it.
The supplementary TSVs are for inspection/audit and are not imported as website
score panels. Upload in the live website has not been automated or browser-tested;
the independently parsed coordinate files use its documented supported format.

This export contains pocket residue atoms, not fpocket alpha-sphere volumes,
cavity meshes, ligand poses or new evidence of ligand binding. Existing portable
reviews retain only C-alpha coordinates, so original mmCIF files are necessary
for atom-level inspection whenever current AlphaFold bytes differ. The app does
not copy HPC-only files to the user's Mac automatically. Full original PDB inputs
cannot be supplied to the optional mmCIF uploader; they retain the clearly marked
C-alpha route. No scientific scores, rankings, gates or existing run outputs are
rewritten. No new biological prediction or HPC campaign was run.

Official interface and guide checked on 28 October 2026:

- https://3dproteinimaging.com/protein-imager/
- https://3dproteinimaging.com/info/interface/overview.pdf
