# Outputs and interpretation

## Run-level organisation

```text
RUN_ROOT/
├── 00_inputs/
├── 01_prepared_proteomes/
├── ...
├── 11_app_ready/
├── benchmark_summary/
├── reports/
├── workflow_control/
└── workflow_logs/
```

Every completed stage contains:

- declared scientific outputs;
- `stage_manifest.json`;
- a persistent stage log;
- measured resource tables;
- a self-contained HTML stage report.

## Final integrated resources

Stage `10_integrated_resource` publishes:

- `duckdb/e3_integrated_resource.duckdb`;
- `tables/final_candidate_prioritisation.parquet`;
- `tables/final_candidate_prioritisation.tsv`;
- the master candidate Parquet;
- validation and provenance records;
- a final computational prioritisation HTML report.

Stage `11_app_ready` publishes stable hand-off files for the Python and R reporting
applications.

## Recommended review order

1. Confirm Snakemake reached the complete `all` target.
2. Read `reports/e3_workflow_summary.html`.
3. Check every stage status and validation table.
4. Review missing-evidence states.
5. Review the prioritisation profile and thresholds.
6. Inspect candidate evidence, orthology, domains and expression before structural scores.
7. Treat final recommendations as computational evidence requiring review.

## Interpretation boundaries

- Sequence-cluster membership does not prove E3 function.
- Orthogroup membership does not prove one-to-one orthology.
- Domain matches do not prove complete architecture or activity.
- Expression does not prove protein abundance or activity.
- AlphaFold confidence and pocket predictors do not prove binding.
- Three-dimensional similarity does not prove selectivity or degradation.

The pipeline is deliberately conservative about unavailable evidence. Missing domain,
expression or structure data must not enter denominators as biological negatives.

## Resource benchmarking

`benchmark_summary` contains stage and workflow wall time, CPU, memory and I/O. These are
measured values. Slurm memory requests are scheduler allocations and must not be reported
as observed RAM use.
