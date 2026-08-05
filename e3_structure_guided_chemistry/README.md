# E3 structure-guided chemistry

This package converts the validated Stage 08 and Stage 09 E3 authorities into
an auditable, open-source computational-chemistry hand-off that requires no
commercial or separately negotiated software licence. It selects up to
ten distinct evolutionary candidate groups, resolves their conserved predicted
pockets, extracts three-dimensional residue pharmacophore features, measures
between-group feature uniqueness and optionally ranks a user-supplied open
fragment library by rule-of-three and pharmacophore compatibility.

The package does **not** claim to run FMOPhore, FrAncestor or AlphaFold3.
FMOPhore and FrAncestor are recorded as `NOT_RUN` in every result because a
complete, reproducible, open-source execution route was not available when
this release was prepared. The implemented method is explicitly reported as
`open_structure_guided_pharmacophore_v1`; it is a computational prioritisation
method, not a binding prediction or experimental result.

All runtime components declared by the supplied configuration must use an
approved open-source SPDX licence. A configuration that permits restricted or
commercial components fails before reading scientific inputs.

Open-source software still has legal licence text: this package is MIT,
DuckDB is MIT, Gemmi is MPL-2.0 and the optional RDKit screen is BSD-3-Clause.
Those licences do not require purchasing a seat, institutional entitlement or
negotiating access. The package never invokes Schrödinger, GAMESS, FMOPhore,
FrAncestor or AlphaFold3.

Every run publishes `COMPONENT_LICENCES.tsv` and `METHOD_STATUS.tsv`, so a
reviewer can verify both the open-source component declarations and the
methods that were deliberately not executed.

`MILESTONE_COVERAGE.tsv` maps each grant component to `IMPLEMENTED`, an open
alternative, an existing upstream input, or `NOT_RUN`. In particular:

| Grant component | Package treatment |
|---|---|
| ten candidate groups | top ten distinct Stage 08 evolutionary groups by default |
| evolutionarily stable regions | Stage 09 pocket-conservation gates |
| unique regions | feature chemistry plus rotation-invariant 3D distance signatures |
| AlphaFold3 refinement | not run; consumes existing checksum-bound structures |
| FMOPhore surfaces/pharmacophores | not run; uses selected pockets and an explicitly named open pharmacophore method |
| FrAncestor fragment screen | not run; optional RDKit compatibility ranking is labelled as an open alternative |

## Inputs

- Stage 08 evolutionary-group ranking;
- Stage 09 selected pockets, pocket-residue mappings, pocket-conservation
  summary and checksum-bound structure asset manifest;
- an optional tab-separated fragment library with `fragment_id` and `smiles`.

## Main command

```bash
./run_e3_structure_guided_chemistry.sh \
    --config config/config.example.yaml \
    --group-ranking /path/evolutionary_candidate_group_ranking.parquet \
    --selected-pockets /path/selected_pockets.parquet \
    --pocket-residue-mappings /path/reused_pocket_residue_mappings.parquet \
    --pocket-conservation-summary /path/pocket_conservation_summary.parquet \
    --structure-asset-manifest /path/reused_asset_manifest.parquet \
    --output-dir /path/09c_computational_chemistry
```

Set `fragment_screening.mode: open_fragment_screen` and provide an absolute
`fragment_library` path to enable the RDKit screen. `prepare_only` publishes
the structural and pharmacophore hand-off without a fragment screen.

The end-to-end workflow is the preferred cluster route. For a bounded
standalone rerun after Stages 08 and 09 have completed:

```bash
scripts/submit_e3_structure_guided_chemistry_slurm.sh \
    --run-root /path/completed_workflow_run \
    --config config/config.example.yaml \
    --output-dir /path/new_open_chemistry_result
```

The standalone launcher defaults to Slurm account and partition `barton`.

## Tests

```bash
python -m pytest -q
coverage run --branch -m pytest -q
coverage report --fail-under=90
pycodestyle src tests
pydocstyle src
```

The output is TSV and Parquet; no comma-separated scientific output is
created.
