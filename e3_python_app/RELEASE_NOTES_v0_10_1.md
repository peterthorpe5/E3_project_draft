# ARIA plant E3 Python reporter v0.10.1

## Search test hotfix

The batch smart search intentionally returns every matching relation with source
provenance. The accession `Q9SA03` in the representative test resource occurs in
both `aliases.member_accession` and `ranked.candidate_accessions`. The previous
test assumed that the ranked relation would always be the first row, although
the stable relation ordering places `aliases` first.

The test now checks the complete set of valid relation/column matches. Search
logic, matching modes, result ordering and production data are unchanged.

## Human and Arabidopsis HOG representatives

The summary, human-member and complete-member tables in both HOG explorers now
contain:

- `human_hog_representatives`
- `arabidopsis_hog_representatives`

Each value is calculated once per root-level `N0.HOG…` group and repeated on
every table row so it remains present in TSV and Excel downloads. A member's
display identifier uses the parsed protein accession when available, otherwise
the parsed entry name, otherwise the published raw identifier. Multiple unique
representatives are sorted and separated by semicolons. A missing lineage is an
empty string, not a fabricated biological negative.

The local HOG filter searches both new fields.

## Validation

The user's v0.10.0 environment reported 120 passing tests and the one obsolete
row-order assertion fixed here. The edited source and tests compile in the build
workspace and pass whitespace and 100-character line-length checks. The complete
suite must be rerun in the release environment:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

The Plotly/Kaleido `scope.mathjax` messages are dependency deprecation warnings,
not the cause of the failed assertion. Static PDF payload tests remain unchanged.

