"""Tests for safe TSV and formatted Excel download support."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from e3app import exports


def test_safe_file_stem_normalises_paths_and_rejects_empty_values() -> None:
    """File stems remain portable and cannot become hidden or empty names."""
    assert exports.safe_file_stem(value="N0.HOG1:leaf / root") == (
        "N0.HOG1_leaf_root"
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        exports.safe_file_stem(value="///")
    with pytest.raises(TypeError, match="must be a string"):
        exports.safe_file_stem(value=123)  # type: ignore[arg-type]


def test_normalise_excel_scalar_preserves_types_and_blocks_formulas() -> None:
    """Missing and complex values are normalised without evaluating text."""
    assert exports.normalise_excel_scalar(value=None) is None
    assert exports.normalise_excel_scalar(value=pd.NA) is None
    assert exports.normalise_excel_scalar(value=np.nan) is None
    assert exports.normalise_excel_scalar(value="=2+2") == "=2+2"
    assert exports.normalise_excel_scalar(value={"b", "a"}) == '["a", "b"]'
    assert exports.normalise_excel_scalar(value=np.int64(7)) == 7
    assert exports.normalise_excel_scalar(value=1234567890123456) == (
        "1234567890123456"
    )
    assert exports.normalise_excel_scalar(value=float("inf")) == "inf"
    assert exports.normalise_excel_scalar(
        value=pd.Timestamp("2026-08-12")
    ) == datetime(2026, 8, 12)
    assert exports.normalise_excel_scalar(
        value=pd.Timestamp("2026-08-12", tz="Europe/London")
    ).endswith("+01:00")
    assert exports.normalise_excel_scalar(value=object()).startswith(
        "<object object at"
    )


@pytest.mark.parametrize(
    ("column_name", "series", "expected"),
    [
        ("candidate_accession", pd.Series([123]), "text"),
        ("member_count", pd.Series([2], dtype="int64"), "integer"),
        ("member_count", pd.Series([2.0, None]), "integer"),
        (
            "same_pocket_position_support_fraction",
            pd.Series([0.0, 0.5, 1.0]),
            "decimal",
        ),
        ("alignment_length_fraction", pd.Series([0.25, 0.75]), "decimal"),
        ("final_score", pd.Series([0.8123]), "decimal"),
        ("adjusted_p_value", pd.Series([1.0e-8]), "scientific"),
        ("supported", pd.Series([True], dtype="bool"), "logical"),
        ("created", pd.Series(pd.to_datetime(["2026-08-12"])), "datetime"),
        (
            "updated",
            pd.Series([datetime(2026, 8, 12)], dtype="object"),
            "datetime",
        ),
        ("date", pd.Series([date(2026, 8, 12)]), "date"),
        ("notes", pd.Series(["review"]), "text"),
    ],
)
def test_excel_format_kind_is_semantic_and_conservative(
    column_name: str,
    series: pd.Series,
    expected: str,
) -> None:
    """Scientific identifiers and measurements receive appropriate formats."""
    assert exports.excel_format_kind(
        column_name=column_name,
        series=series,
    ) == expected
    with pytest.raises(ValueError, match="non-empty"):
        exports.excel_format_kind(column_name="", series=series)


def test_excel_column_width_is_readable_and_bounded() -> None:
    """Widths expand for content but never become unusably narrow or wide."""
    assert exports.excel_column_width(
        column_name="rank",
        series=pd.Series([1, 2]),
    ) == 12.0
    assert exports.excel_column_width(
        column_name="description",
        series=pd.Series(["x" * 200]),
    ) == 50.0
    with pytest.raises(ValueError, match="non-empty"):
        exports.excel_column_width(column_name="", series=pd.Series([1]))


def test_excel_text_is_long_is_targeted_and_validated() -> None:
    """Only genuinely long text should use the smaller left-aligned style."""
    assert exports.excel_text_is_long(value="x" * 81)
    assert not exports.excel_text_is_long(value="x" * 80)
    assert not exports.excel_text_is_long(value=123)
    with pytest.raises(ValueError, match="positive integer"):
        exports.excel_text_is_long(value="text", threshold=0)
    with pytest.raises(ValueError, match="positive integer"):
        exports.excel_text_is_long(value="text", threshold=True)


def test_dataframe_display_formats_are_readable_without_rounding_data() -> None:
    """App tables show concise numbers and retain exact underlying values."""
    frame = pd.DataFrame(
        {
            "final_rank": [1, 2],
            "final_score": [0.1751018181818182, 0.8992472727272727],
            "adjusted_p_value": [1.2e-12, 0.05],
            "status": ["PASS", "FAIL"],
        }
    )
    original = frame.copy(deep=True)
    assert exports.dataframe_display_formats(frame=frame) == {
        "final_rank": "%d",
        "final_score": "%.3f",
        "adjusted_p_value": "%.2e",
    }
    pd.testing.assert_frame_equal(frame, original)

    with pytest.raises(TypeError, match="DataFrame"):
        exports.dataframe_display_formats(frame=[])  # type: ignore[arg-type]
    duplicate = pd.DataFrame([[1, 2]], columns=["score", "score"])
    with pytest.raises(ValueError, match="duplicate"):
        exports.dataframe_display_formats(frame=duplicate)


def test_dataframe_display_widths_force_scrollable_readable_columns() -> None:
    """Every app column receives a bounded width suited to its semantics."""
    frame = pd.DataFrame(
        {
            "alignment_tool_count": [2],
            "best_mean_minimum_tm_score": [0.9156],
            "cluster_id": ["onekp_dataset@@scaffold-ERWT-2002086"],
            "interpretation": [
                "The same candidate member pocket must pass every aligner."
            ],
            "primary_group_type": ["HIERARCHICAL_ORTHOGROUP"],
        }
    )
    assert exports.dataframe_display_widths(frame=frame) == {
        "alignment_tool_count": 130,
        "best_mean_minimum_tm_score": 130,
        "cluster_id": 240,
        "interpretation": 360,
        "primary_group_type": 170,
    }

    with pytest.raises(TypeError, match="DataFrame"):
        exports.dataframe_display_widths(frame=[])  # type: ignore[arg-type]
    unnamed = pd.DataFrame([[1]], columns=[""])
    with pytest.raises(ValueError, match="non-empty"):
        exports.dataframe_display_widths(frame=unnamed)
    duplicate = pd.DataFrame([[1, 2]], columns=["score", "score"])
    with pytest.raises(ValueError, match="duplicate"):
        exports.dataframe_display_widths(frame=duplicate)


def test_dataframe_to_excel_bytes_has_table_filters_freeze_and_formats() -> None:
    """The XLSX is a filterable styled table with safe, typed values."""
    frame = pd.DataFrame(
        {
            "candidate_accession": ["Q9SA03", "=2+2", 1234567890123456],
            "final_rank": [1, 2, 3],
            "final_score": [0.91234, 0.2, None],
            "adjusted_p_value": [1.0e-8, 0.05, 0.1],
            "supported": [True, False, True],
            "review_date": pd.to_datetime(
                ["2026-08-11", "2026-08-12", "2026-08-13"]
            ),
            "notes": ["x" * 120, "short", None],
        }
    )
    payload = exports.dataframe_to_excel_bytes(frame=frame)
    assert payload.startswith(b"PK")

    with ZipFile(BytesIO(payload)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        dictionary_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
        table_xml = archive.read("xl/tables/table1.xml").decode("utf-8")
        dictionary_table_xml = archive.read("xl/tables/table2.xml").decode("utf-8")
        styles_xml = archive.read("xl/styles.xml").decode("utf-8")
        strings_xml = archive.read("xl/sharedStrings.xml").decode("utf-8")

    assert 'state="frozen"' in sheet_xml
    assert 'ySplit="1"' in sheet_xml
    assert 'showGridLines="0"' not in sheet_xml
    assert "<cols>" in sheet_xml
    assert 'ht="60"' in sheet_xml
    assert 'customHeight="1"' in sheet_xml
    assert "<f>" not in sheet_xml
    assert '<autoFilter ref="A1:G4"' in table_xml
    assert 'name="TableStyleMedium2"' in table_xml
    assert "0.000" in styles_xml
    assert "0.00E+00" in styles_xml
    assert "yyyy-mm-dd hh:mm" in styles_xml
    assert 'horizontal="center"' in styles_xml
    assert 'vertical="center"' in styles_xml
    assert '<sz val="10"' in styles_xml
    assert '<borders count="' in styles_xml
    assert "=2+2" in strings_xml
    assert 'state="frozen"' in dictionary_xml
    assert 'name="ColumnDictionaryTable"' in dictionary_table_xml
    assert "Plain-language definition" in strings_xml
    assert "candidate_accession" in strings_xml


def test_dataframe_to_excel_bytes_rejects_invalid_frames() -> None:
    """Invalid exports fail clearly before XlsxWriter receives the data."""
    with pytest.raises(TypeError, match="DataFrame"):
        exports.dataframe_to_excel_bytes(frame=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one column"):
        exports.dataframe_to_excel_bytes(frame=pd.DataFrame())
    duplicate = pd.DataFrame([[1, 2]], columns=["score", "score"])
    with pytest.raises(ValueError, match="duplicate"):
        exports.dataframe_to_excel_bytes(frame=duplicate)
    empty_payload = exports.dataframe_to_excel_bytes(
        frame=pd.DataFrame(columns=["candidate_accession"])
    )
    with ZipFile(BytesIO(empty_payload)) as archive:
        assert "xl/tables/table1.xml" in archive.namelist()
        strings_xml = archive.read("xl/sharedStrings.xml").decode("utf-8")
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
    assert "Column definitions" in workbook_xml
    assert "candidate_accession" in strings_xml


class _FakeColumn(AbstractContextManager["_FakeColumn"]):
    """Minimal Streamlit column context used to capture button calls."""

    def __exit__(self, *args: object) -> None:
        """Leave the fake context without suppressing exceptions."""


class _FakeStreamlit:
    """Capture paired download arguments without starting Streamlit."""

    def __init__(self) -> None:
        """Initialise an empty call record."""
        self.calls: list[dict[str, object]] = []

    def columns(self, *, spec: int) -> tuple[_FakeColumn, _FakeColumn]:
        """Return exactly two fake layout columns."""
        assert spec == 2
        return _FakeColumn(), _FakeColumn()

    def download_button(self, **kwargs: object) -> None:
        """Record a download call."""
        self.calls.append(kwargs)


def test_render_table_downloads_preserves_tsv_and_adds_excel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI keeps its existing TSV key and adds a neighbouring XLSX control."""
    fake = _FakeStreamlit()
    monkeypatch.setattr(exports, "st", fake)
    frame = pd.DataFrame({"rank": [1], "score": [0.9]})

    exports.render_table_downloads(
        frame=frame,
        file_stem="N0.HOG1:selection",
        tsv_label="TSV",
        excel_label="Excel",
        key="existing_download",
    )

    assert [call["file_name"] for call in fake.calls] == [
        "N0.HOG1_selection.tsv",
        "N0.HOG1_selection.xlsx",
    ]
    assert [call["key"] for call in fake.calls] == [
        "existing_download",
        "existing_download_excel",
    ]
    assert fake.calls[0]["mime"] == "text/tab-separated-values"
    assert fake.calls[1]["mime"] == exports.EXCEL_MIME_TYPE
    assert bytes(fake.calls[1]["data"]).startswith(b"PK")

    with pytest.raises(ValueError, match="non-empty key"):
        exports.render_table_downloads(
            frame=frame,
            file_stem="selection",
            tsv_label="TSV",
            excel_label="Excel",
            key="",
        )
    monkeypatch.setattr(exports, "st", None)
    with pytest.raises(RuntimeError, match="Streamlit"):
        exports.render_table_downloads(
            frame=frame,
            file_stem="selection",
            tsv_label="TSV",
            excel_label="Excel",
            key="download",
        )


def test_every_streamlit_tsv_table_uses_paired_downloads() -> None:
    """Every tabular location pairs its TSV and formatted Excel controls."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "e3app"
        / "streamlit_app.py"
    ).read_text(encoding="utf-8")
    helper_count = source.count("render_table_downloads(")
    assert helper_count >= 18
    assert source.count("tsv_label=") == helper_count
    assert source.count("excel_label=") == helper_count
    assert "to_csv(sep=\"\\t\"" not in source


def test_dataframe_to_fasta_bytes_supports_raw_and_aligned_sequences() -> None:
    """FASTA output retains alignment gaps and wraps deterministically."""
    frame = pd.DataFrame(
        {
            "fasta_identifier": ["seq one", "seq_two"],
            "species": ["Species one", "Species two"],
            "sequence": ["ACD-EF", "GGGGGG"],
        }
    )
    payload = exports.dataframe_to_fasta_bytes(
        frame=frame,
        identifier_column="fasta_identifier",
        sequence_column="sequence",
        description_columns=("species",),
        line_width=4,
    )
    assert payload.decode("utf-8") == (
        ">seq_one species=Species_one\nACD-\nEF\n"
        ">seq_two species=Species_two\nGGGG\nGG\n"
    )
    with pytest.raises(ValueError, match="duplicated"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame({"id": ["x", "x"], "seq": ["AA", "BB"]}),
            identifier_column="id",
            sequence_column="seq",
        )
    with pytest.raises(ValueError, match="unsupported"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame({"id": ["x"], "seq": ["AA1"]}),
            identifier_column="id",
            sequence_column="seq",
        )


def test_plotly_pdf_export_validates_renderer_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plot exports use the PDF format and reject renderer corruption."""
    import plotly.io as plotly_io

    calls: list[dict[str, object]] = []

    def fake_to_image(figure: object, **kwargs: object) -> bytes:
        calls.append({"figure": figure, **kwargs})
        return b"%PDF-1.4 test"

    monkeypatch.setattr(plotly_io, "to_image", fake_to_image)
    payload = exports.plotly_figure_to_pdf_bytes(figure={"data": []})
    assert payload.startswith(b"%PDF")
    assert calls[0]["format"] == "pdf"
    assert calls[0]["engine"] == "kaleido"

    monkeypatch.setattr(plotly_io, "to_image", lambda *args, **kwargs: b"bad")
    with pytest.raises(RuntimeError, match="invalid PDF"):
        exports.plotly_figure_to_pdf_bytes(figure={"data": []})
    with pytest.raises(ValueError, match="dimensions"):
        exports.plotly_figure_to_pdf_bytes(figure={}, width=10)


class _FakePdfStreamlit:
    """Capture the two-step on-demand Plotly PDF interaction."""

    def __init__(self, *, pressed: bool) -> None:
        """Initialise state and a deterministic prepare-button response."""
        self.session_state: dict[str, object] = {}
        self.pressed = pressed
        self.downloads: list[dict[str, object]] = []
        self.captions: list[str] = []

    def button(self, label: str, *, key: str) -> bool:
        """Return the configured prepare action."""
        assert label.startswith("Prepare ")
        assert key.endswith("_prepare")
        return self.pressed

    def download_button(self, **kwargs: object) -> None:
        """Record the final PDF download control."""
        self.downloads.append(kwargs)

    def caption(self, value: str) -> None:
        """Record a renderer message."""
        self.captions.append(value)


def test_render_plotly_pdf_download_prepares_only_on_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kaleido rendering is deferred until the user requests one PDF."""
    fake = _FakePdfStreamlit(pressed=False)
    monkeypatch.setattr(exports, "st", fake)
    calls: list[object] = []

    def fake_render(*, figure: object, width: int = 1400, height: int = 900) -> bytes:
        calls.append(figure)
        return b"%PDF prepared"

    monkeypatch.setattr(exports, "plotly_figure_to_pdf_bytes", fake_render)
    exports.render_plotly_pdf_download(
        figure={"data": []},
        file_stem="my plot",
        label="Download graph as PDF",
        key="plot_pdf",
    )
    assert calls == []
    assert fake.downloads == []

    fake.pressed = True
    exports.render_plotly_pdf_download(
        figure={"data": []},
        file_stem="my plot",
        label="Download graph as PDF",
        key="plot_pdf",
    )
    assert calls == [{"data": []}]
    assert fake.downloads[0]["file_name"] == "my_plot.pdf"
    assert fake.downloads[0]["mime"] == exports.PDF_MIME_TYPE


def test_render_plotly_pdf_download_reports_missing_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing renderer produces guidance without a broken download."""
    fake = _FakePdfStreamlit(pressed=True)
    monkeypatch.setattr(exports, "st", fake)

    def fail_render(**kwargs: object) -> bytes:
        raise RuntimeError("Kaleido is unavailable")

    monkeypatch.setattr(exports, "plotly_figure_to_pdf_bytes", fail_render)
    exports.render_plotly_pdf_download(
        figure={},
        file_stem="plot",
        label="Download graph as PDF",
        key="plot_pdf",
    )
    assert fake.captions == ["Kaleido is unavailable"]
    assert fake.downloads == []
    with pytest.raises(ValueError, match="non-empty key"):
        exports.render_plotly_pdf_download(
            figure={},
            file_stem="plot",
            label="PDF",
            key="",
        )
    monkeypatch.setattr(exports, "st", None)
    with pytest.raises(RuntimeError, match="Streamlit"):
        exports.render_plotly_pdf_download(
            figure={},
            file_stem="plot",
            label="PDF",
            key="plot",
        )
