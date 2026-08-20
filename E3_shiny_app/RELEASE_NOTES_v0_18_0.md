# ARIA plant E3 Shiny reporter v0.18.0

## Decision-ready complete results

The enriched HOG overview now puts the following evidence near the front of
the selectable column list:

- the recorded 3D pocket-position and 3D alignment statuses;
- separate nullable flags for same-position support and the stricter conserved
  3D pocket result;
- minimum assessed-member druggability and the all-assessed-members gate; and
- structural coverage, TM-score, overlap, centroid-distance, residue-match and
  chemical-group-conservation summaries.

The enriched member table joins a deterministic strict selected-pocket row
where available and exposes its pocket number, druggability, mapping,
confidence, predictor agreement and evidence status. Missing joined evidence
is labelled unassessed rather than converted to a zero score. Same-position
support is explicitly not presented as proof of conserved pocket chemistry.

Human, Arabidopsis, rice and barley representatives, identifiers and member
counts are now separated throughout the HOG and threshold reporting views.

## Search, expression and heatmaps

- Unified-search matches provide first-18, select-all and clear controls. The
  table and TSV/Excel downloads use exactly the selected fields.
- Expression filtering accepts one identifier or up to 50 unique values pasted
  with semicolon, comma, tab or newline separators. The filtered values can be
  downloaded directly as TSV or Excel.
- Expression heatmaps now encode low values as white and high values as red.

## Seed-catalogue portability repair

Seed metadata JSON is decoded defensively in R after collection, avoiding
DuckDB's optional JSON extension and its network-dependent autoload path.
Pasted seed terms are split consistently on semicolons, commas, tabs and new
lines. `jsonlite` is now an explicit runtime dependency.

## Scientific-method annotation retained

The v0.17.0 threshold and method annotations remain unchanged, including the
Xu and Zhang (2010) reference for TM-score 0.50 as an established approximate
fold/topology boundary. The annotation continues to state that this global
fold threshold does not by itself establish pocket equivalence.

No scientific pipeline output, stored threshold or authoritative ranking is
rewritten by this reporter release.

## Release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```
