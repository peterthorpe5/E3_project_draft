# E3 end-to-end workflow

This package is the orchestration layer above the existing E3 project packages. It does not copy
their scientific logic. Snakemake controls dependencies; each component package remains responsible
for its own detailed validation, outputs and scientific interpretation.

Version `0.2.0` corrects the Python quality gates and formalises the known-E3 evidence input. The
complete twelve-stage DAG, manifests, atomic stage publication, local/Slurm profiles and synthetic
end-to-end test are implemented. The production template still fails closed until the remaining
package adapters are explicitly configured. `CHANGE_ME` values are never treated as defaults.

## DAG and package ownership

| Stage | Owner or planned owner | Publication contract |
|---|---|---|
| `00_inputs` | master workflow | checksummed proteome, seed and shortlist manifests |
| `01_prepared_proteomes` | master adapter | validated species/FASTA inventory |
| `02_discovery` | `e3_discovery_engine` | DIAMOND DeepClust resource |
| `03_candidate_evidence` | `e3_source_to_parquet_seed` | candidate evidence TSV/Parquet/DuckDB |
| `04_orthofinder` | fresh OrthoFinder execution | one isolated, versioned result directory |
| `05_orthology` | `e3_orthology_integration` | parsed identifier and run-specific membership tables |
| `06_domains` | planned domain-evidence component | family/domain evidence, separate from orthology |
| `07_expression` | `expression_downloader` | Expression Atlas Parquet/DuckDB |
| `08_shortlist_gate` | human review plus master validation | approved accession table with sign-off |
| `09_ligandability` | `e3_ligandability_pipeline` | AlphaFold/FPocket/P2Rank resource |
| `10_integrated_resource` | planned release assembler | shared DuckDB plus TSV/Parquet authorities |
| `11_app_ready` | master workflow | Python/Shiny handoff and readiness statement |

DeepClust clusters and OrthoFinder groups remain different concepts. OrthoFinder labels are scoped
to a run. Ligandability is intentionally downstream of a signed shortlist rather than applied to
every cluster member.

## Install and prove the installation

```bash
cd e3_end_to_end_workflow
python -m pip install -e '.[dev]'
./run_tests.sh
./run_e3_end_to_end.sh --dry-run
```

The committed synthetic configuration uses two tiny, visibly synthetic FASTAs and runs all stages.
Its outputs contain `TEST DATA ONLY` and are never production eligible.

## Production preparation

1. Copy `config/production.cluster.template.yaml` to a run-specific immutable YAML.
2. Create `proteomes.tsv`, `data/known_e3_seed_evidence.tsv.gz` and the signed shortlist with the
   documented headers.
3. Replace every `CHANGE_ME` argv with a tested adapter command. Commands are YAML argv lists, not
   shell strings; this prevents accidental quoting and injection errors.
4. Set each `expected_outputs` entry to a non-empty file the component publishes only after success.
5. Validate and inspect the DAG before running:

```bash
e3-workflow validate --config /path/to/run.yaml
e3-workflow plan --config /path/to/run.yaml
./run_e3_end_to_end.sh --config /path/to/run.yaml --profile slurm --dry-run
```

The Slurm profile defaults to account `barton`, partition `general`; resource values can be
overridden with normal Snakemake options. A production stage without an explicit command is rejected
at configuration load time. Every stage runs under `.staging`, records logs and SHA-256 checksums,
and is moved to its formal directory only after its declared output contract passes.

## Restart behaviour

Normal Snakemake targets, `--rerun-incomplete`, and checksum-bearing stage manifests provide the
restart boundary. To rerun one stage, remove or move that stage and its downstream directories, then
request the final target. Existing stage directories are moved under `superseded` if publication
would otherwise replace them. Failed staging directories are retained under `failed`.

## Known-E3 evidence resource

The production seed evidence is a deterministic derivative of the discovery engine's authoritative
`prepared_inputs/known_e3_seeds.tsv`. It retains the accession, E3 category, GO evidence flags,
organism, taxon, sequence MD5 and source-row provenance without storing the full sequence-bearing
51 MB table in Git.

Build it on the cluster from the workflow package root:

```bash
e3-workflow build-seed-evidence \
    --source /home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results/full_onekp_plus_v0_1_14_20260715_100551/prepared_inputs/known_e3_seeds.tsv \
    --output data/known_e3_seed_evidence.tsv.gz
```

The command also writes `data/known_e3_seed_evidence.provenance.tsv`. Existing outputs are protected;
use `--force` only when intentionally rebuilding them from a reviewed source.
