# External tools and pocket inspection

The External links page is available from both Information and Structural
prioritisation. It is a directory of service start pages. Existing EMERALD,
Mol*, AlphaFold DB and Inspector links remain on their original pages, where
the app can supply the selected protein pair or prepare the intended model ZIP.

| Tool | Preparation in the E3 app | What the directory opens |
|---|---|---|
| Protein Imager | Ligandability or 3D structures & pockets; retain the analysed full PDB/mmCIF model and pocket chain/residue IDs | A blank workspace for manual structure loading and residue selection |
| Mol* | 3D alignment or Human & plant 3D alignment; choose the reference/comparison pair for direct accession links | The generic viewer for manual model loading |
| AlphaFold DB | 3D alignment or Human & plant 3D alignment; retain the intended accession and model identity | The database home page |
| EMERALD | 3D alignment or Human & plant 3D alignment; select a pair and use its direct link or exact pair FASTA | The tool start page, without an automatically selected pair |
| AlphaFold 3 Multi-Model Inspector | HOG model comparison; prepare and download the selected-member ZIP | The Inspector, ready for manual ZIP upload |

## Why a directory is appropriate

A directory makes the tools discoverable without duplicating protein/pair/HOG
selection workflows. Its preparation notes explain where context is obtained.
It does not guess a selection from another page or offer an unprepared bundle.
Remote ESMFold/InterProScan jobs still require the workbench's explicit submission
controls; raw API endpoints are not offered as browser shortcuts. The previously
withheld RCSB computed-model pair hand-off is not reintroduced.

## Protein Imager

[Protein Imager](https://3dproteinimaging.com/protein-imager/) supports local
PDB/mmCIF structure loading and residue selections. The action is available on
Ligandability, including when that release has no compatible pocket table, and
on selected structure/pocket reviews in the plant and human/plant routes.

Use the full coordinate model retained for the E3 analysis. Pocket chain and
residue identifiers must refer to that same model. Load it manually in Protein
Imager, select the recorded pocket residues and choose the desired molecular
representation. A portable HTML/C-alpha view does not supply the full atomic
coordinate file. A newer model downloaded by accession may differ from the
model used to generate the recorded pockets.

The app supplies a link and guidance. It does not upload coordinates, transfer
pocket annotations, predict new pockets or import external results. E3 model
evidence, predictions and rankings remain as recorded. The directory and pocket
links work without contacting an external service during app rendering.
