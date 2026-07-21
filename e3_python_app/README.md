# E3 Python app

This is the Python companion to `E3_shiny_app`. It uses Streamlit for presentation and DuckDB for
read-only, bounded queries. The two applications are intended to consume the same release contract;
scientific transformations belong in the data packages, not in either UI.

Version `0.1.0` provides:

- resource overview with exact row and column counts;
- a generic bounded relation browser;
- exact, case-insensitive accession search over recognised accession columns;
- automatic navigation categories for orthology, ligandability, expression, candidates and
  provenance/QC;
- a named-option launcher and environment-based configuration;
- unit, DuckDB integration and headless Streamlit application tests.

## Install and test

```bash
cd e3_python_app
python -m pip install -e '.[dev]'
./run_tests.sh
```

Streamlit's `AppTest` executes the app directly in the test process, permits simulated input, and
allows rendered elements to be inspected without a browser. Query logic is additionally tested
without Streamlit so failures can be localised to data access or presentation.

## Run

```bash
./run_e3_python_app.sh \
    --resource-duckdb /path/to/e3_integrated_resource.duckdb \
    --expression-duckdb /path/to/e3_expression.duckdb \
    --max-rows 1000 \
    --host 127.0.0.1 \
    --port 8501
```

Validate paths without starting a server:

```bash
./run_e3_python_app.sh \
    --resource-duckdb /path/to/e3_integrated_resource.duckdb \
    --validate-only
```

The app opens the DuckDB read-only, validates every dynamic relation/column identifier against a
strict pattern, binds all user search values as SQL parameters, and caps every preview. It does not
load an entire 25-million-protein resource into Pandas.

## Next biological views

The UI will gain focused candidate, orthology/HOG, expression and pocket-conservation pages as the
shared integrated release schema is finalised. Those pages will call the same tested service layer;
the generic browser remains useful for audit and provenance inspection.

