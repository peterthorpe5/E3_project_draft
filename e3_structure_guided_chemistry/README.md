# E3 structure-guided chemistry

This package converts validated Stage 08 and Stage 09 E3 authorities into an
auditable, licence-safe computational-chemistry hand-off. Version 0.3.0 can
prepare a panel from every ranked Stage 08 group while retaining explicit
eligibility, selection and exclusion audits. Every analysed target remains
fixed by evolutionary group, accession, pocket number and structure checksum.

The open method extracts three-dimensional residue pharmacophore features,
measures between-group feature uniqueness and optionally ranks a user-supplied
open fragment library by rule-of-three and pharmacophore compatibility. It does
not establish binding, affinity, selectivity, E3 activity or PROTAC efficacy.

## Scientific and licence boundary

The executed method is named `open_structure_guided_pharmacophore_v2`.
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

The supplied full-universe command considers every ranked Stage 08 group, up
to the reviewed configuration safety cap. Mapping, structure availability and
pocket confidence are eligibility floors. Among eligible pockets, the highest
FPocket druggability score is selected, with confidence, mapping, mapped
residue count and stable identity used as deterministic tie-breakers.
Accession/pocket pairs are unique across the panel: an overlapping group
receives its next-best eligible unassigned pocket or an audited exclusion if
none remains. Candidates below a scientific hand-off threshold remain visible
with explicit failure reasons.

`candidate_pocket_selection_audit.tsv` explains the disposition of every
candidate pocket. `candidate_universe_audit.tsv` explains whether every Stage
08 group was included or why it was not. `ranked_member_pocket_evidence.tsv`
retains the broader Stage 09 pocket evidence used during review.

## Gates

The v0.3.0 production configuration requires:

- conserved-component fraction at least 0.50;
- mean chemical-group conservation at least 0.50;
- mapped-residue fraction at least 0.80;
- conservative pocket pLDDT fraction at least 0.70; and
- FPocket druggability score at least 0.50;
- at least 10 mapped pocket residues; and
- within-panel pharmacophore uniqueness at least 0.10.

`tables/threshold_sensitivity.tsv` reports a multidimensional threshold grid
covering conservation, chemical-feature agreement, pLDDT, druggability and
uniqueness. `tables/threshold_sensitivity_one_at_a_time.tsv` varies each of the
seven gates separately around the configured analysis. The configured
combination and the identities of passing groups are explicit.

Each result is also assigned an interpretable review tier. Tier 1 is a stricter
high-confidence subset; Tier 2 passes the configured chemistry hand-off;
remaining tiers distinguish low druggability, small mapped pockets,
chemistry-limited evidence and unsupported cases. These are computational
review categories, not binding or activity claims.

## Inputs

- an explicit tab-separated candidate manifest;
- the Stage 08 evolutionary-group ranking;
- Stage 09 selected pockets, pocket-residue mappings, pocket-conservation
  summary and checksum-bound structure asset manifest; and
- optionally, the complete Stage 09 ranked-member-pocket authority, Stage 09b
  structural-alignment summary and Stage 10 integrated evidence; and
- optionally, a tab-separated fragment library containing `fragment_id` and
  `smiles`.

The output `integrated_candidate_evidence.tsv` preserves source fields with
layer prefixes (`ranking__`, `pocket__`, `conservation__`, `chemistry__`,
`structural__` and `integrated__`). Its field dictionary defines every column,
preventing similarly named measures from silently overwriting one another.

## Full-universe Dundee campaign

The production v0.3.0 route is one restart-safe command:

```bash
scripts/run_dundee_full_universe_v0_3_0.sh
```

The first invocation validates both packages, generates an immutable workflow
configuration and submits structure/pocket generation and 3D alignment for all
1,972 ranked groups. It does not submit chemistry against the earlier top-200
evidence. Re-running the same command reports an active controller without
duplicating it. Once `11_app_ready/stage_manifest.json` records completion, the
same command prepares the all-ranked-groups panel and submits the v0.3.0
chemistry analysis.

The long `4week` quality of service applies only to the restartable Snakemake
controller by default; child scientific jobs remain ordinary Barton jobs. Use
`--without-controller-qos` if the local scheduler does not require it.

## Expanded top-200 cluster run

For the Dundee production project, the complete checked route is one command:

```bash
scripts/run_dundee_expanded_top200_v0_2_1.sh
```

The launcher refreshes the editable installation, validates source and tests
once per Git commit, prepares the panel if needed, and submits only when the
fixed output has neither completed nor already been submitted. Its recorded
defaults reproduce the agreed Stage 08/09 authority, output locations and
Barton Slurm resources. Re-running the command is safe.

For a different installation, first prepare the explicit screen manifest:

```bash
RUN_ROOT=/path/to/completed_top200_workflow_run
PANEL_DIR=/path/to/milestone2_candidate_panel_expanded_top200_v0_2_1_20260811

scripts/prepare_expanded_candidate_manifest.sh \
    --run-root "${RUN_ROOT}" \
    --config config/expanded_top200_prepare_only_v0_2_1.yaml \
    --output-dir "${PANEL_DIR}" \
    --maximum-rank 200 \
    --decided-by "Peter Thorpe"
```

Review `candidate_manifest.tsv`, `candidate_manifest_exclusions.tsv` and
`candidate_manifest_provenance.json`. Then submit the immutable panel:

```bash
scripts/submit_e3_structure_guided_chemistry_slurm.sh \
    --run-root "${RUN_ROOT}" \
    --config config/expanded_top200_prepare_only_v0_2_1.yaml \
    --candidate-manifest "${PANEL_DIR}/candidate_manifest.tsv" \
    --output-dir /path/to/milestone2_open_chemistry_expanded_top200_v0_2_1_20260811
```

The historical launcher defaults to Slurm account and partition `barton`. The production
configuration requires a clean tracked package checkout. The exact Git commit
and tracked package-source state are recorded in
`provenance/run_manifest.json`; unrelated untracked files do not make the
package source dirty.

## Direct command

```bash
./run_e3_structure_guided_chemistry.sh \
    --config config/full_universe_prepare_only_v0_3_0.yaml \
    --candidate-manifest /path/candidate_manifest.tsv \
    --group-ranking /path/evolutionary_candidate_group_ranking.parquet \
    --selected-pockets /path/selected_pockets.parquet \
    --pocket-residue-mappings /path/reused_pocket_residue_mappings.parquet \
    --pocket-conservation-summary /path/pocket_conservation_summary.parquet \
    --structure-asset-manifest /path/reused_asset_manifest.parquet \
    --ranked-pockets /path/ranked_member_pockets.parquet \
    --structural-alignment-summary /path/structural_alignment_summary.parquet \
    --integrated-evidence /path/final_evolutionary_candidate_prioritisation.parquet \
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
