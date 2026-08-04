# E3AtlasDuckplyr

Version 0.5.0 is the corrected, Python-first Expression Atlas acquisition and
normalisation package for the E3 resource. R/duckplyr remains available for
lazy downstream queries, but raw expression parsing and database publication
are deliberately handled by the validated Python implementation.

No comma-separated output files are produced. Manifests and validation reports
are TSV; large relations are Parquet and DuckDB-backed.

## Scientific data contract

Expression Atlas baseline matrix cells are interpreted as follows:

| Raw cell | Meaning | Published `expression_value` |
|---|---|---:|
| `3,3,3,4,5` | minimum, lower quartile, median, upper quartile, maximum | `3.0` |
| `0,0,0.5,0.5,1` | five-number summary | `0.5` |
| `-` | Atlas measured-zero code | `0.0` |
| `2.5` | single numeric value | `2.5` |

The five comma-separated values are never treated as thousands separators and
never concatenated. The importer retains all five statistics and records
`expression_value_statistic = median`.

The contract is intentionally strict:

- matrix condition columns must be ordered and contiguous `g1..gN`;
- each row must have exactly the declared number of fields;
- gene identifiers and condition headers must be non-empty and unique;
- values must be finite, non-negative and statistically ordered;
- each matrix must have matching sample metadata and configuration XML;
- the configuration XML is the authority for `gN`-to-assay membership;
- every selected expression context must have exactly one metadata context;
- raw expression, XML and metadata SHA-256 values are carried into Parquet;
- stale derived files are not reused when a raw checksum changes;
- TPM is preferred within each species/experiment; FPKM is used only when TPM
  is absent for that experiment;
- database publication is atomic and a failed forced rebuild preserves the
  previous database.

The workflow, not the importer, applies the biological positivity rules. The
recorded production rules are median TPM/FPKM `>= 0.5`, at least 50% positive
contexts for a mapped gene, and expression support in at least 80% of assessed
target species.

## Required raw files

For every selected expression experiment, the downloaded manifest must make
all of these available:

1. a TPM matrix, or FPKM only when TPM is unavailable;
2. SDRF or condensed-SDRF sample metadata;
3. the Expression Atlas `configuration.xml` file defining assay groups.

Optional methods and R-object files may also be retained. Raw downloads are
immutable starting evidence and should not be deleted when rebuilding derived
outputs.

## Environment

Create the supplied environment:

```bash
mamba env create -f envs/e3_atlas_duckplyr.yml
conda activate e3_atlas_duckplyr
```

Or add the required Python dependencies to an existing environment:

```bash
mamba install -c conda-forge \
  pyarrow \
  python-duckdb \
  coverage \
  pycodestyle \
  pydocstyle \
  ruff
```

## Quality gates

Run the complete Python assurance suite:

```bash
./inst/scripts/09_run_python_tests.sh
```

This compiles and lints the supported code, runs all unit, corruption,
known-answer and raw-to-DuckDB tests, enforces at least 90% branch-aware
coverage, and validates every shell script. Version 0.5.0 has 99 passing Python
tests and 91% overall branch-aware coverage.

Run the R query-helper tests in the R-enabled environment:

```bash
R CMD INSTALL .
Rscript inst/scripts/08_run_tests.R
```

## Clean rebuild from existing raw downloads

This is the recommended route for the current project. It leaves the existing
raw download tree untouched and creates all corrected Parquet and DuckDB
outputs in a new directory.

```bash
set -euo pipefail

REPO_ROOT="/home/pthorpe001/data/2026_E3_protac/E3_project_draft"

RAW_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/expression_atlas_ftp_full"

REBUILD_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/expression_atlas_rebuild_v0_5_0_20260803"

DOWNLOADED_MANIFEST="${RAW_ROOT}/manifests/atlas_downloaded_files.tsv"

test -s "${DOWNLOADED_MANIFEST}"

if [[ -e "${REBUILD_ROOT}" ]]; then
  printf 'ERROR: rebuild directory already exists: %s\n' \
    "${REBUILD_ROOT}" >&2
  exit 1
fi

mkdir -p "${REBUILD_ROOT}/manifests"
cp -p \
  "${DOWNLOADED_MANIFEST}" \
  "${REBUILD_ROOT}/manifests/source_atlas_downloaded_files.tsv"

cd "${REPO_ROOT}/expression_downloader"

./inst/scripts/04_python_import_expression_to_parquet.sh \
  --downloaded_files_tsv "${DOWNLOADED_MANIFEST}" \
  --output_dir "${REBUILD_ROOT}" \
  --force_import false \
  --chunk_rows 250000

./inst/scripts/05_python_import_sample_metadata_to_parquet.sh \
  --downloaded_files_tsv "${DOWNLOADED_MANIFEST}" \
  --output_dir "${REBUILD_ROOT}" \
  --force_import false

./inst/scripts/06_python_create_duckdb_views.sh \
  --output_dir "${REBUILD_ROOT}" \
  --duckdb_path "${REBUILD_ROOT}/e3_expression.duckdb" \
  --force false
```

`force=false` is intentional because the rebuild directory is new. No old
Parquet or DuckDB file is eligible for reuse.

## Validate the clean rebuild

First confirm that every selected raw source imported successfully:

```bash
set -euo pipefail

EXPRESSION_SUMMARY="${REBUILD_ROOT}/manifests/atlas_expression_import_summary.tsv"
METADATA_SUMMARY="${REBUILD_ROOT}/manifests/atlas_sample_metadata_import_summary.tsv"
DATABASE_VALIDATION="${REBUILD_ROOT}/manifests/atlas_duckdb_validation.tsv"

test -s "${EXPRESSION_SUMMARY}"
test -s "${METADATA_SUMMARY}"
test -s "${DATABASE_VALIDATION}"
test -s "${REBUILD_ROOT}/e3_expression.duckdb"

awk -F '\t' '
NR == 1 {
  for (i = 1; i <= NF; i++) column[$i] = i
  next
}
$(column["success"]) != "true" {failed++}
END {exit(failed > 0)}
' "${EXPRESSION_SUMMARY}"

awk -F '\t' '
NR == 1 {
  for (i = 1; i <= NF; i++) column[$i] = i
  next
}
$(column["success"]) != "true" {failed++}
END {exit(failed > 0)}
' "${METADATA_SUMMARY}"

column -t -s $'\t' "${DATABASE_VALIDATION}"
```

Then run semantic database checks without collecting the full dataset:

```bash
python - "${REBUILD_ROOT}/e3_expression.duckdb" <<'PY'
import sys
import duckdb

database = sys.argv[1]
with duckdb.connect(database, read_only=True) as connection:
    checks = {
        "expression_rows": "SELECT count(*) FROM atlas_expression_long",
        "selected_rows": "SELECT count(*) FROM atlas_expression_selected",
        "joined_rows": (
            "SELECT count(*) FROM atlas_expression_with_sample_metadata"
        ),
        "tissue_rows": (
            "SELECT count(*) FROM atlas_expression_with_sample_metadata "
            "WHERE coalesce(organism_part, '') <> ''"
        ),
        "five_number_rows": (
            "SELECT count(*) FROM atlas_expression_selected WHERE "
            "expression_summary_type = 'atlas_five_number_summary'"
        ),
        "measured_zero_rows": (
            "SELECT count(*) FROM atlas_expression_selected WHERE "
            "expression_summary_type = 'atlas_zero_code'"
        ),
    }
    values = {
        name: connection.execute(query).fetchone()[0]
        for name, query in checks.items()
    }
    for name, value in values.items():
        print(f"{name}\t{value}")
    assert values["expression_rows"] > 0
    assert values["selected_rows"] == values["joined_rows"]
    assert values["tissue_rows"] > 0
    assert values["five_number_rows"] > 0
PY
```

The exact counts depend on the downloaded experiments. The invariant is that
the selected-expression and metadata-joined row counts are identical.

## Build the workflow resource manifest

The workflow consumes the corrected Parquet relations, not the old derived
files. Generate a checksum-bound manifest with workflow v0.13.0:

```bash
set -euo pipefail

conda activate e3_end_to_end_workflow
cd "${REPO_ROOT}/e3_end_to_end_workflow"
python -m pip install --no-deps --editable .

e3-workflow build-expression-manifest \
  --expression-root "${REBUILD_ROOT}/parquet" \
  --output "${REBUILD_ROOT}/manifests/e3_workflow_expression_resources.tsv"

test -s \
  "${REBUILD_ROOT}/manifests/e3_workflow_expression_resources.tsv"
```

Point a new workflow configuration at that new manifest. Do not replace a
completed run in place; start a new run root so the corrected expression
results, rankings, integrated DuckDB and portable app data are provenance-clear.

## Fresh discovery and download

To rediscover and redownload everything instead of reusing the existing raw
files:

```bash
./inst/scripts/run_python_first_then_r.sh \
  --species_file data/species.txt \
  --override_tsv data/species_overrides.tsv \
  --output_dir /path/to/new/expression_atlas_raw_and_derived_v0_5_0 \
  --force_download false \
  --force_import false \
  --create_duckdb true \
  --import_backend python \
  --expression_file_types tpms,fpkms \
  --download_file_types \
    tpms,fpkms,configuration_xml,sample_metadata,analysis_methods,r_object
```

The downloader returns non-zero when no expression experiment is found, when a
selected download fails, or when any experiment lacks its complete matrix,
metadata and XML contract.

## Output layout

```text
<output>/
├── manifests/
│   ├── atlas_downloaded_files.tsv
│   ├── atlas_expression_import_summary.tsv
│   ├── atlas_sample_metadata_import_summary.tsv
│   ├── atlas_duckdb_validation.tsv
│   └── e3_workflow_expression_resources.tsv
├── downloads/                         # present for a fresh download
├── parquet/
│   ├── atlas_expression_long/
│   ├── atlas_sample_metadata_long/
│   └── atlas_sample_metadata_wide/
└── e3_expression.duckdb
```

Important database relations are:

- `atlas_expression_long`: both TPM and FPKM raw-normalised relations;
- `atlas_expression_selected`: TPM-preferred, FPKM-fallback contexts;
- `atlas_sample_metadata_wide`: one checksum-bound row per metadata context;
- `atlas_expression_with_sample_metadata`: cardinality-preserving tissue join.

## Retired unsafe paths

The old R matrix parser and the old R-manifest-driven Python downloader now
fail closed. They did not enforce the five-number-summary and configuration-XML
contracts required by this release. Supported entry points are:

- `02_python_discover_download_atlas.sh`;
- `04_python_import_expression_to_parquet.sh`;
- `05_python_import_sample_metadata_to_parquet.sh`;
- `06_python_create_duckdb_views.sh`;
- `run_python_first_then_r.sh`.

## Controlled diagnostic snapshot

The snapshot utility creates a bounded, checksum-recorded archive containing
manifests, metadata, methods, matrix previews and optional official experiment
pages. It is diagnostic evidence, not a recursive web crawler and not a
substitute for the raw downloads:

```bash
./inst/scripts/10_snapshot_expression_evidence.sh \
  --expression-root "${RAW_ROOT}" \
  --workflow-run-root /path/to/completed/workflow/run \
  --output-archive /path/to/expression_evidence_snapshot.tar.gz \
  --fetch-pages true \
  --preview-rows 50 \
  --overwrite false
```

## Assurance boundary

Tests substantially reduce regression risk; they are not proof that an
external source will never change. A production rebuild must therefore retain
raw files and checksums, pass the import summaries and database invariants, run
the workflow in a new versioned directory, and receive biological spot review
before replacing the recorded primary result.
