# Controlled workflow data

This directory holds small, version-controlled input resources and their provenance records. These
files are controlled scientific inputs, not generated workflow output.

The production configuration consumes:

```text
known_e3_seed_evidence.tsv.gz
known_e3_seed_evidence.provenance.tsv
```

The repository also retains the older accession resource and its provenance:

```text
known_e3_seeds.tsv.gz
known_e3_seeds.provenance.tsv
```

Create both files with `e3-workflow build-seed-evidence`; do not manually edit the compressed
resource. The older three-column `known_e3_seeds.tsv.gz` may remain temporarily for backwards
compatibility, but it does not preserve the category and GO-related evidence fields.

The evidence archive currently records 43,066 rows in its committed provenance. Package upgrades
must not replace, regenerate or delete any of these four GitHub-tracked files. The builder refuses
to overwrite an existing resource unless `--force` is explicitly supplied, and production runs
stage and checksum the selected authority without modifying it.

Large FASTAs, AlphaFold models, P2Rank installations and database files do not belong here.
