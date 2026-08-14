# ARIA plant E3 Python reporter v0.12.1

## Coverage-gate hotfix

The complete v0.12.0 application suite passed all 133 functional tests, but the
release gate stopped because total branch coverage was 94%, below the required
95% threshold.

This patch adds focused tests for previously untested defensive and fallback
paths in:

- bounded DuckDB candidate, expression and differential-expression queries;
- display formatting, FASTA validation and Plotly PDF renderer failures;
- ranking weight types/ranges, optional 3D status, identifier and recorded-rank
  fallbacks; and
- pasted-search type, term-count, output-limit and empty-summary handling.

No production scientific or application logic changed. The coverage threshold
remains 95% and must not be lowered.

The eight Plotly/Kaleido messages in the predecessor run are third-party
deprecation warnings from Kaleido 0.2.1 compatibility code. They did not fail
the tests or coverage gate. Kaleido remains pinned because this application
uses its self-contained PDF renderer rather than introducing a system-browser
runtime requirement in this test-only patch.

Run the complete release gate before publishing:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any test, style or coverage failure blocks release.
