# External tools: choose a HOG and prepare its inputs

## Protein Imager: prepare and download at every entry point

### Recorded pocket inspection (0.21.5)

Preparation includes recorded pocket files when a matching portable review is
configured. Selected plant and human/plant reviews supply their current group.
On External links and Ligandability the app finds exact matching review groups;
for an individual protein it offers its recorded groups explicitly. A protein
without pocket evidence is listed as not recorded, independently of model availability.
If both configured reviews contain the group, select which recorded evidence to use.

The ZIP contains:

- `pockets/*_protein.cif` and `pockets/*_rankN_pocketM.cif`: the matching protein
  and separate pocket residue structures in their original native coordinates.
  Rank one is the primary result; other retained ranks remain sensitivity evidence.
- `pocket_scores.tsv`: recorded pocket number/rank, druggability, mapping and
  available pLDDT fractions, predictor agreement and evidence status.
- `pocket_residues.tsv`: exact recorded chain/residue identifiers, residue names,
  C-alpha coordinates and available pLDDT for each pocket membership.
- `pocket_status.tsv` and `pocket_files.tsv`: original report/model checksums,
  exported representation, missing-coordinate counts and upload file checksums.
- `models/`: the separate current AlphaFold downloads, with their retrieval audit.

Extract the ZIP. In Protein Imager load one `pockets/*_protein.cif` and its
matching pocket files **together, without separately aligning them**. Use the
Structures/Selections controls to choose the pocket structure and colour it,
show sticks or adjust representations. Individual mmCIF downloads are also
available. The TSVs are supplementary inspection/audit data: the website does
not automatically display their scores. Styles/colours are chosen manually.

**Atom-level inspection requires the original model.** A full current AlphaFold
download is eligible only if its SHA-256 exactly matches the model recorded in
the review, and every recorded C-alpha locator, identity and coordinate agrees.
Alternatively expand **Original pocket prediction models for atom-level inspection**
and supply the original `.cif`/`.mmcif` files from the E3 run. These are checked
locally against the recorded checksum. All available original atoms are retained
for the protein; pocket files contain the original atoms of the mapped pocket residues.

**If the original model is unavailable**, `*_CA_only_*` files retain the report's
original C-alpha trace and mapped pocket positions. These are useful for locating
pockets but lack side chains and cannot support atomic-surface or cavity-volume
inspection. Their B factors are zero placeholders; confidence values are preserved
in the residue TSV when present. Do not overlay these files with unchecked current
models from `models/`. The app never transfers historical pockets onto a newer
model by accession or sequence similarity alone.

No cavity spheres/mesh, ligand poses, new predictions, recalculated scores or
automatic `.3dpi` project styling are supplied. A missing mapped pocket keeps its
score record and explicit export count. Without the matching embedded review data,
the UI says that only current protein structures are included; a legacy report
may need regenerating from its recorded run outputs. Changing source/report/member
selection or original models removes old prepared downloads.

### Protein structures and manual upload

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

The `models/` files are current AlphaFold DB downloads and may differ from historical
E3 models. The distinct `pockets/` files and their audited original-model or
`CA_only` representation are described above.

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

The older **Prepared model for Protein Imager** control supplies current structure
files only. Use the dedicated **Prepare Protein Imager data** panel to include
recorded pocket files. No website link transfers files automatically or imports
results into E3. A portable HTML/C-alpha view alone is not a complete atomic model.

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
