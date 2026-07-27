"""Tests for static and interactive structural-alignment reports."""

from __future__ import annotations

from pathlib import Path

from e3structalign.interactive import render_pair_viewer, write_browser_index
from e3structalign.models import AtomCoordinate, Transform
from e3structalign.reporting import render_html_report


def test_static_report_contains_graphics_evidence_and_escaped_text() -> None:
    """The scientific report embeds graphics, thresholds and safe evidence tables."""
    summaries = [
        {
            "cluster_id": "cluster<&>",
            "primary_group_type": "ORTHOGROUP",
            "primary_group_id": "OG0001",
            "reference_accession": "P1",
            "selected_accession_count": 2,
            "model_available_accession_count": 2,
            "group_position_support_fraction": 1.0,
            "group_support_fraction": 1.0,
            "mean_minimum_tm_score": 0.9,
            "mean_pocket_overlap_fraction": 0.8,
            "median_centroid_distance_angstrom": 1.2,
            "mean_structural_residue_match_fraction": 0.8,
            "mean_structural_residue_identity_fraction": 0.6,
            "mean_structural_chemical_group_conservation": 0.9,
            "three_dimensional_pocket_score": 0.85,
            "position_alignment_status": "SAME_3D_POCKET_POSITION_SUPPORTED",
            "alignment_status": "CONSERVED_3D_POCKET_SUPPORTED",
        }
    ]
    comparisons = [
        {
            **summaries[0],
            "mobile_accession": "P2",
            "alignment_tool": "US-align",
            "minimum_tm_score": 0.9,
            "centroid_distance_angstrom": 1.2,
            "symmetric_overlap_fraction": 0.8,
            "structural_residue_match_fraction": 0.8,
            "structural_chemical_group_conservation": 0.9,
            "same_pocket_position_supported": True,
            "pocket_structure_conserved": True,
            "reason": "supported",
        }
    ]
    report = render_html_report(
        summaries=summaries,
        comparisons=comparisons,
        residue_matches=[],
        settings={
            "distance_threshold_angstrom": 4.0,
            "maximum_centroid_distance_angstrom": 8.0,
            "minimum_pocket_overlap_fraction": 0.5,
            "minimum_global_tm_score": 0.5,
            "minimum_structural_residue_match_fraction": 0.5,
            "minimum_structural_chemical_group_conservation": 0.6,
            "minimum_group_support_fraction": 0.75,
        },
        versions={"US-align": "1", "TM-align": "2"},
        input_inventory={
            "selected": {
                "path": "/controlled/selected.parquet",
                "size_bytes": 10,
                "sha256": "a" * 64,
            }
        },
        validation={
            "pairwise_alignment_count": 2,
            "residue_match_count": 4,
            "comparable_residue_match_count": 4,
        },
    )
    assert "<svg" in report
    assert "Mean minimum TM-score" in report
    assert "cluster&lt;&amp;&gt;" in report
    assert "Open the interactive" in report
    assert "Minimum local chemical-group conservation" in report


def test_pair_viewer_and_index_are_standalone(tmp_path: Path) -> None:
    """The rotatable browser embeds coordinates and links pair pages locally."""
    atoms = [
        AtomCoordinate("A", "1", "A", "1", "", "ALA", 0.0, 0.0, 0.0),
        AtomCoordinate("A", "2", "A", "2", "", "CYS", 0.0, 2.0, 0.0),
    ]
    viewer = render_pair_viewer(
        title="P1 < P2",
        reference_accession="P1",
        mobile_accession="P2",
        alignment_tool="TM-align",
        reference_atoms=atoms,
        mobile_atoms=atoms,
        reference_pocket_coordinates={(0.0, 0.0, 0.0)},
        mobile_pocket_coordinates={(0.0, 2.0, 0.0)},
        transform=Transform(
            translation=(1.0, 0.0, 0.0),
            rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ),
        metrics={"Same pocket": True},
    )
    assert "P1 &lt; P2" in viewer
    assert '"pocket":true' in viewer
    assert "Drag to rotate" in viewer
    assert "https://" not in viewer
    index = tmp_path / "interactive" / "structural_alignment_browser.html"
    write_browser_index(
        path=index,
        alignments=[
            {
                "cluster_id": "c1",
                "primary_group_type": "ORTHOGROUP",
                "primary_group_id": "OG1",
                "reference_accession": "P1",
                "mobile_accession": "P2",
                "alignment_tool": "TM-align",
                "interactive_view_relative_path": (
                    "interactive/pairs/tm-align/c1/P1__P2.html"
                ),
            }
        ],
        summaries=[
            {
                "cluster_id": "c1",
                "primary_group_type": "ORTHOGROUP",
                "primary_group_id": "OG1",
                "position_alignment_status": "SUPPORTED",
                "alignment_status": "CONSERVED",
            }
        ],
    )
    content = index.read_text(encoding="utf-8")
    assert 'href="pairs/tm-align/c1/P1__P2.html"' in content
    assert "No network connection is required" in content
