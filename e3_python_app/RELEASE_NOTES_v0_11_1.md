# ARIA plant E3 Python reporter v0.11.1

## Style-gate hotfix

Version 0.11.0 installed successfully, but the release style gate reported
`W391 blank line at end of file` for four newly added files:

- `src/e3app/prestructure_hogs.py`
- `src/e3app/tab_help.py`
- `tests/test_prestructure_hogs.py`
- `tests/test_tab_help.py`

Version 0.11.1 removes only those redundant terminal blank lines. Each file now
ends with exactly one newline, as required by PEP 8 and `pycodestyle`.

There is no application-logic, query, scientific, interface or test-behaviour
change from v0.11.0. R Shiny v0.14.0 already passed its complete suite and is
unchanged.

## Release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any remaining failure blocks publication.
