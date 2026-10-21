# Origin and relationship to the E3 workflow

This independent package was prepared against
`peterthorpe5/E3_project_draft`, main commit
`c9bc827a18c1280be3ac64d4e8c38c6176e41e61`.

Reference components reviewed:

- `e3_ligandability_pipeline`: explicit P2Rank/fpocket versions, rescoring profile,
  staged tool execution, pocket descriptors, conservative residue confidence and
  retained provenance.
- `e3_end_to_end_workflow/src/e3workflow/excel_reporting.py`: Python/openpyxl
  reporting conventions, numeric types, dark headers, filtered tables and frozen
  identifiers.
- `e3_structural_alignment/src/e3structalign/review_reporting.py`: self-contained
  HTML reporting and separation of measured evidence from its interpretation.

The standalone implementation uses those reporting/method principles without
importing the E3 packages. It deliberately accepts local PDB and mmCIF models,
arbitrary safe model IDs, optional FASTA and explicit author-chain selections.
It needs no accession lookup, model download, E3 family evidence, HOG database,
expression data, structural alignment resource or E3-specific ranking.

The same fpocket output is passed to P2Rank rescoring through the documented
two-column dataset. Independent P2Rank prediction is also retained as a separate
method. The main deliverable is a per-model pocket ranking with clear score and
confidence fields.

This is not a numerical regression of the complete E3 workflow. Preparing a
protein-only PDB, normalising atom/residue records, and adding an independent
prediction route can produce different results from running the E3 package on
another structure file or preparation. The provenance records the actual model,
options, commands and tool identities for each run.

The parent repository is MIT licensed. This standalone folder includes a copy of
that licence. fpocket and P2Rank remain separate upstream software installations;
their binaries/model weights are not redistributed in this package. Scientific
citations are listed in [METHODS](METHODS.md).
