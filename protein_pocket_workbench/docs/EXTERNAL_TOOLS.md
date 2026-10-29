# External tools and exact local inputs

Open **External links**, or follow context buttons from model, 3D comparison,
alignment, conservation or HOG/group pages.

1. Choose a supplied HOG/group or all records.
2. Choose one/two protein or model records. Replicates and retained ranges stay
   separate; FASTA-only records are available in the all-records view.
3. Choose **Selected model inputs** for exact retained-region sequences, or
   **Full representative sequences** for the supplied complete FASTA.
4. Download the exact FASTA, PDB/mmCIF or selected-pocket residue TSV.
5. Open the adjacent tool link and load the downloaded file manually.

Use prepared-chain residue labels with that exact coordinate file. Original
author numbers, insertion codes and FASTA positions are separate TSV columns.
Missing mappings remain explicit.

| Tool | Populated link | Local input |
| --- | --- | --- |
| Mol* | Canonical UniProt accession through documented `afdb` parameter | Complete saved PDB/mmCIF |
| AlphaFold Database | Canonical UniProt entry | Separate public database record |
| EMERALD | Two distinct canonical UniProt accessions, in the chosen order | Exact two-record FASTA for local/RefSeq sequences |
| Protein Imager | Start page | PDB/mmCIF plus matching pocket-residue TSV |
| Multi-Model Inspector | Start page | Audited local-model compatibility ZIP |

Database models/sequences may differ from the project's de novo inputs in
coverage, release, conformation or numbering. Links do not embed local files
or replace saved inputs with fresh database downloads.

Accession priority follows E3: explicit `source_accession`, otherwise an exact
canonical `sequence_id`/`sample_id`. Whole values must be supported. RefSeq
IDs, isoform suffixes and accessions embedded in filenames are not rewritten.
Future imports may supply `source_accession` in the mapping TSV. File-based
hand-offs work without UniProt mapping.

Distinct model replicates can have identical sequences. Their FASTA records
retain separate IDs/roles. No public pair link is offered for two equal accessions.

## Model ZIP and coordinate frame

The model-set selector is independent of the exploratory sequence pair.
Use **Use current model pair** or **Select all models in this group** explicitly.
Then choose:

- **Original saved frames:** independent prepared coordinates.
- **A saved alignment:** offered only for its exact two models. The reference
  is first; the second model already has the recorded mobile transform applied.

Click **Prepare models for external tools**, download the ZIP and upload it
manually to Inspector. An individual checksum-verified mmCIF can also be
downloaded from the bundle, including an aligned mobile if that frame was chosen.
Direct model downloads above always use the original saved model frame.

| File | Contents |
| --- | --- |
| `workbench_model_<index>.cif` | Complete prepared atomic model |
| `manifest.tsv` | Model index, original IDs, inclusion status and coordinate SHA-256 |
| `pockets.tsv` | Original pocket IDs/ranks, scores, confidence/context flags |
| `pocket_residues.tsv` | Matching tool labels, author/FASTA labels and unmapped rows |
| `model_inputs.fasta` | Available exact input sequences, including retained regions |
| `sequence_audit.tsv` | Scope, length, hash and missing-input status |
| `handoff.json` | Coordinate frame, optional saved fit and file hashes |
| `saved_comparison.json` | Original result when a saved alignment was chosen |
| `public_links.tsv` | Supported accession links without inferred replacements |
| `HANDOFF.txt` | Loading instructions and interpretation |

Changing source/model set/frame clears the prepared download. A failed repeat
also clears a prior success. Changing only the exploratory sequence pair leaves
the independently selected ZIP model set unchanged.

Missing coordinates are audited; an entirely coordinate-free bundle is refused.
Missing PAE/AF3-specific metrics are unknown, not zero. Different group members
are not automatically alternative AF3 conformers of one sequence.

## Offline sharing

New reviews include `external/index.html` with record/pair selection, populated
links, exact FASTA/model downloads, pocket TSVs, saved-fit files and group ZIPs.
The directory works offline; external websites need internet. External results
do not alter recorded ranks or analyses.

## Reviewed implementation sources

- [E3 External links documentation at commit 3226e69](https://github.com/peterthorpe5/E3_project_draft/blob/3226e69152faca3224e09d74c8a3c1785b036c05/e3_python_app/docs/EXTERNAL_LINKS.md),
  alongside `external_actions.py` and `external_resources.py`.
- [Mol* URL parameters](https://molstar.org/viewer-docs/tips/url-parameters/).
- [EMERALD canonical-accession URL implementation](https://github.com/algbio/emerald-ui/blob/350fe4dcecb186f22f5bd7bdd422bb8918c1ecdf/src/utils/export/urlSharing.ts).
- [Protein Imager file-loading interface](https://3dproteinimaging.com/protein-imager/).

Checked on 28 October 2026. This workbench adapts E3 hand-offs to existing local
de novo models. No user model was uploaded to an external website in validation.
