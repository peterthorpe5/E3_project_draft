# Add new data

The workflow is species-count agnostic. A new panel should be introduced through
manifests and a new immutable configuration, not by editing Python source.

## Current fresh-run readiness

The repository-level launcher and DAG are restart-safe, but the checked-in
production template is deliberately not yet a submit-ready new-panel recipe.
`validate-fresh` now rejects every unresolved `CHANGE_ME` marker. Do not replace
an adapter marker with a plausible command merely to make validation pass: the
command must be tested against the stage's exact input and output contract.

| Branch | Current status for a genuinely new panel |
|---|---|
| Input and proteome preparation | Native and tested |
| Discovery | Requires a package-compatible fresh-discovery adapter |
| Candidate-evidence publication | Requires fresh Discovery output to be bound to the standard Parquet contract |
| OrthoFinder | Native external tool contract is defined |
| Orthology reconciliation | Package exists; a stage adapter must bind its nested run layout to the standard Stage 05 paths |
| InterPro domains | Native and tested |
| Expression | Requires a fresh Expression Atlas acquisition/import adapter; legacy manifests are forbidden in strict fresh mode |
| Prioritisation | Native and tested once upstream contracts are present |
| Ligandability and 3D alignment | Native distributed implementations are tested |
| Computational chemistry | Native all-group campaign is integrated in workflow v0.15.0 |
| DuckDB and app hand-off | Native and shared by R Shiny and Python |

Therefore, a successful configuration preflight or Snakemake dry run is not by
itself evidence that the scientific executables can complete a new-panel run.
The release gate must include a bounded real-proteome smoke run through every
adapter before the expanded production submission.

## Recommended layout

```text
analysis_inputs/
├── proteomes/
├── manifests/
│   ├── proteomes.tsv
│   ├── known_e3_seed_evidence.tsv.gz
│   ├── orthology_species.tsv
│   └── shortlist.tsv
├── reusable_resources/
│   ├── expression/
│   ├── domains/
│   └── ligandability/
└── configurations/
    └── species_panel_v0_1_0_20260725.yaml
```

Keep raw inputs outside a package checkout. Keep generated workflow runs under a separate
output root.

## Proteome manifest

Use one row per species with stable identifiers and checksums. Start from:

```text
e3_end_to_end_workflow/config/proteomes.template.tsv
```

Species identifiers must agree across the proteome manifest, orthology manifest,
expression resources and prioritisation settings.

## Seed evidence

Known-E3 seed evidence is controlled and source-backed. Do not add a candidate merely to
make a cluster appear. Build or update the seed resource through the documented
`build-seed-evidence` command and review its provenance.

## Orthology

For a fresh panel, OrthoFinder must see the same prepared proteomes used by discovery.
The approved project version is OrthoFinder 2.5.5. A new result is isolated beneath stage
`04`; it must not overwrite the authoritative February result used by the current
analysis.

The orthology species manifest controls identifier reconciliation. Literal accession
matching alone is not adequate when FASTA headers and candidate identifiers use
different formats.

## Expression

Add species to `expression_downloader/data/species.txt` and prepare a validated
Expression Atlas resource. Missing experiments or failed identifier mapping remain
explicit unavailable states.

The current shared resource may be reused for a normal run. A strict clean-room run uses
an external expression adapter and cannot supply `inputs.expression_manifest`.

## Domains

Prefer curated downloaded InterPro/Pfam annotations. Stage `06` can cache official
InterPro API responses by accession or consume a reviewed download manifest. Missing
annotations are `ANNOTATION_UNAVAILABLE`, not a domain-negative result.

## Ligandability and structures

Provide controlled accession/model inputs and record every structure asset checksum.
FPocket, P2Rank and AlphaFold confidence are predictions. Structural stage `09b` compares
pocket position with US-align/TM-align when compatible structures are available.

## New configuration checklist

1. Copy the closest template to a new dated filename.
2. Set a new `run.name`.
3. Replace manifests and paths.
4. Update `analysis.prioritisation.target_species` and `mandatory_species`.
5. Review every tool version and parameter.
6. Review every stage's resources and evidence mode.
7. Validate manifests and checksums.
8. Run `e3-workflow plan --human`.
9. Run a Slurm dry-run.
10. Start with a bounded smoke run before the full submission.
