# External tools: choose a HOG and prepare its inputs

## Protein Imager: prepare and download at every entry point

Use **Prepare Protein Imager data** directly on External links, Ligandability,
3D structures & pockets or the structure/pocket part of Human & plant 3D alignment.
There is no need to navigate to HOG model comparison for these upload files.

- On a selected review, the current group and its published members are supplied
  automatically. Choose the proteins to prepare.
- In Ligandability, choose One protein and enter its canonical UniProt accession,
  or choose HOG members and select the HOG and its proteins.
- Click Prepare Protein Imager data. This contacts AlphaFold Database and obtains
  complete mmCIF coordinate models for the exact selected canonical accessions.
- Download an individual mmCIF to upload directly, or download the HOG ZIP,
  extract it and choose the files under models/ in Protein Imager's structural
  file chooser. The ZIP includes a manifest and an upload README.

The dedicated preparation downloads coordinates only. PAE is unnecessary for
this upload; the existing Inspector preparation retains its normal PAE route.
Missing proteins are recorded in the manifest. An all-missing request produces
an audit download, without claiming to provide uploadable structures.

Files are current AlphaFold DB downloads, not reconstructed C-alpha traces or
guaranteed copies of historical E3 models. For a recorded pocket, use the model
that generated its chain/residue IDs. Pocket highlighting remains manual.

Open **Information → External links** or **Structural prioritisation → External
links**. Both routes open the same working preparation page. Existing links and
controls also remain on their original pages.

## Select the HOG and proteins here

1. Choose **HOG for external tools**. Search by its exact HOG identifier or
   recorded pre/post-structure rank. Choices cover every published root HOG
   with member records in the loaded resource, independently of preview-row limits.
2. Choose the first protein and, when available, a second protein. Labels show
   accessions, species and original identifiers. Unassessed members remain available.
3. Use the populated Mol*/AlphaFold links for a canonical UniProt accession,
   or **Open selected pair in EMERALD** for a supported two-accession pair.
4. Download **selected HOG pair FASTA** when exact source sequences are available.
   Local/isoform/shared accessions use this manual sequence route rather than
   guessing an accession-based URL.

This is an exploratory selection for external follow-up. It does not change the
recorded E3 structural reference or recompute a ranking or pocket prediction.

## Prepare models on this page

Select **HOG members to include in the model ZIP**, then click **Prepare models
for external tools**. This explicit action contacts AlphaFold Database and
retains the existing approved-host, size and model-count checks. Opening the
page or changing a protein does not fetch structures automatically.

After preparation, the page offers:

- The audited **Inspector ZIP**, plus a link to the AlphaFold 3 Multi-Model Inspector.
  Download the ZIP and upload it there manually.
- **Prepared model for Protein Imager**: choose an included accession, download
  its complete mmCIF, then open Protein Imager and load that file manually.
- The retrieval audit, including included/missing accessions, source URLs,
  model checksums and PAE availability.

Models represent different HOG members, not alternative AF3 conformers of one
protein. Absent AF3-specific confidence fields are not zero-valued evidence.
Changing the source, HOG or model selection removes prepared downloads until
the new selection is explicitly prepared. Retrieval failures clear prior bundles.
Pair choices and model-ZIP selections are separate, labelled controls: changing
the exploratory pair does not change the chosen model set.

## Protein Imager and recorded pockets

[Protein Imager](https://3dproteinimaging.com/protein-imager/) accepts manual
PDB/mmCIF loading and residue selections. The new individual model download
supplies a full coordinate file, with its checksum verified against the ZIP audit.

Prepared files are current AlphaFold Database downloads. For inspection of a
recorded E3 pocket, use the same retained model that generated that prediction
and its exact pocket chain/residue identifiers. A current model may differ from
the historical model. The app does not transfer pocket annotations to Protein
Imager or import its results. A portable HTML/C-alpha view is not the complete
atomic coordinate file.

## Missing data and generic start pages

Exact sequences are joined by HOG, species and original member identifier.
Another HOG, orthogroup or species cannot supply a substitute. Conflicting,
invalid and unavailable sequences are labelled explicitly and do not produce
an apparently valid pair FASTA. Missing canonical accessions disable only the
unsupported database/model actions.

The **Tool start pages and preparation notes** expander retains the generic
directory. These links open blank service entry points. If root membership is
absent from a release, the page explains that HOG selection is unavailable and
keeps these manual entry points accessible. The HOG metadata cache is bound to
the loaded source and avoids repeated full-resource queries on widget reruns.

Remote ESMFold/InterProScan jobs retain their explicit workbench submission
controls. Raw API URLs and the previously withheld RCSB computed-model pair
hand-off are not introduced as browser shortcuts.
