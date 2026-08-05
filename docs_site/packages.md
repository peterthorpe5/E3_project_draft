# Component packages

The master workflow owns orchestration. Each component remains independently testable and
usable.

## `e3_end_to_end_workflow`

Owns Snakemake orchestration, stage contracts, resume logic, integration, benchmarking and
reports.

```bash
cd e3_end_to_end_workflow
conda env create --file environment.yml
conda run --name e3_end_to_end_workflow \
    python -m pip install --no-deps --force-reinstall --editable .
conda run --name e3_end_to_end_workflow \
    e3-workflow diagnose-install \
    --source-root "$(pwd)" \
    --require-source-match
conda run --name e3_end_to_end_workflow ./run_tests.sh
```

The source-root check verifies the release number, imported module and installed console
command. Run it after moving the checkout or replacing an older editable installation.

## `e3_discovery_engine`

Owns reproducible E3-seeded sequence discovery. Cluster membership is similarity evidence,
not proof that every member is an E3 ligase.

```bash
cd e3_discovery_engine
./run_tests.sh
cp config/config.example.production.yaml config/config.production.yaml
./run_workflow.sh config/config.production.yaml 16
```

Dry-run every new production configuration. Use the component's named cluster launcher
for full 1KP+ work.

## `e3_source_to_parquet_seed`

Owns source-preserving Parquet/DuckDB conversion and candidate-evidence publication.

```bash
cd e3_source_to_parquet_seed
./run_tests.sh
./run_e3_candidate_evidence.sh \
    /path/to/e3_discovery_resource.duckdb \
    /path/to/derived_output \
    --conda-env e3_discovery
```

The positional interface shown is retained by that component for compatibility. New
master-workflow adapters should expose named options.

## `e3_orthology_integration`

Owns identifier reconciliation, orthogroup/hierarchical-group membership and
candidate-relevant group-member sequences.

```bash
cd e3_orthology_integration
conda env create --file environment.yml
conda run --name e3_orthology \
    python -m pip install --no-deps --editable .
conda run --name e3_orthology ./run_tests.sh
./run_e3_orthology_integration.sh --help
```

## `expression_downloader`

Owns Expression Atlas discovery, download, partitioned Parquet import and DuckDB views.

```bash
cd expression_downloader
mamba env create --file envs/e3_atlas_duckplyr.yml
conda activate e3_atlas_duckplyr
R CMD INSTALL .
Rscript inst/scripts/08_run_tests.R
./inst/scripts/09_run_python_tests.sh
./inst/scripts/run_python_first_then_r.sh --help
```

The end-to-end reuse stage consumes a validated resource manifest rather than scanning an
uncontrolled directory.

## `e3_ligandability_pipeline`

Owns model-confidence assessment, FPocket/P2Rank predictions and pocket-residue mapping.

```bash
cd e3_ligandability_pipeline
conda env create --file environment.cluster.yml
conda run --name e3_ligandability \
    python -m pip install --editable .
conda run --name e3_ligandability ./run_tests.sh
conda run --name e3_ligandability ./run_coverage.sh
```

Predicted pockets do not prove binding.

## `e3_structural_alignment`

Owns US-align/TM-align superposition, pocket-position comparison and local residue
conservation.

```bash
cd e3_structural_alignment
conda env create --file environment.yml
conda run --name e3_structural_alignment \
    python -m pip install --no-deps --editable .
conda run --name e3_structural_alignment ./run_tests.sh
./run_e3_structural_alignment.sh --help
```

## `e3_structure_guided_chemistry`

Owns the optional open-source residue-pharmacophore, stability/uniqueness and
fragment-compatibility hand-off.

```bash
cd e3_structure_guided_chemistry
conda env create --file environment.yml
conda run --name e3_structure_guided_chemistry \
    python -m pip install --no-deps --editable .
conda run --name e3_structure_guided_chemistry ./run_tests.sh
./scripts/submit_e3_structure_guided_chemistry_slurm.sh --help
```

It uses open-source dependencies only. It does not run or claim FMOPhore,
FrAncestor or AlphaFold3, and it does not report docking, affinity or binding.

## Reporting applications

The Python Streamlit and R Shiny applications are read-only consumers of the integrated
DuckDB, master Parquet or completed run directory.

```bash
./e3_python_app/run_e3_python_app.sh --help
./E3_shiny_app/run_app.sh --help
```

They must not perform new scientific transformations.
