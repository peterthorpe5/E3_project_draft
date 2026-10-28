# E3 structural feature mapping

Reference: `peterthorpe5/E3_project_draft`, including
`e3_structural_alignment` and the structural/HOG pages in `e3_python_app`.
The structural environment and residue-evidence implementation were also read
directly from GitHub main on 23 October 2026.

| E3 capability | Workbench implementation |
| --- | --- |
| USalign and TMalign | Independent batch fits, pinned E3 Conda versions |
| Analysis-derived transforms | Saved matrices applied to all mobile atoms; no cosmetic refitting in the app |
| Raw output and tool provenance | Per-comparison command, logs, matrix, binary checksum and reported version |
| Whole-protein and regional review | Explicit global, confidence-selected and reference-domain scopes |
| Group 3D pocket location | Per-model explorer with all methods and original review ranks |
| Pairwise 3D pocket overlay | Reference/mobile visibility, pocket selection, trace/cartoon, confidence and lining markers |
| Manual terminal-region hiding | Display-only per-model position bounds and pLDDT threshold |
| Pocket-annotated FASTA | Full-position tracks, residue highlights, exact model-to-FASTA-to-MSA audit |
| Sequence/model inventory | Explicit representative IDs, model replicates and missing coordinates |
| Rank-one versus top-k sensitivity | Fixed-reference rank-one audit and separately labelled alternatives |
| Residue/chemical conservation | Mutual-nearest geometry, exact sequence identities and E3 chemical groups |
| Aligner agreement | Both tools must support the same member pocket |
| Structural evidence map | TM-score/overlap plot with a single engine/settings scope |
| HOG model comparison | Explicit HOG/group filtering and local-model compatibility ZIP |
| External source | Same AlphaFold 3 Multi-Model Inspector link as E3; optional explicit source-record links |
| External hand-off | Manual ZIP download/upload, manifest mapping model indices, no automatic submission |
| Sequence/tree exploration | JBrowse MSA with tree, Alignment Viewer 2, seeded NJ bootstrap |
| Portable review | Searchable HTML index, offline 3D/FASTA/tree pages, Excel, TSV and DuckDB |

E3-specific species-coverage gates, expression scores, grant-level rankings and
PROTAC conclusions require evidence absent from a generic pocket project.
They are not invented or silently imported into this app. No HOG membership
is inferred from a file name.

The local Inspector compatibility export contains prepared target chains
converted to mmCIF. It does not retrieve AlphaFold Database models or fabricate
PAE/pTM/ipTM/AF3 summary metrics. The external site is independently maintained;
the exporter follows E3's model-index naming convention, while the offline
workbench remains usable without that external site.
