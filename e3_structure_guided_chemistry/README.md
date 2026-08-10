# E3 structure-guided chemistry

This package converts validated Stage 08 and Stage 09 E3 authorities into an
auditable, licence-safe computational-chemistry hand-off. Version 0.2.0 removes
automatic top-rank selection: every analysed target must be fixed in an
explicit candidate manifest by evolutionary group, accession, pocket number
and structure checksum.

The open method extracts three-dimensional residue pharmacophore features,
measures between-group feature uniqueness and optionally ranks a user-supplied
open fragment library by rule-of-three and pharmacophore compatibility. It does
not establish binding, affinity, selectivity, E3 activity or PROTAC efficacy.

## Scientific and licence boundary

The executed method is named `open_structure_guided_pharmacophore_v1`.
AlphaFold3, FMOPhore and FrAncestor remain separately reported as `NOT_RUN`:

- AlphaFold3 source code is Apache-2.0, but its model parameters use separate
  non-commercial terms rather than an approved open-source SPDX licence. The
  package therefore consumes existing checksum-bound structures.
- Public GPL-3.0 FMOPhore code is now available, but a complete validated
  licence-compliant apo-target route has not been integrated. No FMO energy or
  FP-score is claimed.
- No verified publicly executable and licensed FrAncestor workflow has been
  integrated. A supplied open fragment table can be ranked only by the
  explicitly named RDKit alternative.

The configuration fails closed if restricted tools or non-approved SPDX
licences are declared. The package itself is MIT, DuckDB is MIT, Gemmi is
MPL-2.0 and optional RDKit screening is BSD-3-Clause. Every run publishes
`COMPONENT_LICENCES.tsv`, `METHOD_STATUS.tsv` and `MILESTONE_COVERAGE.tsv`.

## Candidate panels

Two decision bases are supported and cannot be mixed within one manifest:

| Decision basis | Meaning |
|---|---|
| `EXPANDED_COMPUTATIONAL_SCREEN` | A reproducible broad screen for candidate review; not project-lead approval |
| `PROJECT_LEAD_APPROVED` | A panel explicitly approved for the definitive analysis |

The supplied expanded-panel command considers the Stage 08 top 200, chooses
one quality-first checksum-bound mapped pocket per group and writes both the
included manifest and an exclusion audit. Pocket confidence and mapping
quality are prioritised before druggability. Candidates below a scientific
hand-off threshold remain visible in the result with explicit failure reasons.

## Gates

The v0.2.0 production configuration requires:

- conserved-component fraction at least 0.50;
- mean chemical-group conservation at least 0.50;
- mapped-residue fraction at least 0.80;
- conservative pocket pLDDT fraction at least 0.70; and
- within-panel pharmacophore uniqueness at least 0.10.

`tables/threshold_sensitivity.tsv` and its Parquet counterpart report a
27-combination grid across conservation, pocket-confidence and uniqueness
thresholds. The configured combination is marked explicitly.

## Inputs

- an explicit tab-separated candidate manifest;
- the Stage 08 evolutionary-group ranking;
- Stage 09 selected pockets, pocket-residue mappings, pocket-conservation
  summary and checksum-bound structure asset manifest; and
- optionally, a tab-separated fragment library containing `fragment_id` and
  `smiles`.

## Expanded top-200 cluster run

From the package directory, first prepare the explicit screen manifest:

```bash
RUN_ROOT=/path/to/completed_top200_workflow_run
PANEL_DIR=/path/to/milestone2_candidate_panel_expanded_top200_v0_2_0_20260810

scripts/prepare_expanded_candidate_manifest.sh \
    --run-root "${RUN_ROOT}" \
    --config config/expanded_top200_prepare_only_v0_2_0.yaml \
    --output-dir "${PANEL_DIR}" \
    --maximum-rank 200 \
    --decided-by "Peter Thorpe"
```

Review `candidate_manifest.tsv`, `candidate_manifest_exclusions.tsv` and
`candidate_manifest_provenance.json`. Then submit the immutable panel:

```bash
scripts/submit_e3_structure_guided_chemistry_slurm.sh \
    --run-root "${RUN_ROOT}" \
    --config config/expanded_top200_prepare_only_v0_2_0.yaml \
    --candidate-manifest "${PANEL_DIR}/candidate_manifest.tsv" \
    --output-dir /path/to/milestone2_open_chemistry_expanded_top200_v0_2_0_20260810
```

The launcher defaults to Slurm account and partition `barton`. The production
configuration requires a clean tracked package checkout. The exact Git commit
and tracked package-source state are recorded in
`provenance/run_manifest.json`; unrelated untracked files do not make the
package source dirty.

## Direct command

```bash
./run_e3_structure_guided_chemistry.sh \
    --config config/expanded_top200_prepare_only_v0_2_0.yaml \
    --candidate-manifest /path/candidate_manifest.tsv \
    --group-ranking /path/evolutionary_candidate_group_ranking.parquet \
    --selected-pockets /path/selected_pockets.parquet \
    --pocket-residue-mappings /path/reused_pocket_residue_mappings.parquet \
    --pocket-conservation-summary /path/pocket_conservation_summary.parquet \
    --structure-asset-manifest /path/reused_asset_manifest.parquet \
    --output-dir /path/09c_computational_chemistry
```

Set `fragment_screening.mode: open_fragment_screen` and provide an absolute
`fragment_library` path to enable the RDKit screen. `prepare_only` performs the
complete expanded structural/pharmacophore analysis but publishes empty
fragment tables because no fragment library was screened.

## Tests

```bash
bash ./run_tests.sh
```

The release gate includes compilation, PEP 8, Google-style docstrings, shell
syntax, unit and integration tests, and at least 95% branch-aware coverage.
Scientific tabular outputs are TSV and Parquet; no comma-separated scientific
output is created.
