"""Safe tabular exports shared by the Streamlit application."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from io import BytesIO
from numbers import Integral, Real
from typing import Any, Sequence

import pandas as pd
import xlsxwriter

from e3app.glossary import column_definition_row

try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - exercised by dependency checks.
    st = None  # type: ignore[assignment]

EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
PDF_MIME_TYPE = "application/pdf"
_INVALID_FILE_STEM = re.compile(r"[^A-Za-z0-9_.-]+")
_IDENTIFIER_COLUMN = re.compile(
    r"(^|_)(accession|checksum|digest|identifier|id)(_|$)",
    flags=re.IGNORECASE,
)
_INTEGER_COLUMN = re.compile(
    r"(^|_)(count|index|number|rank)(_|$)|(^|_)(length|position)$",
    flags=re.IGNORECASE,
)
_SCIENTIFIC_COLUMN = re.compile(
    r"(^|_)(e_?value|fdr|p_?value|q_?value)(_|$)",
    flags=re.IGNORECASE,
)
_NARRATIVE_COLUMN = re.compile(
    r"interpretation|definition|description|caution|reason|evidence|"
    r"note|message|warning|limitation",
    flags=re.IGNORECASE,
)
_WIDE_TEXT_COLUMN = re.compile(
    r"accession|cluster.*id|group.*id|species|alignment.*tool|"
    r"candidate.*list|present|missing|unavailable",
    flags=re.IGNORECASE,
)
_LONG_TEXT_THRESHOLD = 80


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
    is_numeric = pd.api.types.is_numeric_dtype(series.dtype)
    numeric_values = series.dropna()
    integer_like = is_numeric and (
        numeric_values.empty
        or all(
            float(value).is_integer() for value in numeric_values.head(1000)
        )
    )
    if pd.api.types.is_integer_dtype(series.dtype) or (
        is_numeric
        and integer_like
        and _INTEGER_COLUMN.search(column_name)
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


def excel_text_is_long(
    *,
    value: Any,
    threshold: int = _LONG_TEXT_THRESHOLD,
) -> bool:
    """Return whether a cell needs the long-text Excel style.

    Args:
        value: Normalised cell value.
        threshold: Character count above which text is treated as long.

    Returns:
        ``True`` only for text longer than the configured threshold.

    Raises:
        ValueError: If ``threshold`` is not a positive integer.
    """
    if (
        not isinstance(threshold, Integral)
        or isinstance(threshold, bool)
        or threshold < 1
    ):
        raise ValueError("The long-text threshold must be a positive integer.")
    return isinstance(value, str) and len(value) > int(threshold)


def dataframe_display_formats(*, frame: pd.DataFrame) -> dict[str, str]:
    """Return readable Streamlit number formats without changing values.

    Args:
        frame: Data frame shown in an application table.

    Returns:
        Mapping from numeric column name to Streamlit printf-style format.

    Raises:
        TypeError: If ``frame`` is not a pandas data frame.
        ValueError: If column names are empty or duplicated after conversion to
            strings.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Display formatting requires a pandas DataFrame.")
    column_names = [str(column) for column in frame.columns]
    if any(not column for column in column_names):
        raise ValueError("Display columns must have non-empty names.")
    if len(set(column_names)) != len(column_names):
        raise ValueError("Display formatting does not support duplicate columns.")

    formats: dict[str, str] = {}
    for column_index, column_name in enumerate(column_names):
        kind = excel_format_kind(
            column_name=column_name,
            series=frame.iloc[:, column_index],
        )
        if kind == "integer":
            formats[column_name] = "%d"
        elif kind == "decimal":
            formats[column_name] = "%.3f"
        elif kind == "scientific":
            formats[column_name] = "%.2e"
    return formats


def dataframe_display_widths(*, frame: pd.DataFrame) -> dict[str, int]:
    """Return explicit Streamlit column widths for readable wide tables.

    Explicit widths prevent Streamlit from compressing a many-column result
    into the visible card width. The resulting grid uses its native horizontal
    scrollbar and stationary header while retaining every source column.

    Args:
        frame: Data frame shown in an application table.

    Returns:
        Mapping from every column name to a width in pixels.

    Raises:
        TypeError: If ``frame`` is not a pandas data frame.
        ValueError: If column names are empty or duplicated after conversion to
            strings.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Display sizing requires a pandas DataFrame.")
    column_names = [str(column) for column in frame.columns]
    if any(not column for column in column_names):
        raise ValueError("Display columns must have non-empty names.")
    if len(set(column_names)) != len(column_names):
        raise ValueError("Display sizing does not support duplicate columns.")

    widths: dict[str, int] = {}
    for column_index, column_name in enumerate(column_names):
        kind = excel_format_kind(
            column_name=column_name,
            series=frame.iloc[:, column_index],
        )
        if kind in {"integer", "decimal", "scientific", "logical"}:
            widths[column_name] = 130
        elif _NARRATIVE_COLUMN.search(column_name):
            widths[column_name] = 360
        elif _WIDE_TEXT_COLUMN.search(column_name):
            widths[column_name] = 240
        else:
            widths[column_name] = 170
    return widths


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
    worksheet.hide_gridlines(option=0)
    worksheet.freeze_panes(row=1, col=0)
    worksheet.set_zoom(zoom=90)
    worksheet.set_row(row=0, height=24)

    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#1F4E78",
            "border": 1,
            "border_color": "#A6A6A6",
            "align": "left",
            "valign": "vcenter",
        }
    )
    centred_cell = {
        "align": "centre",
        "valign": "vcenter",
        "border": 1,
        "border_color": "#D9E2F3",
    }
    formats = {
        "text": workbook.add_format(
            {**centred_cell, "text_wrap": True}
        ),
        "long_text": workbook.add_format(
            {
                "align": "left",
                "valign": "vcenter",
                "border": 1,
                "border_color": "#D9E2F3",
                "text_wrap": True,
                "font_size": 10,
            }
        ),
        "integer": workbook.add_format(
            {**centred_cell, "num_format": "#,##0"}
        ),
        "decimal": workbook.add_format(
            {**centred_cell, "num_format": "0.000"}
        ),
        "scientific": workbook.add_format(
            {**centred_cell, "num_format": "0.00E+00"}
        ),
        "date": workbook.add_format(
            {**centred_cell, "num_format": "yyyy-mm-dd"}
        ),
        "datetime": workbook.add_format(
            {**centred_cell, "num_format": "yyyy-mm-dd hh:mm"}
        ),
        "logical": workbook.add_format(centred_cell),
    }

    table_columns = []
    long_text_rows: set[int] = set()
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
            value_format = (
                formats["long_text"]
                if excel_text_is_long(value=value)
                else cell_format
            )
            if value_format is formats["long_text"]:
                long_text_rows.add(row_index)
            if value is None:
                worksheet.write_blank(
                    row=row_index,
                    col=column_index,
                    blank=None,
                    cell_format=value_format,
                )
            elif isinstance(value, str) or identifier_column:
                worksheet.write_string(
                    row=row_index,
                    col=column_index,
                    string=str(value),
                    cell_format=value_format,
                )
            elif isinstance(value, bool):
                worksheet.write_boolean(
                    row=row_index,
                    col=column_index,
                    boolean=value,
                    cell_format=value_format,
                )
            elif isinstance(value, (date, datetime)):
                worksheet.write_datetime(
                    row=row_index,
                    col=column_index,
                    date=value,
                    cell_format=value_format,
                )
            else:
                worksheet.write_number(
                    row=row_index,
                    col=column_index,
                    number=float(value),
                    cell_format=value_format,
                )

    for row_index in sorted(long_text_rows):
        worksheet.set_row(row=row_index, height=60)

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

    dictionary = workbook.add_worksheet("Column definitions")
    dictionary.hide_gridlines(option=0)
    dictionary.freeze_panes(row=1, col=0)
    dictionary.set_zoom(zoom=90)
    definition_rows = [
        column_definition_row(
            column_name=column_name,
            declared_type=str(frame.iloc[:, column_index].dtype),
            relations=("Selection",),
        )
        for column_index, column_name in enumerate(column_names)
    ]
    definition_columns = list(definition_rows[0])
    dictionary_widths = (32, 24, 60, 42, 60, 36, 28)
    for column_index, (column_name, width) in enumerate(
        zip(definition_columns, dictionary_widths, strict=True)
    ):
        dictionary.set_column(column_index, column_index, width)
        dictionary.write_string(0, column_index, column_name, header_format)
    dictionary_cell = workbook.add_format(
        {
            "align": "left",
            "valign": "top",
            "border": 1,
            "border_color": "#D9E2F3",
            "text_wrap": True,
            "font_size": 10,
        }
    )
    for row_index, row in enumerate(definition_rows, start=1):
        for column_index, column_name in enumerate(definition_columns):
            dictionary.write_string(
                row_index,
                column_index,
                str(row[column_name]),
                dictionary_cell,
            )
        dictionary.set_row(row_index, height=48)
    dictionary.add_table(
        first_row=0,
        first_col=0,
        last_row=len(definition_rows),
        last_col=len(definition_columns) - 1,
        options={
            "name": "ColumnDictionaryTable",
            "style": "Table Style Medium 2",
            "columns": [
                {"header": column, "header_format": header_format}
                for column in definition_columns
            ],
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


def dataframe_to_fasta_bytes(
    *,
    frame: pd.DataFrame,
    identifier_column: str,
    sequence_column: str,
    description_columns: Sequence[str] = (),
    line_width: int = 80,
) -> bytes:
    """Serialise sequence rows as deterministic UTF-8 FASTA.

    Args:
        frame: Sequence-bearing member table.
        identifier_column: Column used for the first FASTA header token.
        sequence_column: Column containing protein or aligned sequences.
        description_columns: Optional fields appended as ``name=value`` text.
        line_width: Maximum sequence characters per output line.

    Returns:
        UTF-8 encoded FASTA bytes in display-table order.

    Raises:
        TypeError: If ``frame`` is not a pandas data frame.
        ValueError: If columns, identifiers, sequences or width are invalid.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("FASTA export requires a pandas DataFrame.")
    if not isinstance(line_width, Integral) or isinstance(line_width, bool):
        raise ValueError("FASTA line width must be a positive integer.")
    if int(line_width) < 1:
        raise ValueError("FASTA line width must be a positive integer.")
    columns = [identifier_column, sequence_column, *description_columns]
    if any(not isinstance(column, str) or not column for column in columns):
        raise ValueError("FASTA export columns must have non-empty names.")
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError("FASTA export is missing columns: " + ", ".join(missing))
    records: list[str] = []
    seen: set[str] = set()
    for row_number, row in enumerate(frame.to_dict(orient="records"), start=1):
        identifier = "" if pd.isna(row[identifier_column]) else str(
            row[identifier_column]
        ).strip()
        identifier = re.sub(r"\s+", "_", identifier)
        if not identifier:
            raise ValueError(f"FASTA row {row_number} has no identifier.")
        if identifier in seen:
            raise ValueError(f"FASTA identifier is duplicated: {identifier}")
        seen.add(identifier)
        raw_sequence = "" if pd.isna(row[sequence_column]) else str(
            row[sequence_column]
        )
        sequence = re.sub(r"\s+", "", raw_sequence).upper()
        if not sequence:
            raise ValueError(f"FASTA row {row_number} has no sequence.")
        if re.search(r"[^A-Z*.?\-]", sequence):
            raise ValueError(
                f"FASTA row {row_number} contains unsupported sequence characters."
            )
        descriptions: list[str] = []
        for column in description_columns:
            value = row[column]
            if pd.isna(value) or not str(value).strip():
                continue
            text_value = re.sub(r"\s+", "_", str(value).strip())
            descriptions.append(f"{column}={text_value}")
        header = f">{identifier}"
        if descriptions:
            header += " " + " ".join(descriptions)
        records.append(header)
        records.extend(
            sequence[index:index + int(line_width)]
            for index in range(0, len(sequence), int(line_width))
        )
    if not records:
        raise ValueError("FASTA export requires at least one sequence row.")
    return ("\n".join(records) + "\n").encode("utf-8")


def plotly_figure_to_pdf_bytes(
    *, figure: Any, width: int = 1400, height: int = 900
) -> bytes:
    """Render a Plotly figure as vector PDF through Kaleido.

    Args:
        figure: Plotly figure accepted by ``plotly.io.to_image``.
        width: Export width in pixels.
        height: Export height in pixels.

    Returns:
        PDF bytes beginning with the PDF signature.

    Raises:
        ValueError: If dimensions are outside defensive limits.
        RuntimeError: If Plotly/Kaleido cannot render the figure.
    """
    if not 200 <= int(width) <= 5000 or not 200 <= int(height) <= 5000:
        raise ValueError("PDF dimensions must be between 200 and 5000 pixels.")
    try:
        import plotly.io as plotly_io

        payload = plotly_io.to_image(
            figure,
            format="pdf",
            width=int(width),
            height=int(height),
            engine="kaleido",
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            "Plot PDF export requires the packaged Kaleido renderer. "
            "Install the application dependencies and try again."
        ) from exc
    if not isinstance(payload, bytes) or not payload.startswith(b"%PDF"):
        raise RuntimeError("Plotly returned an invalid PDF payload.")
    return payload


def render_plotly_pdf_download(
    *, figure: Any, file_stem: str, label: str, key: str
) -> None:
    """Render one Streamlit PDF download for a Plotly figure."""
    if st is None:
        raise RuntimeError("Streamlit is required to render download controls.")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Plot PDF controls require a non-empty key.")
    stem = safe_file_stem(value=file_stem)
    payload_key = f"_{key}_payload"
    signature_key = f"_{key}_signature"
    current_signature = repr(figure.to_plotly_json() if hasattr(
        figure, "to_plotly_json"
    ) else figure)
    if st.session_state.get(signature_key) != current_signature:
        st.session_state.pop(payload_key, None)
        st.session_state[signature_key] = current_signature
    if st.button(f"Prepare {label.lower()}", key=f"{key}_prepare"):
        try:
            st.session_state[payload_key] = plotly_figure_to_pdf_bytes(
                figure=figure
            )
        except RuntimeError as exc:
            st.caption(str(exc))
            return
    payload = st.session_state.get(payload_key)
    if payload is not None:
        st.download_button(
            label=label,
            data=payload,
            file_name=f"{stem}.pdf",
            mime=PDF_MIME_TYPE,
            key=key,
        )
