# Final coordinated app release v0.12.1 / v0.9.1

Release components:

- R Shiny reporter: `0.12.1`
- Python Streamlit reporter: `0.9.1`
- Structural-alignment pocket-review generator: unchanged at `0.4.0`

## Final terminology correction

Both Orthology interfaces now present the same scientifically explicit choices:

1. **Root-level phylogenetic HOGs (`N0.HOG…`; recommended)** read from the
   root-level `Phylogenetic_Hierarchical_Orthogroups/N0.tsv` result; and
2. **Original MCL orthogroups (`OG…`; broader legacy view)** read from
   `Orthogroups/Orthogroups.tsv`.

HOG is expanded as hierarchical orthogroup. The visible explanation states that
the recommended `N0` groups reconcile rooted gene trees with the species tree,
whereas the `OG…` groups are retained as the original MCL-based comparison.

This is a presentation-only patch. It does not change the authoritative
OrthoFinder 2.5.5 `Results_Feb26` resource, membership relations, prioritisation,
thresholds, data outputs, workflow configuration or the separate interpretation
of DeepClust sequence neighbourhoods.

## Required release validation

Run the complete Python and R suites before publishing:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh

cd ../E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two R `test_script_utils.R` skips are expected only when the session does
not supply a `--file` argument. Any actual test failure blocks release.
