# ARIA plant E3 Python reporter v0.12.0

## Complete enriched HOG results

The **All results** tab now opens with an enriched one-row-per-root-HOG view
instead of implying that one raw relation contains the complete HOG record. Its
selectable fields begin with HOG ID, canonical pre-structure and post-structure
ranks, human representatives and Arabidopsis representatives. They continue
with membership/species summaries and every original field from the strongest
available HOG-linked ranking relation.

A second enriched member-detail view retains every source
`hierarchical_membership` field with a `member_` prefix and repeats the HOG-level
representatives, rankings and candidate annotations on each member row. It
therefore supports complete, interpretable member exports without constructing
an uncontrolled many-to-many join.

All original DuckDB relations remain selectable for exact source-level audit.
The interface now states explicitly that **Select all fields** means all fields
in the selected enriched view or raw relation.

## Defensive behaviour

The join retains membership-only and ranking-only root HOGs, marks source
availability explicitly, deterministically selects one ranking row per HOG and
reports how many source ranking rows existed. Every query remains column-
validated and row-bounded.

Run the complete release gate before publishing:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any test or style failure blocks release.
