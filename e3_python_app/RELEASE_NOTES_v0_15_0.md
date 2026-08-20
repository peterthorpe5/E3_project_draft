# ARIA plant E3 Python reporter v0.15.0

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

- Unified-search matches persist while column controls rerun the Streamlit
  page. Users can choose the first 18, all or no fields, and both preview and
  download exactly the selected columns.
- Expression filtering accepts one identifier or up to 50 unique values pasted
  with semicolon, comma, tab or newline separators. The filtered values can be
  downloaded directly as TSV or Excel.
- Expression heatmaps now encode low values as white and high values as red.

## Scientific-method annotation retained

The v0.14.0 threshold and method annotations remain unchanged, including the
Xu and Zhang (2010) reference for TM-score 0.50 as an established approximate
fold/topology boundary. The annotation continues to state that this global
fold threshold does not by itself establish pocket equivalence.

No scientific pipeline output, stored threshold or authoritative ranking is
rewritten by this reporter release.

## Release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```
