# Workflow stages

| Stage | What it does | Why it is present |
|---|---|---|
| `00_inputs` | Validates controlled manifests and checksums | Establishes explicit provenance |
| `01_prepared_proteomes` | Creates consistently named proteome inputs | Keeps discovery and OrthoFinder on the same panel |
| `02_discovery` | Builds or reuses E3-seeded sequence clusters | Expands beyond known seeds without declaring all members E3s |
| `03_candidate_evidence` | Publishes reconciled candidate and seed evidence | Creates the stable candidate authority used downstream |
| `04_orthofinder` | Reuses or runs OrthoFinder 2.5.5 | Supplies run-specific orthogroup evidence |
| `05_orthology` | Reconciles candidates with orthogroups and hierarchical groups | Prevents false joins caused by identifier-format differences |
| `06_domains` | Collects Pfam/InterPro evidence | Tests domain plausibility independently of cluster membership |
| `07_expression` | Maps candidate-group members to expression datasets | Adds biological context without treating absence as zero |
| `08_shortlist_gate` | Ranks candidates before structural analysis | Controls expensive structure work transparently |
| `09_ligandability` | Assesses model confidence and predicted pockets | Adds computational pocket evidence |
| `09b_structural_alignment` | Compares pocket position in three dimensions | Tests whether predicted pockets occupy comparable regions |
| `10_integrated_resource` | Joins all evidence and calculates final rankings | Produces one traceable release authority |
| `11_app_ready` | Publishes reporting-app hand-offs | Prevents apps opening an incomplete run |

## Dependencies and parallel branches

Discovery and OrthoFinder branch after prepared proteomes. Domains and expression branch
after orthology. Snakemake may run independent branches concurrently, subject to the
configured job limit and resources.

## Evidence modes

Common modes are:

- `validate` and `prepare` for controlled inputs;
- `reuse` for reviewed existing scientific authorities;
- `generate` for a fresh component run;
- `download` for curated external annotations;
- `derive` for deterministic integration;
- `disabled` only for an optional disabled stage.

Evidence mode is provenance, not decoration. A stage declared `generate` cannot silently
fall back to reuse.

## Atomic publication

Each stage runs in a unique `.staging` directory. Expected outputs are validated before
the directory is published under its final stage name. Failed staging data are retained
for diagnosis and do not masquerade as a completed stage.

The completion manifest binds:

- configuration digest;
- upstream lineage;
- command argv;
- tool registry;
- requested and measured resources;
- output paths, sizes and checksums;
- supported interpretation and limitation.
