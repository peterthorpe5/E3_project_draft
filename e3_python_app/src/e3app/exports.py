"""Safe tabular exports shared by the Streamlit application."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from io import BytesIO
from numbers import Integral, Real
from typing import Any

import pandas as pd
import xlsxwriter

try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - exercised by dependency checks.
    st = None  # type: ignore[assignment]

EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_INVALID_FILE_STEM = re.compile(r"[^A-Za-z0-9_.-]+")
_IDENTIFIER_COLUMN = re.compile(
    r"(^|_)(accession|checksum|digest|identifier|id)(_|$)",
    flags=re.IGNORECASE,
)
_INTEGER_COLUMN = re.compile(
    r"(^|_)(count|index|length|number|position|rank)(_|$)",
    flags=re.IGNORECASE,
)
_SCIENTIFIC_COLUMN = re.compile(
    r"(^|_)(e_?value|fdr|p_?value|q_?value)(_|$)",
    flags=re.IGNORECASE,
)


def safe_file_stem(*, value: str) -> str:
    """Return a portable non-empty file stem.

    Args:
        value: Proposed filename without an extension.

    Returns:
        Filename-safe stem containing only letters, numbers, dots, dashes and
        underscores.

    Raises:
        ValueError: If ``value`` is empty after normalisation.
    """
    if not isinstance(value, str):
        raise TypeError("The export file stem must be a string.")
    normalised = _INVALID_FILE_STEM.sub("_", value.strip()).strip("._")
    if not normalised:
        raise ValueError("The export file stem cannot be empty.")
    return normalised


def normalise_excel_scalar(*, value: Any) -> Any:
    """Convert a pandas value into a safe scalar accepted by XlsxWriter.

    Args:
        value: Cell value from a pandas data frame.

    Returns:
        A string, number, Boolean, date/time or ``None``. Formula-like strings
        remain strings and are written with ``write_string`` by the caller.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple, dict, set)):
        serialisable = sorted(value) if isinstance(value, set) else value
        return json.dumps(serialisable, ensure_ascii=False, default=str)
    missing = pd.isna(value)
    if pd.api.types.is_scalar(missing) and bool(missing):
        return None
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None:
            return value.isoformat()
        return value.to_pydatetime()
    if isinstance(value, Real) and not isinstance(value, (bool, Integral)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else str(numeric)
    if isinstance(value, Integral) and not isinstance(value, bool):
        integer = int(value)
        return integer if len(str(abs(integer))) <= 15 else str(integer)
    if isinstance(value, (str, bool, date, datetime)):
        return value
    return str(value)


def excel_format_kind(*, column_name: str, series: pd.Series) -> str:
    """Choose a conservative Excel display format for one scientific column.

    Args:
        column_name: Source column name.
        series: Source column values.

    Returns:
        One of ``text``, ``integer``, ``decimal``, ``scientific``, ``date``,
        ``datetime`` or ``logical``.
    """
    if not isinstance(column_name, str) or not column_name:
        raise ValueError("Excel columns must have non-empty string names.")
    if _IDENTIFIER_COLUMN.search(column_name):
        return "text"
    if pd.api.types.is_bool_dtype(series.dtype):
        return "logical"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    if pd.api.types.is_integer_dtype(series.dtype) or _INTEGER_COLUMN.search(
        column_name
    ):
        return "integer"
    if pd.api.types.is_numeric_dtype(series.dtype):
        if _SCIENTIFIC_COLUMN.search(column_name):
            return "scientific"
        return "decimal"
    non_missing = series.dropna()
    if not non_missing.empty and all(
        isinstance(value, datetime) for value in non_missing.head(100)
    ):
        return "datetime"
    if not non_missing.empty and all(
        isinstance(value, date) for value in non_missing.head(100)
    ):
        return "date"
    return "text"


def excel_column_width(*, column_name: str, series: pd.Series) -> float:
    """Calculate a readable, bounded Excel column width.

    Args:
        column_name: Source column name.
        series: Source column values.

    Returns:
        Width between 12 and 50 Excel character units.
    """
    if not isinstance(column_name, str) or not column_name:
        raise ValueError("Excel columns must have non-empty string names.")
    sample = series.dropna().head(500).map(lambda value: str(value))
    lengths = [len(column_name), *(len(value) for value in sample)]
    return float(min(50, max(12, max(lengths, default=len(column_name)) + 2)))


def dataframe_to_excel_bytes(*, frame: pd.DataFrame) -> bytes:
    """Create a filterable, formatted Excel workbook from displayed rows.

    Args:
        frame: Exact displayed or filtered data frame to export.

    Returns:
        Complete XLSX workbook bytes.

    Raises:
        TypeError: If ``frame`` is not a pandas data frame.
        ValueError: If the frame has no columns or contains duplicate names.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Excel export requires a pandas DataFrame.")
    if frame.shape[1] == 0:
        raise ValueError("Excel export requires at least one column.")
    column_names = [str(column) for column in frame.columns]
    if len(set(column_names)) != len(column_names):
        raise ValueError("Excel export does not support duplicate column names.")

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties(
        {
            "title": "ARIA plant E3 displayed results",
            "subject": "Filterable export from the ARIA plant E3 reporter",
            "author": "Peter Thorpe and collaborators",
            "comments": "The workbook contains the exact bounded rows displayed in the app.",
        }
    )
    worksheet = workbook.add_worksheet("Selection")
    worksheet.hide_gridlines(option=2)
    worksheet.freeze_panes(row=1, col=0)
    worksheet.set_zoom(zoom=90)
    worksheet.set_row(row=0, height=24)

    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#1F4E78",
            "border": 0,
            "align": "left",
            "valign": "vcenter",
        }
    )
    formats = {
        "text": workbook.add_format({"text_wrap": True, "valign": "top"}),
        "integer": workbook.add_format(
            {"num_format": "#,##0", "valign": "top"}
        ),
        "decimal": workbook.add_format(
            {"num_format": "0.000", "valign": "top"}
        ),
        "scientific": workbook.add_format(
            {"num_format": "0.00E+00", "valign": "top"}
        ),
        "date": workbook.add_format(
            {"num_format": "yyyy-mm-dd", "valign": "top"}
        ),
        "datetime": workbook.add_format(
            {"num_format": "yyyy-mm-dd hh:mm", "valign": "top"}
        ),
        "logical": workbook.add_format(
            {"align": "centre", "valign": "top"}
        ),
    }

    table_columns = []
    for column_index, column_name in enumerate(column_names):
        series = frame.iloc[:, column_index]
        kind = excel_format_kind(column_name=column_name, series=series)
        cell_format = formats[kind]
        worksheet.set_column(
            first_col=column_index,
            last_col=column_index,
            width=excel_column_width(column_name=column_name, series=series),
            cell_format=cell_format,
        )
        worksheet.write_string(
            row=0,
            col=column_index,
            string=column_name,
            cell_format=header_format,
        )
        table_columns.append(
            {"header": column_name, "header_format": header_format}
        )
        identifier_column = bool(_IDENTIFIER_COLUMN.search(column_name))
        for row_index, raw_value in enumerate(series, start=1):
            value = normalise_excel_scalar(value=raw_value)
            if value is None:
                worksheet.write_blank(
                    row=row_index,
                    col=column_index,
                    blank=None,
                    cell_format=cell_format,
                )
            elif isinstance(value, str) or identifier_column:
                worksheet.write_string(
                    row=row_index,
                    col=column_index,
                    string=str(value),
                    cell_format=cell_format,
                )
            elif isinstance(value, bool):
                worksheet.write_boolean(
                    row=row_index,
                    col=column_index,
                    boolean=value,
                    cell_format=cell_format,
                )
            elif isinstance(value, (date, datetime)):
                worksheet.write_datetime(
                    row=row_index,
                    col=column_index,
                    date=value,
                    cell_format=cell_format,
                )
            else:
                worksheet.write_number(
                    row=row_index,
                    col=column_index,
                    number=float(value),
                    cell_format=cell_format,
                )

    if not frame.empty:
        worksheet.add_table(
            first_row=0,
            first_col=0,
            last_row=len(frame),
            last_col=len(column_names) - 1,
            options={
                "name": "SelectionTable",
                "style": "Table Style Medium 2",
                "columns": table_columns,
                "autofilter": True,
                "banded_rows": True,
            },
        )

    workbook.close()
    return output.getvalue()


def render_table_downloads(
    *,
    frame: pd.DataFrame,
    file_stem: str,
    tsv_label: str,
    excel_label: str,
    key: str,
) -> None:
    """Render paired TSV and formatted Excel download controls.

    Args:
        frame: Exact table shown to the user.
        file_stem: Shared filename without an extension.
        tsv_label: User-facing TSV button label.
        excel_label: User-facing Excel button label.
        key: Existing stable Streamlit key for the TSV control. The Excel key
            is derived by appending ``_excel``.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Download controls require a non-empty key.")
    if st is None:
        raise RuntimeError("Streamlit is required to render download controls.")
    stem = safe_file_stem(value=file_stem)
    tsv_column, excel_column = st.columns(spec=2)
    with tsv_column:
        st.download_button(
            label=tsv_label,
            data=frame.to_csv(sep="\t", index=False),
            file_name=f"{stem}.tsv",
            mime="text/tab-separated-values",
            key=key,
        )
    with excel_column:
        st.download_button(
            label=excel_label,
            data=dataframe_to_excel_bytes(frame=frame),
            file_name=f"{stem}.xlsx",
            mime=EXCEL_MIME_TYPE,
            key=f"{key}_excel",
        )
