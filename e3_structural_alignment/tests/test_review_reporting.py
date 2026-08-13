"""Tests for standalone pocket-review HTML rendering."""

from __future__ import annotations

from pathlib import Path

from e3structalign.review_data import (
    load_report_payloads,
    resolve_review_inputs,
)
from e3structalign.review_models import ReviewInputOverrides, ReviewSettings
from e3structalign.review_reporting import (
    _records_table,
    _status_class,
    _text,
    group_page_name,
    render_evidence_matrix,
    render_group_page,
    render_index,
    write_html,
)


def _payload(review_run: dict[str, Path]) -> dict[str, object]:
    """Return the shared fully joined review payload."""
    inputs = resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=ReviewInputOverrides(),
    )
    return load_report_payloads(
        inputs=inputs,
        settings=ReviewSettings(),
    )[0]


def test_group_page_is_self_contained_and_explicit(
    review_run: dict[str, Path],
) -> None:
    """Group HTML embeds structure/alignment data and scientific limits."""
    payload = _payload(review_run)
    page = render_group_page(payload)
    assert "<canvas id=\"viewer\">" in page
    assert "Pocket-annotated MAFFT sequence alignment" in page
    assert 'id="pocketTracks"' in page
    assert "Member-level top-k agreement and rescue audit" in page
    assert "Decision interpretation" in page
    assert "Sequence and model inventory" in page
    assert "Downloadable audit resources" in page
    assert "prioritised_group_sequences.fasta" in page
    assert "never replaces the immutable strict rank-one result" in page
    assert "https://" not in page
    assert "P1" in page
    assert '"selection_rank":1' in page
    assert '<button id="fit" type="button">Fit and centre</button>' in page
    assert 'id="viewerStatus" class="note" aria-live="polite"' in page
    assert 'rx=-.28;ry=.45;zoom=1;draw();' in page
    assert "View fitted and centred." in page
    assert 'id="downloadViewPdf"' in page
    assert 'id="downloadAlignmentPdf"' in page
    assert "downloadCurrentViewPdf" in page
    assert "downloadAlignmentPdf" in page
    assert "application/pdf" in page
    assert group_page_name(payload) == "rank_001__orthogroup__OG0001.html"


def test_index_preserves_ranking_and_escapes_identifiers(
    review_run: dict[str, Path],
) -> None:
    """Index links the ordered report pages without executable identifiers."""
    payload = _payload(review_run)
    payload["group_key"]["primary_group_id"] = "<script>bad</script>"
    page = render_index([payload])
    assert "Ranked top-50 index" not in page
    assert "&lt;script&gt;bad&lt;/script&gt;" in page
    assert "<script>bad</script>" not in page
    assert "review_decisions_template.tsv" in page
    assert "evidence_matrix.html" in page
    assert "Downloadable audit outputs" in page
    assert "Minimum druggability" in page
    assert "Pre-structure rank" in page
    assert "prioritised_group_sequences.tsv" in page


def test_evidence_matrix_separates_strict_and_sensitivity(
    review_run: dict[str, Path],
) -> None:
    """Comparison matrix retains ranking and both structural conclusions."""
    payload = _payload(review_run)
    page = render_evidence_matrix([payload])
    assert "Strict 3D conservation" in page
    assert "Top-k 3D conservation" in page
    assert "not a new score" in page
    assert 'id="matrixStatus"' in page
    assert "rank_001__orthogroup__OG0001.html" in page


def test_write_html_replaces_existing_file_atomically(tmp_path: Path) -> None:
    """HTML publication can safely replace an existing formal file."""
    path = tmp_path / "report.html"
    write_html(path, "first")
    write_html(path, "second")
    assert path.read_text(encoding="utf-8") == "second"


def test_display_helpers_cover_unknown_and_negative_states() -> None:
    """Display helpers distinguish missing, negative and neutral evidence."""
    assert _text(None) == "—"
    assert _status_class("NOT_ASSESSED") == "unknown"
    assert _status_class("FAIL") == "not-supported"
    assert _status_class("NOT_SUPPORTED") == "not-supported"
    assert _status_class("SUPPORTED") == "supported"
    assert _status_class(True) == "supported"
    assert _status_class("false") == "not-supported"
    assert _status_class("review") == "neutral"
    assert "No member-level records" in _records_table([])
