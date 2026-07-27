# Master configuration

One YAML file controls the complete run. Schema version 2 adds the central `tools`
registry and an optional `path_base` for generated sweep configurations. Schema version 1
remains readable for older immutable runs.

## Configuration ownership

| Section | Controls |
|---|---|
| `run` | Run identity, production/synthetic mode and output root |
| `inputs` | Controlled manifests, source resources and caches |
| `analysis` | Biological thresholds, scoring weights and interpretation policy |
| `tools` | Executables, reviewed versions, Conda environments and tool parameters |
| `stages` | Enabled state, evidence mode, argv, output contract and Slurm resources |
| `benchmarking` | Process-tree sampling and Slurm accounting |
| `reporting` | HTML preview limits and chart density |

## `run`

```yaml
run:
  name: my_species_panel_v0_1_0_20260725
  mode: production
  project_root: /path/to/E3_project_draft
  output_root: /path/to/analysis/e3_end_to_end_runs
```

`run.name` is the isolated output directory. It must change when any input, threshold or
tool setting changes.

## `inputs`

The exact required inputs depend on enabled stages and evidence modes. Common inputs are:

- proteome, seed and orthology-species manifests;
- the inherited SQLite resource used for identifier reconciliation;
- validated reusable Expression Atlas, domain and ligandability manifests;
- an authoritative OrthoFinder archive for a reuse run;
- an E3-domain catalogue.

Paths are resolved relative to the configuration file. A generated sweep config uses
`path_base` so those paths retain the base configuration's meaning.

## `analysis`

This section contains scientific policy used directly by internal implementations:

```yaml
analysis:
  expression:
    minimum_expression_value: 0.0
    broad_positive_fraction: 0.5
  ligandability:
    minimum_druggability_score: 0.5
    minimum_mapping_fraction: 0.95
    minimum_pocket_plddt_fraction: 0.7
    minimum_region_overlap: 0.25
  prioritisation:
    profile_name: grant_aligned_stringent_v1
    minimum_target_species_fraction: 0.9
    final_candidate_limit: 20
```

Weights validated as a group must sum to `1.0`. Fractions are validated within `0` to
`1`. Structural-alignment evidence cannot influence prioritisation unless stage `09b` is
enabled.

## `tools`

Each external tool has a stable lower-case name:

```yaml
tools:
  orthofinder:
    executable: orthofinder
    expected_version: 2.5.5
    conda_environment: e3_end_to_end_workflow
    parameters:
      search_threads: 32
      analysis_threads: 32
```

Stage argv lists refer to these values by named placeholders:

```yaml
stages:
  04_orthofinder:
    command:
      - "{tool_orthofinder_executable}"
      - -f
      - "{run_root}/01_prepared_proteomes/proteomes"
      - -t
      - "{tool_orthofinder_search_threads}"
      - -a
      - "{tool_orthofinder_analysis_threads}"
```

Tool parameters must be scalar strings, integers, numbers or booleans because one
placeholder maps to one argv token. Lists and nested parameter mappings are rejected
rather than being joined ambiguously. Booleans render as `true` or `false`.

The stage manifest records the complete resolved tool registry. The configuration digest
therefore binds the result to the executables, reviewed versions and parameters.

## `stages`

Every stage declares:

- `enabled` and `required`;
- `evidence_mode`;
- optional external `command` as an argv list;
- `expected_outputs`;
- `threads`, `memory_mb` and `runtime_minutes`.

Never put a shell command string in `command`. Each argument is a separate YAML list item,
which avoids quoting and injection errors.

## Configuration validation

```bash
e3-workflow validate --config /path/to/run.yaml
e3-workflow plan --config /path/to/run.yaml --human
```

Validation checks the schema, value bounds, stage contracts, controlled manifests and
checksums required by the selected branches. A file merely existing is never proof that a
stage completed.
