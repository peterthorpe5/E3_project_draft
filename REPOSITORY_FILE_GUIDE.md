# E3 project repository file guide

## Purpose and scope

This is the human map of `E3_project_draft`. It explains which package owns each part of the
analysis, which files are entry points, how information moves through the end-to-end workflow and
which retained files are historical rather than authoritative.

Test files are intentionally not listed one by one. Each package's `tests/` directory and test
runner are described as a single unit. Generated caches, old validation captures and compiled
artefacts are also grouped rather than presented as scientific inputs.

The repository is a collection of independent packages joined by `e3_end_to_end_workflow`. The
packages do not write into inherited SQLite, DuckDB or OrthoFinder authorities. New runs use
isolated output directories and checksum-bound manifests.

## Pipeline at a glance

| Order | Package or tool | Main responsibility | Main hand-off |
|---|---|---|---|
| 1 | `e3_discovery_engine` | E3-seeded DIAMOND/DeepClust discovery | discovery DuckDB and cluster evidence |
| 2 | `e3_source_to_parquet_seed` | Candidate-evidence and curated Parquet resources | candidate-evidence Parquet and provenance |
| 3 | OrthoFinder 2.5.5 | Complete-proteome grouping | OrthoFinder result directory/archive |
| 4 | `e3_orthology_integration` | Identifier reconciliation and group membership | orthology Parquet tables and validation |
| 5 | `expression_downloader` | Expression Atlas acquisition/import | expression Parquet resources and DuckDB views |
| 6 | `e3_ligandability_pipeline` | AlphaFold confidence, FPocket, P2Rank and residue mapping | ligandability Parquet tables |
| 7 | `e3_structural_alignment` | Optional US-align/TM-align superposition and 3D pocket comparison | alignment/pocket Parquet tables |
| 8 | `e3_end_to_end_workflow` | Snakemake orchestration, integration, provenance and reports | integrated DuckDB, rankings, HTML and app hand-off |
| 9 | `e3_python_app` / `E3_shiny_app` | Read-only exploration | interactive views of completed resources |

## Normal entry points

| File | Use |
|---|---|
| `e3_end_to_end_workflow/submit_e3_end_to_end.sh` | Normal detached cluster submission. Returns immediately and lets Snakemake submit scientific jobs to Slurm. |
| `e3_end_to_end_workflow/run_e3_end_to_end.sh` | Foreground/local runner and diagnostic entry point. Do not run it inside Slurm unless deliberately overriding the safeguard. |
| `e3_end_to_end_workflow/config/grant_aligned_reuse.cluster.template.yaml` | Starting template for the reviewed-results workflow using the authoritative 60-proteome `Results_Feb26` archive. |
| `e3_end_to_end_workflow/config/production.cluster.template.yaml` | Starting template for a new, larger species/proteome panel. |
| `e3_structural_alignment/run_e3_structural_alignment.sh` | Standalone named-option structural-alignment runner. Normally called by optional end-to-end stage `09b`. |
| `e3_python_app/run_e3_python_app.sh` | Launch the Python/Streamlit viewer. |
| `E3_shiny_app/run_app.sh` | Launch the R Shiny viewer. |

## Repository root

| File | Role |
|---|---|
| `LICENSE` | Repository licence. |
| `E3_MASTER_WORKFLOW_AND_PYTHON_APP_HANDOVER_v0_1_0.md` | Historical handover describing the earlier master-workflow and Python-app state. Use current package READMEs and release notes for present behaviour. |
| `REPOSITORY_FILE_GUIDE.md` | This cross-package map. |
| `.DS_Store` and package-level `.DS_Store` files | macOS metadata accidentally retained in Git. They are not inputs and must never be used as provenance. |

## `e3_end_to_end_workflow`

This is the orchestration authority. It defines the stable stage graph, validates configuration,
launches Snakemake, checks upstream manifests before every stage, publishes stages atomically,
collects resource measurements and creates the integrated release.

### Top-level files

| File or group | Role |
|---|---|
| `README.md` | Primary installation, “how to start”, configuration, restart and cluster-operation guide. |
| `RELEASE_NOTES_v0_2_0.md` through `RELEASE_NOTES_v0_7_1.md` | Versioned history. `v0.7.1` is the current release note. |
| `pyproject.toml` | Python package metadata, version, console entry point and style/coverage settings. |
| `environment.yml` | Reproducible Conda environment, including Snakemake 9 and OrthoFinder 2.5.5. |
| `requirements.txt`, `requirements-dev.txt` | Pip runtime and development dependencies. |
| `submit_e3_end_to_end.sh` | Detached login-node controller launcher with duplicate-run protection and durable logs. |
| `run_e3_end_to_end.sh` | Foreground Snakemake runner; resolves named stage controls and never embeds Python source. |
| `run_tests.sh` | Full Python, shell, style, coverage and Snakemake validation. |
| `.gitignore` | Package-local generated-file exclusions. |
| `TEST_RESULTS_*` | Historical test-output captures; useful as release evidence but not executable inputs. |

### Configuration and controlled data

| File or group | Role |
|---|---|
| `config/grant_aligned_reuse.cluster.template.yaml` | Reviewed-authority template. Structural alignment is present but disabled/optional by default. |
| `config/grant_aligned_reuse.cluster.yaml` | Immutable Q9SA03-limited v0.6.0 run configuration used for the current cluster run. Do not rewrite it into a different analysis. |
| `config/production.cluster.template.yaml` | Arbitrary-size future panel template with explicit component adapter placeholders. |
| `config/five_proteome_orthofinder.cluster.yaml` | Bounded five-proteome fresh-OrthoFinder validation, not the production 60-proteome authority. |
| `config/synthetic.yaml` | Tiny non-production end-to-end configuration. |
| `config/synthetic_proteomes.tsv`, `synthetic_seeds.tsv`, `synthetic_shortlist.tsv` | Synthetic fixtures used by the complete DAG test. |
| `config/proteomes.template.tsv` | Schema/example for a future proteome manifest. |
| `config/known_e3_seed_evidence.template.tsv` | Schema/example for known-E3 seed evidence. |
| `config/shortlist.template.tsv` | Schema/example for an explicit reviewed shortlist where one is supplied. |
| `data/README.md` | Controlled-data description. |
| `data/e3_domain_catalogue.tsv` | Reviewed E3-domain catalogue used to interpret InterPro/Pfam annotations. |
| `data/known_e3_seed_evidence.tsv.gz` and provenance TSV | Compact production seed-evidence derivative and its source record. |
| `data/known_e3_seeds.tsv.gz` and provenance TSV | Earlier seed resource retained for compatibility/provenance. |
| `data_bk/` | Historical duplicate backup of controlled data. It is not the default runtime authority; do not edit it as though it were current. |

### Profiles, workflow and documentation

| File | Role |
|---|---|
| `profiles/local/config.v8+.yaml` | Local Snakemake defaults. |
| `profiles/slurm/config.v8+.yaml` | Slurm executor defaults, retry/latency behaviour and account/partition fallbacks. |
| `workflow/Snakefile` | Top-level DAG. All stage jobs, benchmark aggregation and HTML reporting originate here. |
| `docs/ARCHITECTURE.md` | Stage directories, dependencies, atomic publication, concurrency and extension contract. |
| `docs/EVIDENCE_MODES_AND_SCALING.md` | Reuse/generate/download/derive semantics and larger-panel policy. |
| `docs/BENCHMARKING.md` | Resource measurement and Slurm accounting fields. |
| `docs/REPORTING.md` | Stage and consolidated HTML report contract. |
| `docs/TEST_TRACEABILITY.tsv` | Requirement-to-test traceability. |

### Python modules

| Module | Responsibility |
|---|---|
| `src/e3workflow/__init__.py`, `__main__.py` | Package version and module entry point. |
| `cli.py` | Named subcommands for validation, plans, stage execution, run-root resolution, manifests and reports. |
| `config.py` | Schema validation, stage ordering, dependencies, resources, scientific thresholds and configuration digest. |
| `control.py` | Configuration-bound stage tokens used by resume, force and start-at controls. |
| `runner.py` | Stage execution, subprocess streaming, upstream checksum validation, temporary staging and atomic publication. |
| `manifests.py` | Proteome, seed and shortlist manifest validation. |
| `resources.py` | Expression, domain-cache and ligandability resource-manifest creation/validation. |
| `production.py` | Native reviewed-reuse adapters for discovery, candidates, OrthoFinder, domains and expression. |
| `orthology_groups.py` | Candidate/group membership selection helpers. |
| `domain_annotations.py` | InterPro API/cache retrieval and annotation flattening. |
| `prioritisation.py` | Grant-aligned pre-structure scoring and computational shortlist. |
| `ligandability.py` | Reused pocket selection, sequence-aligned pocket-region conservation and validated pocket-to-FASTA coordinates. |
| `integration.py` | Integrated DuckDB, explicit OrthoFinder IDs/sequences, optional 3D position/conservation joins, HTML and app hand-off. |
| `benchmarking.py` | Process-tree measurements and run-level benchmark aggregation. |
| `reporting.py` | Self-contained stage/run HTML reports and exact invocation provenance. |
| `seed_evidence.py` | Deterministic compact seed-evidence resource builder. |
| `tabular.py` | Typed TSV/Parquet/DuckDB helpers. |
| `io_utils.py` | Checksums, JSON/TSV I/O, inventories and logging. |
| `errors.py` | Controlled workflow exception hierarchy. |
| `tests/` | Unit, integration, synthetic DAG, shell-interface and scientific mini-pipeline tests. Individual test files are omitted here by request. |

## `e3_structural_alignment`

This optional package is the direct 3D evidence layer. It is deliberately independent so the
alignment engine or geometric method can evolve without embedding Python in the master shell.

| File or module | Role |
|---|---|
| `README.md` | Method, inputs, output schema, standalone command and integration instructions. |
| `RELEASE_NOTES_v0_1_0.md`, `RELEASE_NOTES_v0_1_1.md` | Initial alignment release and current graphical/interactive reporting release. |
| `pyproject.toml` | Package/version/CLI and quality settings. |
| `environment.yml` | Independent environment with pinned US-align, TM-align, Biopython and DuckDB. |
| `requirements.txt`, `requirements-dev.txt` | Pip runtime/development dependencies. |
| `run_e3_structural_alignment.sh` | Shell-only named-option wrapper around `e3-structure-align run`. |
| `run_tests.sh` | Coverage, unit, style, docstring and shell validation. |
| `src/e3structalign/__init__.py`, `__main__.py` | Version and module entry point. |
| `src/e3structalign/cli.py` | Defensive named CLI and threshold parsing. |
| `src/e3structalign/pipeline.py` | Input reconciliation, deterministic references, bounded concurrent pair runs, local residue correspondences, group summaries, resume and atomic publication. |
| `src/e3structalign/usalign.py` | Shared US-align/TM-align execution, version capture, output parsing and matrix validation. |
| `src/e3structalign/structure_io.py` | PDB/mmCIF C-alpha parsing, residue lookup, coordinate transforms, pocket geometry and mutual-nearest residue matching. |
| `src/e3structalign/models.py` | Immutable pocket, asset, residue, sequence-coordinate, atom, transform and result objects. |
| `src/e3structalign/reporting.py` | Self-contained scientific HTML summary with SVG graphics and evidence/provenance tables. |
| `src/e3structalign/interactive.py` | Offline rotatable C-alpha/pocket pair viewers and searchable browser index. |
| `src/e3structalign/io_utils.py` | TSV/Parquet/JSON, checksums, manifests, logging and output inventories. |
| `src/e3structalign/errors.py` | Input, tool and workflow exceptions. |
| `tests/` | Unit and end-to-end tests, including fake deterministic structural aligners. |

## `e3_discovery_engine`

This package owns sequence discovery and candidate expansion. DeepClust clusters are sequence
clusters, not OrthoFinder orthogroups.

### Main files and configuration

| File or group | Role |
|---|---|
| `README.md`, `CHANGELOG.md` | User guide and release history. |
| `pyproject.toml`, `requirements*.txt` | Package/dependency definitions. |
| `Snakefile` | Discovery DAG. |
| `run_workflow.sh` | General named workflow wrapper. |
| `run_e3_discovery_engine_full_onekp_cluster.sh` | Main full-panel cluster entry point. |
| `run_tests.sh` | Complete package test/quality runner. |
| `PACKAGE_MANIFEST.tsv` | Package file/checksum register. |
| `config/config.example.production.yaml` | Production configuration example. |
| `config/config.cluster.full_onekp.example.yaml` | Full 1KP cluster example. |
| `config/config.example.legacy_reproduction.yaml` | Explicit inherited-method reproduction configuration. |
| `config/config.five_proteome_*.local.yaml` | Five-proteome principal, no-mask and TANTAN comparisons. |
| `config/samples*.tsv`, `five_proteome_samples.local.tsv` | Sample/proteome manifests. |
| `config/generated_runs/.../benchmark_{10,20,40,60}_proteomes.*` | Frozen scaling-ladder configurations and sample selections. |
| `workflow/envs/production.yml` | Production rule environment. |
| `workflow/envs/legacy_diamond_2_1_23.yml` | Environment retained only for the declared legacy comparison. |
| `dist/*.whl` | Historical built wheel; source plus the current environment remains the development authority. |
| `.coverage`, generated results and validation captures | Non-scientific development artefacts. |

### Scripts and source modules

| File or module | Role |
|---|---|
| `scripts/submit_full_onekp_slurm.sh`, `slurm_full_onekp_job.sh` | Full-panel Slurm submission and job body. |
| `scripts/check_full_onekp_slurm.sh` | Scheduler/output status checks. |
| `scripts/run_e3_scaling_and_full.sh` | Scaling ladder plus full execution. |
| `scripts/run_five_proteome_masking_comparison.sh` | Principal/no-mask/TANTAN comparison. |
| `scripts/run_release_checks.sh` | Release validation. |
| `src/e3_discovery/cli.py` | Named CLI. |
| `config.py`, `cluster_config.py`, `constants.py` | Configuration and fixed schema constants. |
| `pipeline.py` | Stage coordination. |
| `diamond.py`, `clusters.py` | DIAMOND/DeepClust execution and cluster parsing. |
| `fasta.py`, `seeds.py`, `sequence_metadata.py` | Protein/seed preparation and metadata. |
| `manifest.py`, `provenance.py`, `resource.py` | Input/output manifests and release resources. |
| `benchmarks.py`, `resource_monitor.py` | Scaling and resource measurements. |
| `path_safety.py`, `io_utils.py`, `logging_utils.py`, `exceptions.py` | Defensive filesystem, I/O, logging and errors. |
| `docs/` | Methods, data dictionaries/sources, benchmark protocol, runbooks, release/testing standards, legacy limitations and interpretation guidance. |
| `legacy_reference/` | Frozen inherited scripts/configuration for audit only. It is not the production implementation. |
| `tests/` | Unit, integration, command, release and workflow tests. |

## `e3_source_to_parquet_seed`

This package converts inherited/curated sources into reproducible Parquet, candidate-evidence and
DuckDB-view resources.

| File or module | Role |
|---|---|
| `README.md`, `RELEASE_NOTES_v0_4_0.md` | Current user/release documentation. |
| `pyproject.toml`, `requirements.txt` | Package and dependency definition. |
| `run_e3_seed_pipeline.sh` | Seed-source conversion workflow. |
| `run_e3_candidate_evidence.sh` | Candidate-evidence builder. |
| `run_e3_source_to_parquet_seed_full_cluster.sh` | Cluster-scale combined entry point. |
| `run_tests.sh`, `run_coverage.sh` | Test/coverage runners. |
| `scripts/e3_convert_seed_sources.py` | Convert controlled source tables. |
| `scripts/e3_build_candidate_evidence.py` | Build candidate evidence. |
| `scripts/e3_build_curated_resource.py` | Build curated release tables. |
| `scripts/e3_build_manifest.py` | Manifest builder. |
| `scripts/e3_create_duckdb_views.py` | Read-only view creator. |
| `scripts/e3_write_files_used_report.py` | Provenance report. |
| `scripts/e3_clean_macos_sidecars.py` | Remove macOS sidecar clutter from analysed inputs. |
| `e3parquet/candidate_evidence.py`, `curated.py` | Main scientific transformations. |
| `e3parquet/fasta.py`, `tabular.py`, `duckdb_views.py` | Format-specific helpers. |
| `e3parquet/file_manifest.py`, `reports.py` | Provenance/manifests/reports. |
| `e3parquet/io_utils.py`, `logging_utils.py`, `cleanup.py` | Defensive operational utilities. |
| `docs/CANDIDATE_EVIDENCE_RESOURCE.md` | Candidate table definitions and interpretation. |
| `docs/CANDIDATE_EVIDENCE_TEST_TRACEABILITY.tsv` | Requirement/test mapping. |
| `tests/` | Unit, CLI, release-contract and integration tests. |

## `e3_orthology_integration`

This package reconciles candidate accessions with the authoritative OrthoFinder output. It preserves
the exact distinction between orthogroups, hierarchical orthogroups and predicted orthologue
relationships.

| File or module | Role |
|---|---|
| `README.md`, `RELEASE_NOTES_v0_1_3.md`, `RELEASE_NOTES_v0_1_4.md` | User guide plus maintenance and current group-sequence release records. |
| `config/results_feb26.yaml` | Reviewed authoritative Results_Feb26 settings. |
| `config/species_manifest_results_feb26.tsv` | 60-proteome species mapping. |
| `e3orthology/data/*` | Packaged copies of the default Results_Feb26 configuration/manifest. |
| `environment.yml`, `pyproject.toml`, `requirements*.txt` | Environment and package definitions. |
| `run_e3_orthology_integration.sh` | Foreground named-option runner. |
| `submit_e3_orthology_integration.sh` | Slurm submission wrapper. |
| `slurm/e3_orthology_integration.sbatch` | Batch job body. |
| `run_tests.sh` | Quality/test runner. |
| `e3orthology/cli.py`, `__main__.py` | CLI entry. |
| `config.py`, `species.py` | Configuration and species mappings. |
| `identifiers.py`, `candidates.py` | Candidate/FASTA/OrthoFinder identifier reconciliation. |
| `orthofinder.py`, `sqlite_audit.py` | OrthoFinder parsers and inherited SQLite cross-checks. |
| `stages.py`, `pipeline.py` | Restartable stage orchestration, including candidate-group member sequence publication. |
| `io_utils.py`, `logging_utils.py`, `errors.py` | Defensive operations. |
| `tests/` | Function, CLI, stage, integration and release tests. |

## `e3_ligandability_pipeline`

This package owns AlphaFold model selection/confidence, FPocket, P2Rank, residue mapping and pocket
quality. Its outputs are predictions, not experimental binding evidence.

| File or module | Role |
|---|---|
| `README.md`, `RELEASE_NOTES_v0_1_*.md` | User and release documentation. |
| `RELEASE_VALIDATION_SUMMARY_*.txt` | Frozen release validation summaries. |
| `pyproject.toml`, `MANIFEST.in`, `requirements*.txt` | Packaging/dependencies. |
| `environment.cluster.yml` | Cluster tool environment. |
| `config/config.cluster.example.yaml` | Cluster configuration template. |
| `examples/accessions.local_models.example.tsv` | Input-manifest example. |
| `run_e3_ligandability.sh` | Main named workflow runner. |
| `scripts/submit_e3_ligandability_slurm.sh`, `slurm_e3_ligandability_job.sh` | Slurm submission and job body. |
| `scripts/e3_ligandability.py` | Compatibility CLI script forwarding into the package. |
| `run_tests.sh`, `run_coverage.sh` | Test/coverage gates. |
| `run_legacy_regression.sh` | Explicit comparison with retained inherited behaviour. |
| `e3ligandability/alphafold.py` | AlphaFold acquisition/metadata. |
| `structure.py`, `models.py`, `mapping.py` | Coordinate parsing, records and residue mapping. |
| `fpocket.py`, `p2rank.py`, `tools.py` | External pocket-tool execution/parsing. |
| `pipeline.py`, `config.py`, `cli.py` | Workflow, configuration and CLI. |
| `outputs.py`, `qc.py`, `provenance.py`, `regression.py` | Publication, validation, manifests and legacy comparison. |
| `io_utils.py`, `logging_utils.py` | Defensive operations. |
| `docs/` | Output schema, methods/limits, cluster runbook, legacy decision and traceability. |
| `legacy_reference/` | Frozen inherited scripts/checksums/environment for audit only. |
| `tests/` | Unit, CLI regression, structure, tool-output and release-contract tests. |
| `BUILD_*`, `COVERAGE_*`, `WHEEL_*`, `TWINE_*`, `DIST_CHECKSUMS_*` | Historical packaging/validation evidence, not runtime inputs. |

## `expression_downloader`

This R package plus Python-first scripts acquires Expression Atlas resources, imports Parquet and
creates queryable DuckDB/duckplyr views.

| File or group | Role |
|---|---|
| `README.md`, `PYTHON_FIRST_WORKFLOW.md`, `CONDA_SETUP.md` | Main guides. |
| `DESCRIPTION`, `NAMESPACE`, `LICENSE` | R package metadata/exports/licence. |
| `envs/e3_atlas_duckplyr*.yml` | Full and minimal environments. |
| `data/species.txt`, `species_overrides.tsv` | Species registry inputs/overrides. |
| `data/manual_experiments_template.tsv` | Explicit manual experiment additions. |
| `basic_runner.sh` | Compact workflow wrapper. |
| `run_full_expression_atlas_pipeline.sh` | Full production entry point. |
| `rebuild_duckdb_views.sh` | Rebuild views from retained Parquet without reacquisition. |
| `R/species.R`, `atlas_search.R`, `atlas_files.R` | Species/experiment/file discovery. |
| `R/identifiers.R` | Identifier alias extraction. |
| `R/duckplyr_import.R`, `query.R` | Parquet/DuckDB import and queries. |
| `R/pipeline.R`, `file_helpers.R`, `utils_cli.R` | Orchestration and utilities. |
| `inst/python/discover_and_download_atlas.py` | Python-first discovery/acquisition. |
| `inst/python/download_atlas_files.py` | Manifest-driven file downloader. |
| `inst/python/import_expression_to_parquet.py` | Expression import. |
| `inst/python/import_sample_metadata_to_parquet.py` | Sample metadata import. |
| `inst/scripts/00_*` through `09_*` | Ordered dependency, registry, discovery, download, import, view, query and test steps. |
| `inst/scripts/run_all.R`, `run_python_first_then_r.sh`, `_bootstrap.R` | Combined runners/bootstrap. |
| `inst/extdata/species.txt` | Installed package copy of the default species registry. |
| `tests/` | R and Python unit/integration tests. |

## `E3_shiny_app`

This is the R Shiny read-only viewer. It must open completed resources and must not mutate analysis
authorities.

| File or module | Role |
|---|---|
| `README.md`, `DATA_RESOURCE_GUIDE.md` | App and data-resource guides. |
| `DESCRIPTION`, `NAMESPACE`, `LICENSE` | R package metadata/exports/licence. |
| `app.R` | Shiny application composition. |
| `run_app.sh` | Shell launcher. |
| `config/app_config.example.tsv` | Data-source configuration example. |
| `R/app_config.R` | Configuration validation. |
| `R/data_sources.R`, `data_source_report.R`, `resource_helpers.R` | Resource discovery, validation and reporting. |
| `R/query_helpers.R`, `utils.R` | Read-only query/common helpers. |
| `R/module_resource_overview.R`, `module_resource_browser.R`, `module_data_sources.R` | Integrated-resource overview/browsing/provenance modules. |
| `R/module_expression_filters.R`, `module_expression_plots.R`, `module_expression_summary.R`, `module_expression_table.R`, `module_gene_lookup.R` | Expression/gene exploration modules. |
| `inst/scripts/check_dependencies.R`, `run_app.R`, `write_data_sources_report.R`, `script_utils.R` | Installed operational scripts. |
| `inst/scripts/run_tests.R` | Installed test entry point. |
| `www/app.css` | Application styling. |
| `tests/` | R unit/module tests. |

## `e3_python_app`

This is the Python/Streamlit read-only viewer intended to parallel the Shiny app.

| File or module | Role |
|---|---|
| `README.md` | Installation/configuration/use. |
| `config/app.env.example` | Environment-variable template. |
| `environment.yml`, `pyproject.toml`, `requirements*.txt` | Environment/package metadata. |
| `run_e3_python_app.sh` | App launcher. |
| `run_tests.sh` | Test/style runner. |
| `src/e3app/cli.py`, `__main__.py` | Named CLI and module entry. |
| `src/e3app/config.py` | Environment/resource validation. |
| `src/e3app/data.py` | Read-only data access. |
| `src/e3app/streamlit_app.py` | User interface. |
| `src/e3app/errors.py` | Controlled exceptions. |
| `docs/TEST_TRACEABILITY.tsv` | App requirement/test mapping. |
| `tests/` | Configuration, data, CLI and UI tests. |

## Historical/development artefacts

The repository currently tracks several file classes that are not analysis authorities:

- `.DS_Store`, `.coverage` and `__pycache__/` files;
- a malformed-looking `e3_discovery_engine/.gitignore:` filename;
- old `TEST_RESULTS`, `COVERAGE_RESULTS`, build, wheel, Twine and checksum captures;
- `e3_discovery_engine/test_outputs/`;
- `e3_discovery_engine/dist/*.whl`; and
- duplicated `e3_end_to_end_workflow/data_bk/`.

They are documented here so users do not mistake them for inputs. Removing or reorganising them
should be a separate, reviewed repository-clean-up change; they are not silently deleted as part of
scientific workflow releases.
