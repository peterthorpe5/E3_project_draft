# Controlled workflow data

This directory holds small, version-controlled input resources and their provenance records.

The production configuration consumes:

```text
known_e3_seed_evidence.tsv.gz
known_e3_seed_evidence.provenance.tsv
```

Create both files with `e3-workflow build-seed-evidence`; do not manually edit the compressed
resource. The older three-column `known_e3_seeds.tsv.gz` may remain temporarily for backwards
compatibility, but it does not preserve the category and GO-related evidence fields.

Large FASTAs, AlphaFold models, P2Rank installations and database files do not belong here.
