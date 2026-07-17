# Legacy audit and rerun decision

## Decision

All five inherited scripts are preserved unchanged as evidence and replaced by
the version 0.1.0 production workflow.

The inherited structural result tables remain useful for comparison, but they
must be treated as provisional until controlled reproduction establishes which
values are reliable.

The project will **not** rerun AlphaFold, FPocket or P2Rank across the complete
expanded sequence resource. Production structural analysis will be restricted
to a biologically curated primary cluster and two or three backup clusters.

## Inherited files

- `download_models.py`
- `get_pLDDT_scores.py`
- `get_pocket_pLDDT_scores.py`
- `plot_pLDDT_dist.py`
- `run_p2rank_rescore.sh`

Frozen copies and SHA-256 checksums are under `legacy_reference/`.

## Findings

### Model download

The inherited downloader used retries, but did not call `raise_for_status()`,
validate content type or file content, use temporary files, calculate
checksums, or distinguish missing predictions from transient network failure.
An HTTP error body could therefore be stored under a CIF or JSON filename.

The CSV and SQLite input routes also applied different selection rules.

### Model-level pLDDT

The intended rule was implemented correctly as:

```text
fractionPlddtConfident + fractionPlddtVeryHigh >= 0.5
```

This represents at least half of residues at pLDDT 70 or above. However,
metadata rows were appended to SQLite without a uniqueness contract, API
response handling was incomplete, and the calculation was not independently
checked against the downloaded model.

The replacement calculates pLDDT directly from mmCIF and compares it with API
metadata.

### Pocket-level pLDDT

The inherited script joined pocket residues to model residues using an inner
join. Unmatched residues disappeared from the denominator. A pocket with poor
residue mapping could therefore appear more confident than it was.

The replacement reports every predicted residue as mapped, ambiguous or
unmapped and provides both:

- a mapped-residue confidence fraction; and
- a conservative confidence fraction using all predicted pocket residues as
  the denominator.

### P2Rank/FPocket execution

The inherited shell script contained a malformed variable assignment, a
hard-coded Mac installation path and no defensive shell mode. It did not
record a structured status per accession or verify that the expected output
files existed.

The comments document a version mixture: P2Rank 2.5.1 for the E3 database and
2.5.2-dev.2 for testing Piers' list. The recovered Micromamba environment
pins FPocket 4.2.2. These results must not be presented as one uniform
software run without retaining the P2Rank distinction.

The replacement requires explicit executable/version preflight, uses one
staging directory per accession, persists stdout/stderr, checks required output
files and publishes results atomically.

### Plotting

The inherited plotting script was descriptive rather than a scientific
calculation. It is replaced by structured tables and can be recreated from the
published model-quality table when needed.

## Controlled validation plan

1. Run model-level regression on the inherited testing folder.
2. Select one or two retained models with raw FPocket and P2Rank outputs.
3. Run version 0.1.0 with fixed tool versions.
4. Compare model pLDDT, pocket count, FPocket metrics, P2Rank scores, residue
   mapping and pocket confidence.
5. Document differences by cause rather than forcing equality.
6. Finalise the family/domain/expression shortlist.
7. Run the validated workflow only on curated full-length representatives from
   the selected clusters.

## Interpretation boundary

A predicted pocket, high pLDDT, FPocket score or P2Rank score is computational
evidence. None proves ligand binding, E3 activity, substrate specificity or
PROTAC suitability.
