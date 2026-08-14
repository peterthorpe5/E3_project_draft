# ARIA E3 app test hotfix handover — 14 August 2026

## Versions

- R Shiny reporter: v0.14.0, unchanged; the user reported its suite passed.
- Python Streamlit reporter: v0.11.1.
- Portable pocket-review producer: v0.4.0, unchanged.

Python v0.11.0 built and installed, then stopped at the `pycodestyle` gate with
four W391 findings. The only v0.11.1 change is removal of redundant blank lines
after the final code line in the four named source/test files. Every corrected
file retains one terminating newline. No ranking, SQL, interface, download,
help text or scientific behaviour changed.

Run the complete Python release gate after installing v0.11.1:

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

The detailed v0.14.0/v0.11.0 feature handover remains applicable. Any test
failure after this style hotfix should be reported with the complete failure
section and traceback.
