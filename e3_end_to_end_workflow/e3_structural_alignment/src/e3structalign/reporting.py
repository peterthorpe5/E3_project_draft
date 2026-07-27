"""Self-contained HTML reporting for structural pocket comparisons."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from e3structalign.io_utils import utc_now


def _text(value: Any) -> str:
    """Return one HTML-escaped display value."""
    if value is None:
        return "Not assessed"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        if math.isnan(value):
            return "Not assessed"
        return f"{value:.4f}"
    return html.escape(str(value))


def _status_class(value: str) -> str:
    """Return a safe CSS status class for one controlled label."""
    upper = value.upper()
    if "SUPPORTED" in upper and "NOT_SUPPORTED" not in upper:
        return "supported"
    if "INSUFFICIENT" in upper or "NOT_ASSESSED" in upper:
        return "unavailable"
    return "not-supported"


def _cards(summaries: Sequence[Mapping[str, Any]]) -> str:
    """Render the high-level group result cards."""
    position_supported = sum(
        row.get("position_alignment_status")
        == "SAME_3D_POCKET_POSITION_SUPPORTED"
        for row in summaries
    )
    conserved = sum(
        row.get("alignment_status") == "CONSERVED_3D_POCKET_SUPPORTED"
        for row in summaries
    )
    insufficient = sum(
        row.get("alignment_status") == "INSUFFICIENT_STRUCTURES"
        for row in summaries
    )
    values = (
        ("Groups assessed", len(summaries)),
        ("Same pocket position", position_supported),
        ("Locally conserved pocket", conserved),
        ("Insufficient structures", insufficient),
    )
    return "".join(
        '<div class="card"><div class="number">'
        f"{value}</div><div>{html.escape(label)}</div></div>"
        for label, value in values
    )


def _scatter_plot(summaries: Sequence[Mapping[str, Any]]) -> str:
    """Render a compact TM-score versus pocket-overlap SVG."""
    plotted = [
        row
        for row in summaries
        if row.get("mean_minimum_tm_score") is not None
        and row.get("mean_pocket_overlap_fraction") is not None
    ]
    if not plotted:
        return "<p>No groups had sufficient pairwise metrics for this plot.</p>"
    width = 760
    height = 430
    left = 70
    top = 25
    chart_width = 650
    chart_height = 335
    elements = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Mean TM-score against mean pocket overlap">'
    ]
    for tick in range(0, 11, 2):
        fraction = tick / 10
        x = left + fraction * chart_width
        y = top + (1 - fraction) * chart_height
        elements.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" '
            f'y2="{top + chart_height}" class="grid"/>'
        )
        elements.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" '
            f'y2="{y:.1f}" class="grid"/>'
        )
        elements.append(
            f'<text x="{x:.1f}" y="{top + chart_height + 25}" '
            f'text-anchor="middle">{fraction:.1f}</text>'
        )
        elements.append(
            f'<text x="{left - 15}" y="{y + 4:.1f}" '
            f'text-anchor="end">{fraction:.1f}</text>'
        )
    elements.extend(
        (
            f'<line x1="{left}" y1="{top + chart_height}" '
            f'x2="{left + chart_width}" y2="{top + chart_height}" class="axis"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" '
            f'y2="{top + chart_height}" class="axis"/>',
            f'<text x="{left + chart_width / 2:.1f}" y="{height - 15}" '
            'text-anchor="middle">Mean minimum TM-score</text>',
            (
                f'<text transform="translate(20 {top + chart_height / 2:.1f}) rotate(-90)" '
                'text-anchor="middle">Mean pocket overlap fraction</text>'
            ),
        )
    )
    colours = {
        "CONSERVED_3D_POCKET_SUPPORTED": "#16794a",
        "THREE_DIMENSIONAL_POCKET_NOT_SUPPORTED": "#b3472d",
        "POCKET_RESIDUE_CONSERVATION_NOT_ASSESSED": "#8b6b1f",
        "INSUFFICIENT_STRUCTURES": "#6b7280",
    }
    for row in plotted:
        x_value = max(0.0, min(1.0, float(row["mean_minimum_tm_score"])))
        y_value = max(
            0.0, min(1.0, float(row["mean_pocket_overlap_fraction"]))
        )
        x = left + x_value * chart_width
        y = top + (1 - y_value) * chart_height
        label = (
            f"{row.get('cluster_id', '')} | {row.get('primary_group_id', '')}"
        )
        colour = colours.get(str(row.get("alignment_status")), "#415a77")
        elements.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{colour}">'
            f"<title>{html.escape(label)}</title></circle>"
        )
    elements.append("</svg>")
    return "".join(elements)


def _table(
    records: Sequence[Mapping[str, Any]],
    columns: Sequence[tuple[str, str]],
    *,
    maximum_rows: int,
) -> str:
    """Render a bounded accessible evidence table."""
    header = "".join(
        f"<th>{html.escape(label)}</th>" for _field, label in columns
    )
    body = []
    for record in records[:maximum_rows]:
        cells = "".join(
            f"<td>{_text(record.get(field))}</td>" for field, _label in columns
        )
        body.append(f"<tr>{cells}</tr>")
    note = (
        f"<p class=\"muted\">Showing {min(len(records), maximum_rows)} of "
        f"{len(records)} rows. Complete evidence is retained in TSV and Parquet.</p>"
    )
    return (
        note
        + f"<div class=\"table-wrap\"><table><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _threshold_table(settings: Mapping[str, Any]) -> str:
    """Render configured decision thresholds and executables."""
    labels = {
        "distance_threshold_angstrom": "Residue distance threshold (Å)",
        "maximum_centroid_distance_angstrom": "Maximum centroid distance (Å)",
        "minimum_pocket_overlap_fraction": "Minimum pocket overlap",
        "minimum_global_tm_score": "Minimum global TM-score",
        "minimum_structural_residue_match_fraction": (
            "Minimum local structural-residue match fraction"
        ),
        "minimum_structural_chemical_group_conservation": (
            "Minimum local chemical-group conservation"
        ),
        "minimum_group_support_fraction": "Minimum group support fraction",
    }
    rows = [
        {"parameter": label, "value": settings.get(field)}
        for field, label in labels.items()
    ]
    return _table(
        rows,
        (("parameter", "Parameter"), ("value", "Configured value")),
        maximum_rows=len(rows),
    )


def render_html_report(
    *,
    summaries: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    residue_matches: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any],
    versions: Mapping[str, str],
    input_inventory: Mapping[str, Mapping[str, Any]],
    validation: Mapping[str, Any],
) -> str:
    """Render the complete structural-alignment report as HTML."""
    group_columns = (
        ("cluster_id", "Discovery cluster"),
        ("primary_group_id", "OrthoFinder group"),
        ("reference_accession", "Reference"),
        ("selected_accession_count", "Selected"),
        ("model_available_accession_count", "Models"),
        ("group_position_support_fraction", "Position support"),
        ("group_support_fraction", "Conserved support"),
        ("mean_minimum_tm_score", "Mean min TM"),
        ("mean_pocket_overlap_fraction", "Mean pocket overlap"),
        ("median_centroid_distance_angstrom", "Median centroid Å"),
        ("mean_structural_residue_match_fraction", "Local match"),
        ("mean_structural_residue_identity_fraction", "Residue identity"),
        (
            "mean_structural_chemical_group_conservation",
            "Chemical conservation",
        ),
        ("position_alignment_status", "Position conclusion"),
        ("alignment_status", "Conservation conclusion"),
    )
    comparison_columns = (
        ("primary_group_id", "OrthoFinder group"),
        ("reference_accession", "Reference"),
        ("mobile_accession", "Member"),
        ("alignment_tool", "Tool"),
        ("minimum_tm_score", "Min TM"),
        ("centroid_distance_angstrom", "Centroid Å"),
        ("symmetric_overlap_fraction", "Pocket overlap"),
        ("structural_residue_match_fraction", "Local match"),
        (
            "structural_chemical_group_conservation",
            "Chemical conservation",
        ),
        ("same_pocket_position_supported", "Same position"),
        ("pocket_structure_conserved", "Conserved pocket"),
        ("reason", "Interpretation"),
    )
    residue_columns = (
        ("primary_group_id", "OrthoFinder group"),
        ("reference_accession", "Reference"),
        ("reference_fasta_position", "Ref FASTA position"),
        ("reference_fasta_residue", "Ref residue"),
        ("mobile_accession", "Member"),
        ("mobile_fasta_position", "Member FASTA position"),
        ("mobile_fasta_residue", "Member residue"),
        ("alignment_tool", "Tool"),
        ("ca_distance_angstrom", "Cα distance Å"),
        ("residue_identity", "Exact identity"),
        ("chemical_group_match", "Chemical match"),
        ("sequence_comparison_status", "Coordinate status"),
    )
    version_rows = [
        {"tool": tool, "version": version}
        for tool, version in sorted(versions.items())
    ]
    input_rows = [
        {
            "input": label,
            "path": details.get("path"),
            "size_bytes": details.get("size_bytes"),
            "sha256": details.get("sha256"),
        }
        for label, details in sorted(input_inventory.items())
    ]
    generated = utc_now()
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARIA E3 structural pocket alignment</title>
<style>
:root{{--ink:#18212b;--blue:#173f5f;--line:#d7dee5;--panel:#f6f9fb;
--green:#16794a;--red:#b3472d;--amber:#8b6b1f}}
body{{font-family:system-ui,-apple-system,sans-serif;max-width:1320px;margin:2rem auto;
padding:0 1.2rem;color:var(--ink);line-height:1.5}}
h1,h2,h3{{color:var(--blue)}} code{{word-break:break-all}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem}}
.card{{border:1px solid var(--line);border-radius:10px;padding:1rem;background:var(--panel)}}
.number{{font-size:2rem;font-weight:750;color:var(--blue)}}
.notice{{border-left:5px solid var(--amber);background:#fff8e8;padding:1rem}}
.supported{{color:var(--green);font-weight:700}}
.not-supported{{color:var(--red);font-weight:700}}
.unavailable{{color:var(--amber);font-weight:700}}
.table-wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:.84rem}}
th,td{{border:1px solid var(--line);padding:.42rem;text-align:left;vertical-align:top}}
th{{background:#eaf1f5;position:sticky;top:0}} .muted{{color:#596673;font-size:.9rem}}
svg{{max-width:100%;height:auto;background:white;border:1px solid var(--line)}}
.grid{{stroke:#e5e9ed;stroke-width:1}} .axis{{stroke:#263645;stroke-width:1.5}}
details{{border:1px solid var(--line);border-radius:8px;padding:.7rem;margin:.8rem 0}}
</style></head><body>
<h1>ARIA E3 structural pocket alignment</h1>
<p>Generated {html.escape(generated)}. This report compares shortlisted predicted structures
after US-align/TM-align superposition. It distinguishes a pocket occupying an equivalent
three-dimensional position from the stronger conclusion that its local structural and
chemical residue environment is conserved.</p>
<p><a href="../interactive/structural_alignment_browser.html"><strong>Open the interactive
structure and pocket alignment browser</strong></a></p>
<div class="notice"><strong>Scientific scope:</strong> these are computational structure and
pocket predictions. They do not establish compound binding, selectivity, E3 activity or
target degradation. Thresholds are configurable and require review on the project data before
structural evidence is allowed to affect prioritisation.</div>
<h2>Run overview</h2><div class="cards">{_cards(summaries)}</div>
<p>Alignment tools: {html.escape('; '.join(sorted(versions)) or 'none')}.
Pairwise alignments: {_text(validation.get('pairwise_alignment_count'))}.
Residue matches: {_text(validation.get('residue_match_count'))};
with exact FASTA coordinates: {_text(validation.get('comparable_residue_match_count'))}.</p>
<h2>Group-level conclusions</h2>
{_table(summaries, group_columns, maximum_rows=250)}
<h2>Global similarity and pocket overlap</h2>
<p>Each point is one candidate group. Hover to see the discovery cluster and OrthoFinder
group identifier.</p>{_scatter_plot(summaries)}
<h2>Pairwise pocket evidence</h2>
{_table(comparisons, comparison_columns, maximum_rows=500)}
<h2>Residue-level structural correspondences</h2>
<p>Rows are conservative mutual-nearest Cα matches within the configured distance threshold.
FASTA positions are reported only where label numbering, range and residue identity were
validated against the exact protein sequence.</p>
{_table(residue_matches, residue_columns, maximum_rows=1000)}
<h2>Decision thresholds</h2>{_threshold_table(settings)}
<details open><summary><strong>Alignment software</strong></summary>
{_table(version_rows, (("tool", "Tool"), ("version", "Version")), maximum_rows=20)}
</details>
<details><summary><strong>Controlled inputs and checksums</strong></summary>
{_table(input_rows, (("input", "Input"), ("path", "Path"), ("size_bytes", "Bytes"),
                     ("sha256", "SHA-256")), maximum_rows=20)}
</details>
<h2>How to interpret the two conclusions</h2>
<ul>
<li><strong>Same pocket position supported</strong>: the whole proteins pass the configured
TM-score threshold and the selected pocket centroids/point clouds occupy a comparable
location after superposition.</li>
<li><strong>Conserved 3D pocket supported</strong>: same-position support is present and the
local mutual-nearest pocket residues also meet structural-match and chemical-group
conservation thresholds, with all enabled aligners agreeing.</li>
<li><strong>Not assessed/insufficient</strong>: missing models, missing mapped pocket residues or
fewer than two eligible structures are not treated as negative biological evidence.</li>
</ul>
</body></html>
"""


def write_html_report(
    *,
    path: Path,
    summaries: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    residue_matches: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any],
    versions: Mapping[str, str],
    input_inventory: Mapping[str, Mapping[str, Any]],
    validation: Mapping[str, Any],
) -> None:
    """Write the self-contained report atomically."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(
        render_html_report(
            summaries=summaries,
            comparisons=comparisons,
            residue_matches=residue_matches,
            settings=settings,
            versions=versions,
            input_inventory=input_inventory,
            validation=validation,
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)
