# Input example

`manifest.example.tsv` is a template containing real tab separators. Replace the
model paths and FASTA identifiers with your own. It intentionally contains no
invented BRCA1 sequence or biological prediction.

If you are not supplying FASTA, remove `sequence_id` or leave those cells empty.
`chain` can be empty for a single-chain model, an author chain ID, or `all` for
deliberate complex analysis. Relative paths are resolved against the TSV folder.

For a real software smoke test, the installed P2Rank 2.5.1 distribution contains
`test_data/1fbl.pdb`. Use `--confidence none` for this experimental structure;
it is not an AlphaFold or BRCA1 dataset. See [the test guide](../tests/README.md).
