# Inputs and mapping

## Accepted routes

- Full pipeline run directory or ZIP: prepared PDBs, residue-map TSV and report
  are imported together. Native tool folders are not mistaken for input models.
- `report.html`: embedded model/pocket tables only. Coordinates must be added
  from the matching models or completed run for 3D analysis.
- `protein_pockets.duckdb`: materialised original pipeline tables, with external
  access disabled during read. Supply the surrounding model files for 3D work.
- AlphaFold model directories/ZIPs: all discovered PDB/mmCIF models are retained;
  JSON/MSA/template files are not treated as structures. Duplicate model IDs
  with different input bytes fail instead of silently replacing a model.
- Complete workbench resource ZIP: restores typed tables and local artifacts.

The bulk uploader accepts several ZIPs in one import. An archive can contain
nested folders; ZIPs inside ZIPs are not expanded. Up to 1,000 models may be
imported. Per-archive extraction bounds are 8 GiB and 100,000 entries. UI upload
size is 2 GiB per file; use server-side CLI import for larger inputs.

## Representative sequences

Supply ungapped protein FASTA, one first-token identifier per record. The app
preserves supplied IDs; do not assume an accession is extracted from a header.
Content matching lets all five model replicates map to one representative.
Identical sequences with distinct supplied IDs require an explicit mapping to
associate a model; they remain distinct sequence records unless you select a
subset for phylogeny.

Optional mapping TSV example:

```text
sample_id	sequence_id	chain	group_id
fold_example_model_0	NP_123456.1	A	protein_01
fold_example_model_1	NP_123456.1	A	protein_01
```

Literal tabs separate fields. `sample_id` must match the complete model filename
stem or imported report ID. An explicit sequence ID must exist in the FASTA.
An exact full match or unique exact fragment is required. Unmatched/ambiguous
records stay visible in model checks; no fuzzy mapping is silently accepted.

## Coordinates

Pockets from the original pipeline refer to its normalised tool residue keys,
for example `A_1686`. The workbench uses the same preparation code to rebuild
these keys from original de novo models. A full pipeline run's prepared PDB and
`residue_map.tsv` are preferred so original author labels are preserved.

Spatial comparisons use tool residue keys. Reference domain ranges use mapped
representative FASTA positions where available; otherwise they use one-based
model sequence positions. The app retains both kinds of numbering and offers a
pocket-to-alignment-column table with author labels and pLDDT.

## Existing alignment and tree

Aligned FASTA must contain exactly the selected records, with equal row lengths
and unchanged ungapped sequences. Newick leaves must match those IDs exactly,
with no duplicate tips. Imported branch/support values retain their supplied
meaning; record the external phylogenetic method with the project.
## Optional HOG/group/source columns in version 1.1

The model mapping TSV accepts `hog_id`, `group_id`, `source_accession`
and `source_url` in addition to exact `sample_id`, `sequence_id` and
chain mapping. Explicit HOG IDs take priority for grouping. Membership is
never inferred from a filename. Source links are used only for manual
navigation and must be HTTP(S) URLs. Local models are reused for Inspector
exports; no AlphaFold Database retrieval is required.

