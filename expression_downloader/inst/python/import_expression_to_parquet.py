#!/usr/bin/env python3
"""Stream Expression Atlas TPM/FPKM matrices into long Parquet files.

This script is intentionally independent of R. It reads the downloaded-file
manifest produced by ``discover_and_download_atlas.py``, selects successful TPM
and FPKM matrix downloads, and writes one long-format Parquet file per matrix.

The conversion is streaming: each wide TSV row is expanded into gene-by-sample
records in batches, then written to Parquet using pyarrow. This avoids loading a
whole Expression Atlas matrix into memory and avoids fragile R/vroom/DuckDB CSV
parsing for very wide Atlas files.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - exercised on user systems
    pa = None
    pq = None


def require_pyarrow() -> None:
    """Stop with a clear message when pyarrow is unavailable."""

    if pa is None or pq is None:
        raise SystemExit(
            "Missing Python dependency: pyarrow. Install it with:\n"
            "  mamba install -c conda-forge pyarrow\n"
            "or:\n"
            "  conda install -c conda-forge pyarrow"
        )

TRUE_VALUES = {"true", "t", "yes", "y", "1"}
FALSE_VALUES = {"false", "f", "no", "n", "0", ""}
EXPRESSION_TYPES = {"tpms": "TPM", "fpkms": "FPKM"}
NULL_VALUES = {"", "na", "n/a", "nan", "null", "none", "-"}

GENE_ID_PATTERN = re.compile(r"gene.*id|ensembl|identifier|^id$", re.I)
GENE_NAME_PATTERN = re.compile(r"gene.*name|gene.*symbol|symbol|^name$", re.I)


@dataclass(frozen=True)
class MatrixJob:
    """A single expression-matrix conversion job."""

    expression_tsv: Path
    output_parquet: Path
    experiment_accession: str
    species_column: str
    expression_unit: str
    file_type: str
    source_database: str = "ExpressionAtlas"


@dataclass(frozen=True)
class ColumnLayout:
    """Detected wide-matrix column layout."""

    header: list[str]
    gene_id_index: int
    gene_name_index: Optional[int]
    expression_indices: list[int]


@dataclass(frozen=True)
class ImportResult:
    """Summary of one matrix import."""

    expression_tsv: Path
    output_parquet: Path
    experiment_accession: str
    species_column: str
    expression_unit: str
    action: str
    success: bool
    imported_rows: int
    input_rows: int
    expression_columns: int
    message: str


def parse_bool(value: object, default: bool = False) -> bool:
    """Convert common text values to boolean.

    Parameters
    ----------
    value:
        Value to convert.
    default:
        Value to return when the input is not recognised.

    Returns
    -------
    bool
        Parsed boolean value.
    """

    if value is None:
        return default

    value_text = str(value).strip().lower()

    if value_text in TRUE_VALUES:
        return True
    if value_text in FALSE_VALUES:
        return False

    return default


def open_text(path: Path):
    """Open plain or gzipped text for reading.

    Parameters
    ----------
    path:
        File to open.

    Returns
    -------
    TextIO
        Readable text handle.
    """

    if str(path).endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8", newline="")

    return path.open(mode="r", encoding="utf-8", newline="")


def normalise_header_name(value: str) -> str:
    """Clean a header field without changing its biological meaning.

    Parameters
    ----------
    value:
        Raw header field.

    Returns
    -------
    str
        Cleaned header field.
    """

    return value.strip().strip('"').strip("'")


def make_unique(names: Iterable[str]) -> list[str]:
    """Return unique names while preserving the original order.

    Parameters
    ----------
    names:
        Input names.

    Returns
    -------
    list[str]
        Unique names with ``_2``, ``_3`` suffixes added when needed.
    """

    seen: dict[str, int] = {}
    unique_names: list[str] = []

    for name in names:
        clean_name = normalise_header_name(name)
        if clean_name == "":
            clean_name = "unnamed_column"

        count = seen.get(clean_name, 0) + 1
        seen[clean_name] = count

        if count == 1:
            unique_names.append(clean_name)
        else:
            unique_names.append(f"{clean_name}_{count}")

    return unique_names


def detect_column_layout(expression_tsv: Path) -> ColumnLayout:
    """Detect gene identifier and expression columns from a matrix header.

    Parameters
    ----------
    expression_tsv:
        Path to a wide Expression Atlas matrix.

    Returns
    -------
    ColumnLayout
        Detected column layout.
    """

    with open_text(expression_tsv) as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            raw_header = next(reader)
        except StopIteration as error:
            raise ValueError(f"Expression matrix has no header: {expression_tsv}") from error

    header = make_unique(raw_header)

    gene_id_index = 0
    for index, name in enumerate(header):
        if GENE_ID_PATTERN.search(name):
            gene_id_index = index
            break

    gene_name_index: Optional[int] = None
    for index, name in enumerate(header):
        if index == gene_id_index:
            continue
        if GENE_NAME_PATTERN.search(name):
            gene_name_index = index
            break

    metadata_indices = {gene_id_index}
    if gene_name_index is not None:
        metadata_indices.add(gene_name_index)

    expression_indices = [
        index for index in range(len(header)) if index not in metadata_indices
    ]

    return ColumnLayout(
        header=header,
        gene_id_index=gene_id_index,
        gene_name_index=gene_name_index,
        expression_indices=expression_indices,
    )


def safe_get(row: list[str], index: Optional[int]) -> str:
    """Safely extract a field from a row.

    Parameters
    ----------
    row:
        Parsed TSV row.
    index:
        Zero-based column index, or ``None``.

    Returns
    -------
    str
        Field value, or an empty string when unavailable.
    """

    if index is None:
        return ""
    if index < 0 or index >= len(row):
        return ""
    return row[index].strip()


def parse_float(value: str) -> Optional[float]:
    """Parse a numeric expression value.

    Parameters
    ----------
    value:
        Raw expression value.

    Returns
    -------
    float or None
        Parsed float, or ``None`` when the value is blank or non-numeric.
    """

    clean_value = value.strip().replace(",", "")

    if clean_value.lower() in NULL_VALUES:
        return None

    try:
        return float(clean_value)
    except ValueError:
        return None


def build_schema() -> pa.Schema:
    """Build the long-expression Parquet schema.

    Returns
    -------
    pyarrow.Schema
        Output schema.
    """

    return pa.schema(
        [
            pa.field("source_database", pa.string()),
            pa.field("experiment_accession", pa.string()),
            pa.field("species_column", pa.string()),
            pa.field("gene_id", pa.string()),
            pa.field("gene_name", pa.string()),
            pa.field("sample_or_condition", pa.string()),
            pa.field("expression_value", pa.float64()),
            pa.field("expression_unit", pa.string()),
            pa.field("source_file", pa.string()),
        ]
    )


def rows_to_table(rows: list[dict[str, object]], schema: pa.Schema) -> pa.Table:
    """Convert buffered dictionaries to a pyarrow table.

    Parameters
    ----------
    rows:
        Buffered output records.
    schema:
        Expected output schema.

    Returns
    -------
    pyarrow.Table
        Arrow table ready for Parquet writing.
    """

    columns = {name: [] for name in schema.names}
    for row in rows:
        for name in schema.names:
            columns[name].append(row.get(name))

    arrays = [pa.array(columns[name], type=schema.field(name).type) for name in schema.names]
    return pa.Table.from_arrays(arrays, schema=schema)


def parquet_row_count(path: Path) -> int:
    """Return the row count of a Parquet file.

    Parameters
    ----------
    path:
        Parquet file path.

    Returns
    -------
    int
        Number of rows, or zero if the file cannot be read.
    """

    if not path.exists() or path.stat().st_size == 0:
        return 0

    try:
        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:  # noqa: BLE001 - robust command-line tool
        return 0


def iter_matrix_records(
    job: MatrixJob,
    layout: ColumnLayout,
) -> Iterator[tuple[dict[str, object], int]]:
    """Yield long expression records from a wide matrix.

    Parameters
    ----------
    job:
        Matrix conversion job.
    layout:
        Detected column layout.

    Yields
    ------
    tuple[dict[str, object], int]
        Long record and the current input row number.
    """

    with open_text(job.expression_tsv) as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)

        for input_row_number, row in enumerate(reader, start=1):
            if not row:
                continue

            gene_id = safe_get(row=row, index=layout.gene_id_index)
            gene_name = safe_get(row=row, index=layout.gene_name_index)

            if gene_id == "":
                continue

            for index in layout.expression_indices:
                sample_or_condition = layout.header[index]
                value = parse_float(safe_get(row=row, index=index))

                if value is None:
                    continue

                yield (
                    {
                        "source_database": job.source_database,
                        "experiment_accession": job.experiment_accession,
                        "species_column": job.species_column,
                        "gene_id": gene_id,
                        "gene_name": gene_name,
                        "sample_or_condition": sample_or_condition,
                        "expression_value": value,
                        "expression_unit": job.expression_unit,
                        "source_file": str(job.expression_tsv),
                    },
                    input_row_number,
                )


def normalise_matrix_to_parquet(
    job: MatrixJob,
    force: bool,
    chunk_rows: int,
) -> ImportResult:
    """Convert one wide matrix to long Parquet.

    Parameters
    ----------
    job:
        Matrix conversion job.
    force:
        Whether to overwrite an existing non-empty Parquet file.
    chunk_rows:
        Number of long records to buffer per Parquet write.

    Returns
    -------
    ImportResult
        Import status and row counts.
    """

    if not job.expression_tsv.exists() or job.expression_tsv.stat().st_size == 0:
        return ImportResult(
            expression_tsv=job.expression_tsv,
            output_parquet=job.output_parquet,
            experiment_accession=job.experiment_accession,
            species_column=job.species_column,
            expression_unit=job.expression_unit,
            action="skipped_missing_or_empty_input",
            success=False,
            imported_rows=0,
            input_rows=0,
            expression_columns=0,
            message="input matrix missing or empty",
        )

    existing_rows = parquet_row_count(path=job.output_parquet)
    if not force and existing_rows > 0:
        layout = detect_column_layout(expression_tsv=job.expression_tsv)
        return ImportResult(
            expression_tsv=job.expression_tsv,
            output_parquet=job.output_parquet,
            experiment_accession=job.experiment_accession,
            species_column=job.species_column,
            expression_unit=job.expression_unit,
            action="skipped_existing_non_empty_parquet",
            success=True,
            imported_rows=existing_rows,
            input_rows=0,
            expression_columns=len(layout.expression_indices),
            message="existing Parquet contained rows",
        )

    layout = detect_column_layout(expression_tsv=job.expression_tsv)

    if len(layout.expression_indices) == 0:
        return ImportResult(
            expression_tsv=job.expression_tsv,
            output_parquet=job.output_parquet,
            experiment_accession=job.experiment_accession,
            species_column=job.species_column,
            expression_unit=job.expression_unit,
            action="skipped_no_expression_columns",
            success=False,
            imported_rows=0,
            input_rows=0,
            expression_columns=0,
            message="no expression columns detected",
        )

    job.output_parquet.parent.mkdir(parents=True, exist_ok=True)
    schema = build_schema()

    temporary_path = Path(
        tempfile.mkstemp(
            suffix=".parquet.partial",
            dir=str(job.output_parquet.parent),
        )[1]
    )

    writer: Optional[pq.ParquetWriter] = None
    buffer: list[dict[str, object]] = []
    imported_rows = 0
    input_rows = 0

    try:
        writer = pq.ParquetWriter(
            where=temporary_path,
            schema=schema,
            compression="snappy",
        )

        for record, input_row_number in iter_matrix_records(job=job, layout=layout):
            input_rows = max(input_rows, input_row_number)
            buffer.append(record)

            if len(buffer) >= chunk_rows:
                writer.write_table(rows_to_table(rows=buffer, schema=schema))
                imported_rows += len(buffer)
                buffer = []

        if buffer:
            writer.write_table(rows_to_table(rows=buffer, schema=schema))
            imported_rows += len(buffer)

    except Exception as error:  # noqa: BLE001 - command-line tool should keep going
        if writer is not None:
            writer.close()
        if temporary_path.exists():
            temporary_path.unlink()
        return ImportResult(
            expression_tsv=job.expression_tsv,
            output_parquet=job.output_parquet,
            experiment_accession=job.experiment_accession,
            species_column=job.species_column,
            expression_unit=job.expression_unit,
            action="import_failed",
            success=False,
            imported_rows=0,
            input_rows=input_rows,
            expression_columns=len(layout.expression_indices),
            message=str(error),
        )
    finally:
        if writer is not None:
            writer.close()

    if imported_rows == 0:
        if temporary_path.exists():
            temporary_path.unlink()
        return ImportResult(
            expression_tsv=job.expression_tsv,
            output_parquet=job.output_parquet,
            experiment_accession=job.experiment_accession,
            species_column=job.species_column,
            expression_unit=job.expression_unit,
            action="imported_zero_rows",
            success=False,
            imported_rows=0,
            input_rows=input_rows,
            expression_columns=len(layout.expression_indices),
            message="no numeric expression values were imported",
        )

    if job.output_parquet.exists():
        job.output_parquet.unlink()
    os.replace(temporary_path, job.output_parquet)

    final_rows = parquet_row_count(path=job.output_parquet)
    success = final_rows > 0

    return ImportResult(
        expression_tsv=job.expression_tsv,
        output_parquet=job.output_parquet,
        experiment_accession=job.experiment_accession,
        species_column=job.species_column,
        expression_unit=job.expression_unit,
        action="imported_to_parquet_python",
        success=success,
        imported_rows=final_rows,
        input_rows=input_rows,
        expression_columns=len(layout.expression_indices),
        message="ok" if success else "Parquet row-count validation failed",
    )


def read_downloaded_manifest(path: Path) -> list[dict[str, str]]:
    """Read the downloaded-file manifest.

    Parameters
    ----------
    path:
        Downloaded-file manifest TSV.

    Returns
    -------
    list[dict[str, str]]
        Manifest rows.
    """

    with path.open(mode="r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build_jobs(
    downloaded_files_tsv: Path,
    output_dir: Path,
) -> list[MatrixJob]:
    """Build conversion jobs from a downloaded-file manifest.

    Parameters
    ----------
    downloaded_files_tsv:
        Manifest produced by the Python discovery/download script.
    output_dir:
        Expression Atlas output directory.

    Returns
    -------
    list[MatrixJob]
        Matrix conversion jobs.
    """

    rows = read_downloaded_manifest(path=downloaded_files_tsv)
    jobs: list[MatrixJob] = []

    for row in rows:
        file_type = (row.get("file_type") or "").strip()
        if file_type not in EXPRESSION_TYPES:
            continue
        if not parse_bool(row.get("success"), default=False):
            continue

        species_column = (row.get("species_column") or "").strip()
        experiment_accession = (row.get("experiment_accession") or "").strip()
        source_database = (row.get("source_database") or "ExpressionAtlas").strip()
        local_path = Path((row.get("local_path") or "").strip())

        if not species_column or not experiment_accession or not str(local_path):
            continue

        output_parquet = (
            output_dir
            / "parquet"
            / "atlas_expression_long"
            / f"species_column={species_column}"
            / f"experiment_accession={experiment_accession}"
            / f"{file_type}.parquet"
        )

        jobs.append(
            MatrixJob(
                expression_tsv=local_path,
                output_parquet=output_parquet,
                experiment_accession=experiment_accession,
                species_column=species_column,
                expression_unit=EXPRESSION_TYPES[file_type],
                file_type=file_type,
                source_database=source_database,
            )
        )

    return jobs


def write_summary(path: Path, results: list[ImportResult]) -> None:
    """Write an import summary TSV.

    Parameters
    ----------
    path:
        Output summary path.
    results:
        Import results.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "expression_tsv",
        "output_parquet",
        "experiment_accession",
        "species_column",
        "expression_unit",
        "action",
        "success",
        "imported_rows",
        "input_rows",
        "expression_columns",
        "message",
    ]

    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "expression_tsv": str(result.expression_tsv),
                    "output_parquet": str(result.output_parquet),
                    "experiment_accession": result.experiment_accession,
                    "species_column": result.species_column,
                    "expression_unit": result.expression_unit,
                    "action": result.action,
                    "success": "true" if result.success else "false",
                    "imported_rows": result.imported_rows,
                    "input_rows": result.input_rows,
                    "expression_columns": result.expression_columns,
                    "message": result.message,
                }
            )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv:
        Optional argument list for testing.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """

    parser = argparse.ArgumentParser(
        description="Import Expression Atlas TPM/FPKM matrices to long Parquet."
    )
    parser.add_argument("--downloaded_files_tsv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--force_import", default="false")
    parser.add_argument("--chunk_rows", type=int, default=250000)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the importer.

    Parameters
    ----------
    argv:
        Optional argument list for testing.

    Returns
    -------
    int
        Process exit code.
    """

    args = parse_args(argv=argv)
    require_pyarrow()
    downloaded_files_tsv = Path(args.downloaded_files_tsv)
    output_dir = Path(args.output_dir)
    force_import = parse_bool(args.force_import, default=False)
    summary_path = output_dir / "manifests" / "atlas_expression_import_summary.tsv"

    if not downloaded_files_tsv.exists():
        raise SystemExit(f"Downloaded-files manifest does not exist: {downloaded_files_tsv}")

    jobs = build_jobs(
        downloaded_files_tsv=downloaded_files_tsv,
        output_dir=output_dir,
    )

    results: list[ImportResult] = []
    total_jobs = len(jobs)
    print(f"Python Parquet importer found {total_jobs} TPM/FPKM matrix jobs", flush=True)

    for index, job in enumerate(jobs, start=1):
        if index == 1 or index % 10 == 0 or index == total_jobs:
            print(
                f"Importing matrix {index}/{total_jobs}: "
                f"{job.species_column} {job.experiment_accession} {job.expression_unit}",
                flush=True,
            )

        result = normalise_matrix_to_parquet(
            job=job,
            force=force_import,
            chunk_rows=args.chunk_rows,
        )
        results.append(result)

    write_summary(path=summary_path, results=results)
    successful = sum(1 for result in results if result.success)
    imported_rows = sum(result.imported_rows for result in results if result.success)
    print(f"Wrote expression import summary: {summary_path}", flush=True)
    print(f"Successful matrix imports: {successful}/{total_jobs}", flush=True)
    print(f"Total long expression rows: {imported_rows}", flush=True)

    if total_jobs > 0 and successful == 0:
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
