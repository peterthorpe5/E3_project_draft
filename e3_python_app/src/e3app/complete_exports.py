"""Batched, complete TSV and Excel exports with explicit row-count manifests."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from io import TextIOWrapper
import logging
from numbers import Integral
from tempfile import TemporaryFile
from typing import Iterator, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
import xlsxwriter

from e3app.errors import AppError
from e3app.exports import normalise_excel_scalar, safe_file_stem
from e3app.glossary import column_definition_row
from e3app.result_queries import ResourceQuery

LOGGER = logging.getLogger(__name__)
EXPORT_BATCH_ROWS = 4096
EXCEL_DATA_ROWS = 1_048_575
EXCEL_COLUMNS = 16_384
EXCEL_TEXT_CHARACTERS = 32_767


def iter_query_batches(
    *,
    connection: duckdb.DuckDBPyConnection,
    query: ResourceQuery,
    batch_rows: int = EXPORT_BATCH_ROWS,
) -> Iterator[tuple[tuple[object, ...], ...]]:
    """Stream every result row in bounded batches without a pandas materialisation.

    Args:
        connection: Open resource connection, used exclusively while iterating.
        query: Complete read-only query.
        batch_rows: Positive batch size, at most 100,000 rows.

    Yields:
        Tuples of complete source rows until the query is exhausted.

    Raises:
        AppError: If the batch size or source query is invalid.
    """
    if (
        not isinstance(batch_rows, Integral)
        or isinstance(batch_rows, bool)
        or not 1 <= batch_rows <= 100_000
    ):
        raise AppError("Export batch rows must be between 1 and 100000")
    try:
        cursor = connection.execute(query.sql, query.parameters)
        while rows := cursor.fetchmany(int(batch_rows)):
            yield tuple(rows)
    except duckdb.Error as exc:
        LOGGER.exception("Complete export failed for %s", query.name)
        raise AppError(f"Complete export failed for {query.name}: {exc}") from exc


def query_schema(
    *,
    connection: duckdb.DuckDBPyConnection,
    query: ResourceQuery,
) -> tuple[tuple[str, str], ...]:
    """Inspect complete output fields without collecting result rows.

    Args:
        connection: Open resource connection.
        query: Complete query to describe.

    Returns:
        Ordered field names and DuckDB types.

    Raises:
        AppError: If the result schema cannot be inspected.
    """
    try:
        rows = connection.execute(f"DESCRIBE {query.sql}", query.parameters).fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)
    except duckdb.Error as exc:
        raise AppError(f"Could not inspect export fields for {query.name}: {exc}") from exc


def _export_notes(*, description: str) -> str:
    """Describe the exact tabular export scope and interpretation boundaries.

    Args:
        description: Applied source, search and group selection.

    Returns:
        Human-readable archive/workbook guidance.
    """
    return (
        "E3 complete tabular evidence export\n\n"
        f"Created (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        f"Selection: {description}\n\n"
        "Every matching row and every query field is included, independently of "
        "screen row limits and hidden preview columns. Manifest counts describe "
        "the exported rows, not the preview. TSV files are UTF-8, tab-separated, "
        "with quoted cells for embedded tabs/newlines; SQL nulls are empty cells. "
        "Source relations remain separate to preserve one-to-many evidence.\n\n"
        "Canonical HOG ranks retain the stored resource-wide ranking; blank ranks "
        "mean unavailable, not a low rank. All original ranking relations are "
        "included when linked. A dossier follows recorded group, cluster and "
        "protein identifiers, and reports its linking columns. Shared identifiers "
        "can connect rows with different group annotations; retain that context.\n\n"
        "Scope: tabular records in the loaded resource. External databases, "
        "structure files in separate review bundles and new analysis jobs are "
        "not fetched or embedded. Missing source evidence is not reconstructed.\n"
    )


def _validate_export(*, queries: Sequence[ResourceQuery], description: str) -> None:
    """Reject empty or ambiguously named complete-export requests.

    Args:
        queries: Queries to export in the supplied order.
        description: Human-readable selection provenance.

    Raises:
        AppError: If queries, names or provenance are invalid.
    """
    if not queries:
        raise AppError("There are no result queries to export")
    names = [query.name for query in queries]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise AppError("Export result names must not be blank")
    if len(set(names)) != len(names):
        raise AppError("Export result names must be unique")
    if not isinstance(description, str) or not description.strip():
        raise AppError("Complete exports require a selection description")


def complete_tsv_archive(
    *,
    connection: duckdb.DuckDBPyConnection,
    queries: Sequence[ResourceQuery],
    description: str,
) -> bytes:
    """Export all query rows and fields as compressed, separately named TSV files.

    Args:
        connection: Open resource connection.
        queries: Complete query for each source to export.
        description: Applied source and selection, recorded in README.txt.

    Returns:
        ZIP bytes containing data, counts and a complete field dictionary.

    Raises:
        AppError: If any source fails; no partial archive is returned.
    """
    _validate_export(queries=queries, description=description)
    manifest: list[tuple[object, ...]] = []
    definitions: list[dict[str, str]] = []
    with TemporaryFile(mode="w+b") as output:
        with ZipFile(output, mode="w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr("README.txt", _export_notes(description=description))
            for index, query in enumerate(queries, start=1):
                schema = query_schema(connection=connection, query=query)
                filename = f"tables/{index:03d}_{safe_file_stem(value=query.name)}.tsv"
                row_count = 0
                with archive.open(filename, mode="w", force_zip64=True) as binary:
                    with TextIOWrapper(binary, encoding="utf-8", newline="") as text_file:
                        writer = csv.writer(text_file, delimiter="\t", lineterminator="\n")
                        writer.writerow([name for name, _ in schema])
                        for batch in iter_query_batches(connection=connection, query=query):
                            writer.writerows(batch)
                            row_count += len(batch)
                manifest.append((query.name, filename, row_count, len(schema)))
                definitions.extend(
                    column_definition_row(
                        column_name=name,
                        declared_type=declared_type,
                        relations=(query.name,),
                    )
                    for name, declared_type in schema
                )
                LOGGER.info("Exported complete TSV source=%s rows=%d", query.name, row_count)
            with archive.open("manifest.tsv", mode="w") as binary:
                with TextIOWrapper(binary, encoding="utf-8", newline="") as text_file:
                    writer = csv.writer(text_file, delimiter="\t", lineterminator="\n")
                    writer.writerow(("source", "file", "exported_rows", "exported_columns"))
                    writer.writerows(manifest)
            with archive.open("column_definitions.tsv", mode="w") as binary:
                with TextIOWrapper(binary, encoding="utf-8", newline="") as text_file:
                    writer = csv.DictWriter(
                        text_file,
                        fieldnames=list(definitions[0]),
                        delimiter="\t",
                        lineterminator="\n",
                    )
                    writer.writeheader()
                    writer.writerows(definitions)
        output.seek(0)
        return output.read()


def _write_excel_row(
    *,
    worksheet: object,
    row_number: int,
    values: Sequence[object],
    cell_format: object = None,
) -> None:
    """Write literal Excel cells, rejecting values Excel would silently truncate.

    Args:
        worksheet: XlsxWriter worksheet.
        row_number: Zero-based output row.
        values: Complete row values.
        cell_format: Optional shared cell format.

    Raises:
        AppError: If Excel cannot retain an entire value or column.
    """
    if len(values) > EXCEL_COLUMNS:
        raise AppError("Excel cannot retain this many fields; use the complete TSV archive")
    for column_number, raw_value in enumerate(values):
        value = normalise_excel_scalar(value=raw_value)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        if isinstance(value, str):
            if len(value) > EXCEL_TEXT_CHARACTERS:
                raise AppError(
                    "A value exceeds Excel's cell text limit; use the complete TSV archive "
                    "to retain every character"
                )
            status = worksheet.write_string(row_number, column_number, value, cell_format)
        else:
            status = worksheet.write(row_number, column_number, value, cell_format)
        if status != 0:
            raise AppError("Excel could not retain a complete cell; use the TSV archive")


def complete_excel_workbook(
    *,
    connection: duckdb.DuckDBPyConnection,
    queries: Sequence[ResourceQuery],
    description: str,
) -> bytes:
    """Stream every row to Excel, splitting tables across sheets when necessary.

    Args:
        connection: Open resource connection.
        queries: Complete query for each source to export.
        description: Applied source and selection provenance.

    Returns:
        Formatted XLSX bytes with manifest, guidance and field definitions.

    Raises:
        AppError: If an Excel limit would lose data or any source fails.
    """
    _validate_export(queries=queries, description=description)
    with TemporaryFile(mode="w+b") as output:
        workbook = xlsxwriter.Workbook(
            output,
            {
                "constant_memory": True,
                "strings_to_formulas": False,
                "strings_to_urls": False,
            },
        )
        header = workbook.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white"})
        definitions: list[dict[str, str]] = []
        manifest: list[tuple[object, ...]] = []
        try:
            notes = workbook.add_worksheet("Read me")
            notes.set_column(0, 0, 110)
            for row_number, line in enumerate(_export_notes(description=description).splitlines()):
                _write_excel_row(worksheet=notes, row_number=row_number, values=(line,))
            for index, query in enumerate(queries, start=1):
                schema = query_schema(connection=connection, query=query)
                columns = tuple(name for name, _ in schema)
                sheet_names: list[str] = []
                row_count = 0
                sheet_row = EXCEL_DATA_ROWS + 1
                # An empty result still has a header sheet and a zero-count manifest entry.
                for batch in iter_query_batches(connection=connection, query=query):
                    for row in batch:
                        if sheet_row > EXCEL_DATA_ROWS:
                            sheet_name = f"Result_{index:03d}_{len(sheet_names) + 1}"
                            worksheet = workbook.add_worksheet(sheet_name)
                            sheet_names.append(sheet_name)
                            worksheet.freeze_panes(1, 0)
                            worksheet.set_column(0, len(columns) - 1, 24)
                            _write_excel_row(
                                worksheet=worksheet,
                                row_number=0,
                                values=columns,
                                cell_format=header,
                            )
                            sheet_row = 1
                        _write_excel_row(worksheet=worksheet, row_number=sheet_row, values=row)
                        sheet_row += 1
                        row_count += 1
                        if sheet_row > EXCEL_DATA_ROWS:
                            worksheet.autofilter(0, 0, sheet_row - 1, len(columns) - 1)
                if not sheet_names:
                    sheet_name = f"Result_{index:03d}_1"
                    worksheet = workbook.add_worksheet(sheet_name)
                    worksheet.freeze_panes(1, 0)
                    worksheet.set_column(0, len(columns) - 1, 24)
                    sheet_names.append(sheet_name)
                    _write_excel_row(
                        worksheet=worksheet,
                        row_number=0,
                        values=columns,
                        cell_format=header,
                    )
                    sheet_row = 1
                worksheet.autofilter(0, 0, max(1, sheet_row - 1), len(columns) - 1)
                manifest.append((query.name, ";".join(sheet_names), row_count, len(columns)))
                definitions.extend(
                    column_definition_row(
                        column_name=name,
                        declared_type=declared_type,
                        relations=(query.name,),
                    )
                    for name, declared_type in schema
                )
                LOGGER.info("Exported complete Excel source=%s rows=%d", query.name, row_count)
            manifest_sheet = workbook.add_worksheet("Manifest")
            manifest_sheet.freeze_panes(1, 0)
            manifest_sheet.set_column(0, 1, 55)
            manifest_sheet.set_column(2, 3, 20)
            _write_excel_row(
                worksheet=manifest_sheet,
                row_number=0,
                values=("source", "worksheets", "exported_rows", "exported_columns"),
                cell_format=header,
            )
            for row_number, row in enumerate(manifest, start=1):
                _write_excel_row(worksheet=manifest_sheet, row_number=row_number, values=row)
            dictionary = workbook.add_worksheet("Column definitions")
            dictionary.freeze_panes(1, 0)
            dictionary.set_column(0, len(definitions[0]) - 1, 40)
            _write_excel_row(
                worksheet=dictionary,
                row_number=0,
                values=tuple(definitions[0]),
                cell_format=header,
            )
            for row_number, definition in enumerate(definitions, start=1):
                _write_excel_row(
                    worksheet=dictionary,
                    row_number=row_number,
                    values=tuple(definition.values()),
                )
        finally:
            workbook.close()
        output.seek(0)
        return output.read()
