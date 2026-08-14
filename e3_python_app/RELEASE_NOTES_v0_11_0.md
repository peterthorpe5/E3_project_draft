# ARIA plant E3 Python reporter v0.11.0

## Direct pre-structure top-N HOG list

The new **Pre-structure ranked HOGs** tab makes the requested top-200 analysis
set available without configuring the general threshold explorer. It:

- selects one row per root-level `N0.HOG…`;
- orders by `prestructure_evolutionary_group_rank`, falling back only to the
  equivalent authoritative `evolutionary_group_rank` field;
- never substitutes cluster-level `computational_rank`;
- applies no target-species, mandatory-species, domain, expression, pocket,
  druggability or structural gate;
- defaults to 200 rows within the configured application row cap;
- preserves the recorded rank when the visible result is searched; and
- adds available human and Arabidopsis HOG representatives before paired TSV
  and formatted Excel download.

If an older result source lacks both the root-HOG identifier and authoritative
HOG-level pre-structure rank, the tab explains that it is unavailable instead
of constructing a biologically different surrogate ranking.

## Contextual tab help

Every top-level tab now begins with a collapsed **❓ How to use this tab** panel.
The maintained help catalogue provides tab-specific operating guidance,
evidence boundaries and interpretation cautions. Tests require exact coverage
of all current top-level tabs so a future tab cannot silently omit guidance.

## Streamlit runtime compatibility

All deprecated `use_container_width` arguments have been replaced with
`width="stretch"`. The minimum Streamlit version is consequently 1.51. The
final-druggability group selector now obtains its initial value solely from its
keyed Session State entry, avoiding the warning caused by supplying both a
widget default and a Session State value.

## Validation

New focused tests cover rank-source authority, root-HOG filtering, deterministic
deduplication, absence of gate filtering, representative annotation, row-limit
validation, complete help coverage and the two Streamlit warning regressions.
The complete suite must be rerun in the release environment:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any failure blocks release.
