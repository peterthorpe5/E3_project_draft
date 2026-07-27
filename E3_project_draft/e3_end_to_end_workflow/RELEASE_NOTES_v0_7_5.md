# e3_end_to_end_workflow v0.7.5

This patch corrects the stage-05 component-publication mismatch observed on 24 July 2026.

## Root cause

The `e3_orthology_integration` command completed all six of its internal stages and published its
portable products below:

```text
orthology/stages/05_publish_portable_outputs/{tables,qc,provenance}
```

The master workflow correctly retained that nested component run for provenance, but validated its
stable stage-05 contract below:

```text
orthology/{tables,qc}
```

The master stage therefore reported six missing outputs even though the component command returned
zero and its scientific validation had completed.

## Correction

- Materialises only the declared portable orthology outputs from the component publication stage
  into the master stage-05 contract.
- Uses hard links where supported and a checksum-verified copy fallback.
- Preserves the complete nested component run, manifests, logs and checksums.
- Fails closed if any component product is absent, empty or declared outside `orthology/`.
- Adds regression tests for successful materialisation and both failure modes.

## Safe continuation

The failed outer stage was retained under the run's `failed/` directory. Stages 00 through 04 are
unchanged and can be reused. After installing v0.7.5, resume the same immutable run through
`05_orthology`; do not rerun OrthoFinder or delete the authoritative `Results_Feb26` archive.
