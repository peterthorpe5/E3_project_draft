# Coordinated app hotfix v0.11.1 / v0.8.1

This archive supersedes the v0.11.0 / v0.8.0 app archive.

- R Shiny `0.11.1` validates OrthoFinder group-type values before named-vector
  lookup, preventing `subscriptOutOfBoundsError` for unsupported values.
- Python Streamlit `0.8.1` removes the reported PEP8 E203 violation in
  `src/e3app/exports.py`.
- Structural-alignment/pocket-review remains `0.4.0`.

The R suite reported 762 passing assertions before the single resolver error.
The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Re-run both complete app suites after installing this hotfix.
