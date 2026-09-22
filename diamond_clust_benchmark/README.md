# DIAMOND clustering benchmark

This package answers one deliberately narrow question for the ARIA plant E3
project: can the pairwise sequence-clustering/database-building stage be made at
least 10% faster without materially changing cluster membership or the
neighbourhoods of controlled E3 sentinel sequences?

It extends the repository's `e3_discovery_engine` conventions for DIAMOND,
Snakemake, Slurm, provenance and atomic publication. It does not duplicate the
downstream E3 discovery, orthology, expression or application workflow.

## Scientific boundary

The supplied grant proposes DIAMOND2 and DeepClust comparative genomics to
identify and cluster plant E3 ligases, followed by expression and evolutionary
evidence and a searchable database. The grant milestone is delivery of the E3
resource; it does not state a 10% runtime target or require a methods contest.
The 10% target is therefore an internal optimisation deliverable that supports
the proposed method, rather than a verbatim grant milestone.

The existing full production timings make the benchmark scope important:

| Existing stage | Wall time |
|---|---:|
| `makedb` | 0.9 min |
| DeepClust | 97.1 min |
| representative/member realignment | 93.6 min |
| combined pairwise stage | 190.7 min |

A 10% reduction in `makedb` alone would save only seconds. The default decision
stage is consequently `pairwise_pipeline`, defined as clustering plus optional
realignment. `makedb`, clustering, realignment and total pipeline time are also
reported separately.

## Default comparison

The production template compares the current DIAMOND 2.2.3 exact-identity
DeepClust baseline with DIAMOND 2.2.8 strategies:

| Case | Purpose |
|---|---|
| DeepClust exact, default cascade | version-only comparison |
| DeepClust exact, faster final cascade | explicit cascade comparison |
| LinClust exact | faster linear clustering with exact identity |
| DeepClust approximate | speed/quality trade-off |
| LinClust approximate | fastest exploratory trade-off |

All cases use the same input, 32 threads, 220G DIAMOND limit, 50% identity,
50% mutual coverage, `evalue=0.1`, TANTAN masking and three isolated sequential
repeats. The full commands and exact resolved versions are retained in each
case manifest.

A candidate passes only when all configured conditions hold:

- mean paired speed-up is at least 10% on `pairwise_pipeline`;
- global cluster-membership pairwise F1 is at least 0.99; and
- when a sentinel TSV is supplied, E3 sentinel-neighbourhood recall is at
  least 0.99.

The report includes the paired bootstrap 95% interval for interpretation. It
does not claim biological interchangeability beyond the measured guardrails.

## Installation

The controller can reuse the established `e3_discovery` environment. Install
this small Python package into it and create the separate candidate DIAMOND
environment:

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft/diamond_clust_benchmark

conda run --name e3_discovery \
    python -m pip install --no-deps --editable .

conda env create --file workflow/envs/diamond_2_2_8.yml
```

If the established environment does not contain the controller dependencies,
create the supplied standalone environment instead:

```bash
conda env create --file workflow/envs/benchmark.yml
conda run --name diamond_clust_benchmark \
    python -m pip install --no-deps --editable .
```

The baseline configuration deliberately resolves DIAMOND 2.2.3 from
`e3_discovery`; candidate cases resolve 2.2.8 from `diamond_clust_2_2_8`.
Runtime preflight rejects any version mismatch before reading the large FASTA.

## Cluster run

Copy the versioned template; never edit a completed run into a new analysis:

```bash
cp config/full_onekp_cluster.template.yaml \
    config/full_onekp_cluster.v0_1_0.yaml
```

Review the absolute FASTA and output paths. Add a headered sentinel TSV when
the exact E3 seed identifiers are available:

```text
sequence_id
internal_sequence_identifier_1
internal_sequence_identifier_2
```

Validate and dry-run:

```bash
conda run --name e3_discovery \
    diamond-clust-benchmark validate-config \
    --config config/full_onekp_cluster.v0_1_0.yaml

conda run --name e3_discovery \
    ./run_workflow.sh \
    --config config/full_onekp_cluster.v0_1_0.yaml \
    --cores 32 \
    --dry-run
```

Submit one controller allocation. Cases run sequentially so they do not
compete for CPU, memory, scratch or filesystem bandwidth:

```bash
./scripts/submit_benchmark_slurm.sh \
    --config config/full_onekp_cluster.v0_1_0.yaml \
    --account barton \
    --partition barton \
    --cpus 32 \
    --memory 256G \
    --time 3-00:00:00 \
    --conda-env e3_discovery
```

## Outputs

The configured output root contains:

- `provenance/input_profile.tsv` and `runtime_preflight.json`;
- one atomic `cases/<case>/repeat_<n>/` directory per observation;
- per-stage `metrics.tsv`, logs and immutable `case_manifest.json` files;
- retained quality-repeat memberships only, limiting persistent storage;
- `tables/benchmark_summary.tsv`, `quality_summary.tsv` and
  `decision_summary.tsv`; and
- `reports/benchmark_summary.html` plus `report_manifest.json`.

Incomplete prior outputs are moved to `failed/`, never silently overwritten.
Case scratch directories are isolated and removed only after success or
captured failure metadata.

If all case repeats are complete but final quality reporting is interrupted,
rerun only the report in a fresh allocation. This command cannot rerun DIAMOND:

```bash
./scripts/submit_report_slurm.sh \
    --config config/full_onekp_cluster.v0_1_0.yaml \
    --run-root /absolute/path/to/the/existing/benchmark/root \
    --account barton \
    --partition barton \
    --cpus 2 \
    --memory 256G \
    --time 2-00:00:00 \
    --conda-env e3_discovery
```

The report uses two DuckDB threads and an isolated spill directory below
`<run-root>/scratch/quality`. Temporary spill data are removed after each
membership comparison.

## Tests

The test suite uses an external fake DIAMOND executable. It exercises the same
subprocess, monitoring, atomic publication and report paths without requiring
DIAMOND or cluster data:

```bash
./run_tests.sh

# Optional complete local Snakemake smoke run
./run_workflow.sh --config config/synthetic.yaml --cores 2
```

See `docs/BENCHMARK_PROTOCOL.md`, `docs/CLUSTER_RUNBOOK.md` and
`docs/GRANT_ALIGNMENT.md` for the frozen protocol, operational checks and the
grant-to-deliverable mapping.
