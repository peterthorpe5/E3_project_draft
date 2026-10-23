# Resource layout and DuckDB schema 1.0

Each resource contains `project.json`, `pocket_workbench.duckdb`, `models/`,
`comparisons/`, `sequence_analyses/`, and, when used, `jobs/` and
`prediction_runs/`. Paths inside the portable resource are relative. Move the
whole resource to retain its coordinate files and viewer pages.

All DuckDB tables are materialised; no external CSV/Parquet views are needed.
`record_json` retains the complete imported/generated record in addition to
typed main fields. Database reads use read-only connections. Structure and
residue keys include the model ID.

| Table | One row per / important fields |
| --- | --- |
| `models` | Model: sample_id, group_id, sequence_id, status, mapping_status, confidence summaries, prepared_model |
| `pockets` | Model/method/pocket: review_rank, native/rescore scores, volume, confidence, lining residues |
| `residues` | Model/tool residue: author labels, amino acid, FASTA position, pLDDT, CA x/y/z |
| `sequences` | Representative sequence ID and amino acid sequence |
| `structure_alignments` | Comparison: reference/mobile, engine, status, RMSD, aligned atoms, input-model coverage, both TM-scores, rotation, translation, settings |
| `pocket_matches` | Pocket pair: centroid distance, symmetric overlap, mutual fraction, sequence Jaccard, mapping and support flags |
| `sequence_analyses` | MSA/tree analysis: method, sequence/column counts, filtering and bootstrap metadata |
| `project_info` | Schema, version, title, source manifest, provenance and revision metadata |

Views: `v_best_pocket_per_model`, `v_model_summary` and
`v_supported_pocket_matches`. Positional support and fold support are separate;
read settings/coverage before interpreting them. The latter view selects
complete-mapping, position-supported pairs, without inventing a Kabsch TM-score.

Example query:

```sql
SELECT reference, mobile, reference_pocket, mobile_pocket,
       centroid_distance, symmetric_overlap, sequence_jaccard,
       position_supported, fold_supported
FROM pocket_matches
WHERE position_supported
ORDER BY reference, mobile, symmetric_overlap DESC;
```

Python app access:

```python
import duckdb

with duckdb.connect("/path/to/project/pocket_workbench.duckdb", read_only=True) as db:
    rows = db.execute(
        "SELECT * FROM pockets WHERE sample_id = ? AND method = ? ORDER BY review_rank",
        ["model_a", "fpocket"],
    ).fetchall()
```

This is a new workbench schema. The original `protein_pockets.duckdb` remains a
separate prediction resource with its original schema.

## Additive 1.1 fields

The portable project schema remains 1.0-compatible. New builds rebuild DuckDB
with additional typed columns:

- `models`: explicit `hog_id`, `source_accession` and `source_url`.
- `structure_alignments`: reported `tool_version` and aligned sequence identity.
- `pocket_matches`: original reference/member ranks, comparable-residue count,
  residue identity fraction and chemical-group conservation.

Full residue correspondences remain in each pocket match's `record_json`,
including original labels, FASTA positions, distances and chemical classes.
The comparison JSON retains the same complete evidence. For example:

```sql
SELECT reference, mobile, reference_pocket, mobile_pocket,
       json_extract(record_json, '$.residue_correspondences') AS matched_residues
FROM pocket_matches;
```

Older resources open without an automatic rebuild. Their absent typed fields
and uncomputed conservation metrics are unavailable; running a new batch build
or import/export preparation materialises the new columns. Review exports
include a separate rank-one/top-k audit and dual-aligner agreement TSV/Excel.

## Additive 1.2 fields and quality tables

New resources add parent sample ID, input scope, region name, parent-sequence
bounds, selection source and original FASTA mapping status to `models`.
Pocket records add `quality_screen_pass`, `near_cut_boundary`,
`cut_boundary_distance_a`, `near_very_low_confidence` and
`uncertain_context_distance_a`. Legacy records have unknown/null values,
not an implicit pass.

| Table | Purpose |
| --- | --- |
| `quality_models` | Full-parent confidence, preparation status and retained/excluded counts |
| `quality_regions` | Every retained/rejected proposal with parent/model/sequence bounds, core/PAE metrics and cut ends |
| `quality_exclusions` | Original model-index ranges excluded from all retained regions |
| `region_comparison_plan` | Direct pair eligibility, corresponding residue count and mutual coverage |

The extra view `v_quality_screened_pockets` selects explicit passing records.
Complete source/QC records are retained in `record_json` where present and
the project-level `quality_preparation` metadata. All four tables are also
exported as TSV and formatted Excel sheets.

The browser reads old native resources without modifying their database.
Exports treat optional quality tables absent from 1.0/1.1 databases as empty.
New saves rebuild the expanded schema in the new resource; original predictor
databases remain unchanged. `cleaned_region` comparison scope and its
coverage/TM-scores refer to the retained input, not the parent protein.

