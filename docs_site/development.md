# Testing and development

## Repository checks

```bash
./run_repository_tests.sh
```

## Master workflow checks

```bash
conda run \
    --name e3_end_to_end_workflow \
    ./e3_end_to_end_workflow/run_tests.sh
```

The master quality gate includes:

- Python unit and end-to-end tests;
- branch-aware coverage;
- PEP 8 and Google-style docstring checks;
- Python compilation;
- shell syntax and whitespace checks;
- version consistency;
- Snakemake lint and synthetic DAG execution when dependencies are present.

## Component checks

Run the component's own tests after changing it. Run the complete master synthetic
regression whenever a component output contract changes.

## Coding standards

- Python uses PEP 8, a 100-character line limit, Google-style docstrings, defensive
  validation and logging.
- User-facing shell entry points use named options.
- Shell entry points contain no embedded Python.
- User-facing tabular text outputs are TSV, not CSV.
- Partial files are staged and published atomically.
- Resume decisions use configuration and input checksums plus validated outputs.
- External command argv is a YAML list, never an interpolated shell string.

## Documentation checks

```bash
python -m pip install --requirement requirements-docs.txt
mkdocs build --strict
```

The strict build must pass before publishing. The generated `site/` directory is a build
artifact and should not be committed.

## Release checklist

1. Update package and launcher versions.
2. Add release notes.
3. Validate every configuration template.
4. Run Python, shell and repository tests.
5. Build the documentation site strictly.
6. Generate and visually inspect the PDF guide.
7. Check archives after unpacking.
8. Record SHA-256 checksums.
9. Test the first real Slurm controller submission on the Dundee cluster.
