# ARIA plant E3 Shiny reporter v0.13.1

## Human and Arabidopsis HOG representatives

The HOG summary, human-member and complete-member tables in both the
**Human-containing HOGs** and **Plant and human HOGs** tabs now contain:

- `human_hog_representatives`
- `arabidopsis_hog_representatives`

The values are calculated per root-level `N0.HOG…` group and repeated in all
three displayed and downloadable tables. Parsed protein accessions are preferred;
parsed entry names and then raw identifiers are deterministic fallbacks. Multiple
unique representatives are sorted and semicolon-delimited. HOGs without an
Arabidopsis member retain a blank Arabidopsis value.

The tab filter searches both new representative fields. UI guidance defines the
selection and blank-value rules explicitly.

## Validation

The user reported that the complete R suite passed before this additive schema
change. Query integration and filtering assertions now cover multiple human
representatives, one Arabidopsis representative, repeated member-table values and
the intentionally blank absent-lineage value. The complete suite must be rerun:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Any actual test failure blocks release.

