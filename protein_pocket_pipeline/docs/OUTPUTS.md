# Outputs and app integration

The root `report.html` embeds the browser's table data and requires no server,
JavaScript CDN or internet connection. Its links use relative paths; move the
whole run folder together. It includes model/search/confidence filters, sortable
headings, pagination, model checks and links to each model's workbook/structures.

## Folders

| Path | Purpose |
| --- | --- |
| `inputs/<id>/` | Unmodified source model and supplied representative FASTA |
| `models/<id>/` | Prepared protein PDB and original-to-tool residue map TSV |
| `tool_outputs/<id>/fpocket/` | fpocket model, cavity atoms, original info file and full descriptors TSV |
| `tool_outputs/<id>/p2rank/` | Independent prediction tables and visualisation files |
| `tool_outputs/<id>/p2rank_rescore/` | Dataset pointing to the same fpocket output, rescoring tables and visualisations |
| `logs/<id>/` | Per-method `.command.json`, `.stdout.log`, `.stderr.log` |
| `tables/` | Normalised TSV tables, including header-only empty tables |
| `excel/` | Combined workbook plus `models/<id>.xlsx` |
| `database/` | A fully materialised `protein_pockets.duckdb` |
| `provenance/` | Run manifest, version/configuration and input/tool/software fingerprints |
| `checkpoints/` | Per-model state, derived-data digest and output-file checksums |
| `pipeline.log` | Run-level progress and failure tracebacks |

P2Rank creates CSV internally. These files are converted to TSV before a stage
finishes, with values retained as text in native-output tables. The normalised
tables have typed numeric values in Excel and DuckDB. The tool's binary/model
files and logs are not altered. `raw_descriptors.tsv` preserves the union of
native descriptor fields, including metrics absent from the main summary.

## Workbook

Every workbook has the same structure: **README**, **Ranked_cavities**,
**Model_checks**, **All_pockets**, **Prediction_overlap**, **Method_runs**,
**Residue_map**, **Pocket_residues**, **FPocket_descriptors**,
**Run_provenance**, **Field_dictionary**.

Tables have dark headers, frozen identifiers/header rows, filters and alternate
row shading. Fractions use percentage formats, numeric values remain numeric,
and failed/low-confidence states are visible. Blank means unavailable, not zero.
Original lining residue numbers are in **Pocket_residues**; the concise ranking
table uses prepared residue IDs. Method scores are deliberately separate.

Excel's cell text and row limits still apply. Text exceeding 32,767 characters is
explicitly shortened with a pointer to the complete TSV. A sheet exceeding
1,048,575 data rows fails rather than silently truncating; the TSV and DuckDB
exports are written first. The intended scale is a curated representative set.

## Stable DuckDB tables

| Table | One row per |
| --- | --- |
| `samples` | Submitted model, including failed/partial/no-pocket models |
| `ranked_pockets` | Ranked fpocket cavity with same-cavity P2Rank rescore, overlap and local confidence |
| `pockets` | Method-specific pocket, with distinct native score/rank fields |
| `residues` | Model residue mapping, original identifiers and pLDDT |
| `pocket_residues` | Distinct model/method/pocket/residue membership |
| `matches` | fpocket/independent-P2Rank pair passing the within-model overlap threshold |
| `method_runs` | Model/method completion state and log prefix |
| `fpocket_descriptors` | Original numeric fpocket descriptor for one cavity |
| `run_info` | Metadata key and JSON-encoded value |

All tables have explicit types and primary keys, even if empty. The database
contains no external `read_parquet`/`read_csv` views and stays usable without the
original paths. Schema version **1.0** is recorded in `run_info`. The full field
dictionary is available as TSV and in each workbook. Residue primary keys always
include model ID; pocket keys also include method.

Views:

- `v_best_pocket_per_model`: review rank 1 for models with fpocket cavities.
- `v_locally_confident_pockets`: ranked cavities meeting the configured local rule.
- `v_independent_p2rank`: independent prediction records only.
- `v_model_summary`: all submitted models plus cavity/prediction counts. Read
  status fields before interpreting a zero count: a failure is not evidence that
  the model has no pockets.

## Example queries

Best cavities within each model:

```sql
SELECT sample_id, review_rank, pocket_id, ranking_basis,
       p2rank_rescore_score, druggability_score, volume_a3,
       mean_plddt, confidence_status
FROM ranked_pockets
WHERE review_rank <= 5
ORDER BY sample_id, review_rank;
```

Original residues for one cavity:

```sql
SELECT author_chain, author_residue_number, insertion_code,
       fasta_position, plddt, mapped
FROM pocket_residues
WHERE sample_id = 'model_01' AND method = 'fpocket' AND pocket_id = 4
ORDER BY author_chain, author_residue_number, insertion_code;
```

Python app access uses parameter binding and read-only mode:

```python
import duckdb

with duckdb.connect(
    database="/path/to/results/database/protein_pockets.duckdb",
    read_only=True,
) as connection:
    rows = connection.execute(
        query="SELECT * FROM ranked_pockets WHERE sample_id = ? ORDER BY review_rank",
        parameters=["model_01"],
    ).fetchall()
```

## Visual inspection

P2Rank produces PyMOL and ChimeraX scripts in each successful method's
`output/visualizations/` directory, with copied structures and points in `data/`.
Open/run these from the visualisations directory so their relative paths resolve.
fpocket also retains its own visualisation scripts and pocket atom files. The
HTML provides a table browser and structure links; it is not an embedded 3D viewer.
