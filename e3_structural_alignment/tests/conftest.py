"""Shared fixtures for structural-alignment tests."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from e3structalign.io_utils import sha256_file, write_tsv


def _pdb_line(
    serial: int,
    residue: int,
    x: float,
    y: float,
    z: float,
) -> str:
    """Return one fixed-width PDB C-alpha record."""
    return (
        f"ATOM  {serial:5d}  CA  ALA A{residue:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 90.00           C\n"
    )


@pytest.fixture
def structural_inputs(tmp_path: Path) -> dict[str, Path]:
    """Create two translated models and matching input TSVs."""
    reference = tmp_path / "P1.cif.pdb"
    mobile = tmp_path / "P2.pdb"
    reference.write_text(
        _pdb_line(1, 1, 0.0, 0.0, 0.0)
        + _pdb_line(2, 2, 0.0, 2.0, 0.0),
        encoding="utf-8",
    )
    mobile.write_text(
        _pdb_line(1, 1, 10.0, 0.0, 0.0)
        + _pdb_line(2, 2, 10.0, 2.0, 0.0),
        encoding="utf-8",
    )
    selected = tmp_path / "selected.tsv"
    selected_rows = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "candidate_accession": "P1",
            "species_column": "species_1",
            "pocket_number": 1,
            "druggability_score": 0.9,
            "mapping_fraction": 1.0,
            "conservative_fraction_plddt_ge_70": 1.0,
            "predictor_agreement": "true",
            "structural_evidence_status": "SELECTED_HIGH_CONFIDENCE",
        },
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "candidate_accession": "P2",
            "species_column": "species_2",
            "pocket_number": 1,
            "druggability_score": 0.8,
            "mapping_fraction": 1.0,
            "conservative_fraction_plddt_ge_70": 1.0,
            "predictor_agreement": "true",
            "structural_evidence_status": "SELECTED_HIGH_CONFIDENCE",
        },
    ]
    write_tsv(selected, selected_rows, tuple(selected_rows[0]))
    mappings = tmp_path / "mappings.tsv"
    mapping_rows = [
        {
            "accession": accession,
            "pocket_number": 1,
            "mapping_status": "MAPPED",
            "model_label_chain": "A",
            "model_label_seq_id": residue,
            "model_auth_chain": "A",
            "model_auth_seq_id": residue,
            "model_insertion_code": "",
        }
        for accession in ("P1", "P2")
        for residue in (1, 2)
    ]
    write_tsv(mappings, mapping_rows, tuple(mapping_rows[0]))
    sequence_coordinates = tmp_path / "sequence_coordinates.tsv"
    sequence_coordinate_rows = [
        {
            "candidate_accession": accession,
            "pocket_number": 1,
            "structure_label_chain": "A",
            "structure_label_seq_id": residue,
            "structure_auth_chain": "A",
            "structure_auth_seq_id": residue,
            "structure_insertion_code": "",
            "structure_residue_name": "ALA",
            "fasta_position": residue,
            "fasta_residue": "A",
            "sequence_coordinate_status": "MAPPED_EXACT",
        }
        for accession in ("P1", "P2")
        for residue in (1, 2)
    ]
    write_tsv(
        sequence_coordinates,
        sequence_coordinate_rows,
        tuple(sequence_coordinate_rows[0]),
    )
    assets = tmp_path / "assets.tsv"
    asset_rows = [
        {
            "accession": "P1",
            "path": reference,
            "sha256": sha256_file(reference),
        },
        {
            "accession": "P2",
            "path": mobile,
            "sha256": sha256_file(mobile),
        },
    ]
    write_tsv(assets, asset_rows, tuple(asset_rows[0]))
    executable = tmp_path / "USalign"
    executable.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

if len(sys.argv) == 1:
    print("US-align (Version 20241201)")
    raise SystemExit(0)
matrix = pathlib.Path(sys.argv[sys.argv.index("-m") + 1])
matrix.write_text(
    "i t(i) u(i,1) u(i,2) u(i,3)\\n"
    "0 -10.0 1.0 0.0 0.0\\n"
    "1 0.0 0.0 1.0 0.0\\n"
    "2 0.0 0.0 0.0 1.0\\n",
    encoding="utf-8",
)
print("Aligned length= 2, RMSD= 0.00, Seq_ID=n_identical/n_aligned= 1.000")
print("TM-score= 1.00000 (if normalized by length of Chain_1)")
print("TM-score= 1.00000 (if normalized by length of Chain_2)")
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    tmalign = tmp_path / "TMalign"
    tmalign.write_text(
        executable.read_text(encoding="utf-8").replace("US-align", "TM-align"),
        encoding="utf-8",
    )
    tmalign.chmod(tmalign.stat().st_mode | stat.S_IXUSR)
    return {
        "selected": selected,
        "mappings": mappings,
        "sequence_coordinates": sequence_coordinates,
        "assets": assets,
        "reference": reference,
        "mobile": mobile,
        "executable": executable,
        "tmalign": tmalign,
        "output": tmp_path / "result",
    }


@pytest.fixture
def review_run(
    tmp_path: Path,
    structural_inputs: dict[str, Path],
) -> dict[str, Path]:
    """Create one minimal completed workflow run for visual-review tests."""
    run_root = tmp_path / "completed_run"
    stage09_tables = run_root / "09_ligandability" / "tables"
    stage09_tables.mkdir(parents=True)
    stage10 = run_root / "10_integrated_resource" / "final_results"
    stage10.mkdir(parents=True)
    stage09b = (
        run_root
        / "09b_structural_alignment"
        / "structural_alignment"
        / "tables"
    )
    stage09b.mkdir(parents=True)
    shortlist_rows = [
        {
            "final_evolutionary_rank": 1,
            "prestructure_evolutionary_group_rank": 2,
            "lead_cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "grant_aligned_prediction_status": "STRUCTURAL_SUPPORT",
            "grant_aligned_prestructure_pass": True,
            "grant_aligned_base_pass": True,
            "grant_aligned_final_pass": True,
            "conservation_status": "CONSERVED_POCKET_SUPPORTED",
            "three_dimensional_position_status": (
                "SAME_3D_POCKET_POSITION_SUPPORTED"
            ),
            "three_dimensional_alignment_status": (
                "CONSERVED_3D_POCKET_SUPPORTED"
            ),
            "sensitivity_position_alignment_status": (
                "SAME_3D_POCKET_POSITION_SUPPORTED"
            ),
            "sensitivity_alignment_status": "CONSERVED_3D_POCKET_SUPPORTED",
            "final_score": 0.91,
        }
    ]
    write_tsv(
        stage10 / "top_50_computational_review_shortlist.tsv",
        shortlist_rows,
        tuple(shortlist_rows[0]),
    )
    selected_rows = []
    ranked_rows = []
    for accession, species, score in (
        ("P1", "species_1", 0.9),
        ("P2", "species_2", 0.8),
    ):
        base = {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "candidate_accession": accession,
            "species_column": species,
            "pocket_number": 1,
            "druggability_score": score,
            "mapping_fraction": 1.0,
            "conservative_fraction_plddt_ge_70": 1.0,
            "predictor_agreement": True,
            "structural_evidence_status": "SELECTED_HIGH_CONFIDENCE",
        }
        selected_rows.append(base)
        ranked_rows.append(
            {
                **base,
                "selection_rank": 1,
                "is_strict_selected": True,
            }
        )
        ranked_rows.append(
            {
                **base,
                "pocket_number": 2,
                "druggability_score": score - 0.1,
                "selection_rank": 2,
                "is_strict_selected": False,
            }
        )
    write_tsv(
        stage09_tables / "selected_pockets.tsv",
        selected_rows,
        tuple(selected_rows[0]),
    )
    write_tsv(
        stage09_tables / "ranked_member_pockets.tsv",
        ranked_rows,
        tuple(ranked_rows[0]),
    )
    coordinate_rows = [
        {
            "candidate_accession": accession,
            "pocket_number": pocket_number,
            "structure_label_chain": "A",
            "structure_label_seq_id": residue,
            "structure_auth_chain": "A",
            "structure_auth_seq_id": residue,
            "structure_insertion_code": "",
            "structure_residue_name": "ALA",
            "fasta_position": residue,
            "fasta_residue": "A",
            "sequence_coordinate_status": "MAPPED_EXACT",
        }
        for accession in ("P1", "P2")
        for pocket_number, residue in ((1, 1), (2, 2))
    ]
    write_tsv(
        stage09_tables / "ranked_pocket_sequence_coordinates.tsv",
        coordinate_rows,
        tuple(coordinate_rows[0]),
    )
    asset_rows = [
        {
            "accession": "P1",
            "path": structural_inputs["reference"],
            "sha256": sha256_file(structural_inputs["reference"]),
        },
        {
            "accession": "P2",
            "path": structural_inputs["mobile"],
            "sha256": sha256_file(structural_inputs["mobile"]),
        },
    ]
    write_tsv(
        stage09_tables / "reused_asset_manifest.tsv",
        asset_rows,
        tuple(asset_rows[0]),
    )
    alignment = (
        run_root
        / "09_ligandability"
        / "alignments"
        / "cluster_1__OG0001"
        / "aligned.fasta"
    )
    alignment.parent.mkdir(parents=True)
    alignment.write_text(">P1\nAA\n>P2\nAA\n", encoding="utf-8")
    structural_rows = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "reference_accession": "P1",
            "selected_accession_count": 2,
            "model_available_accession_count": 2,
            "aligned_accession_count": 2,
            "position_supported_accession_count": 2,
            "supported_accession_count": 2,
            "group_position_support_fraction": 1.0,
            "group_support_fraction": 1.0,
            "mean_minimum_tm_score": 1.0,
            "mean_pocket_overlap_fraction": 1.0,
            "median_centroid_distance_angstrom": 0.0,
            "position_alignment_status": "SAME_3D_POCKET_POSITION_SUPPORTED",
            "alignment_status": "CONSERVED_3D_POCKET_SUPPORTED",
        }
    ]
    write_tsv(
        stage09b / "structural_alignment_summary.tsv",
        structural_rows,
        tuple(structural_rows[0]),
    )
    sensitivity_group_rows = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "member_pocket_top_k": 5,
            "sensitivity_group_position_support_fraction": 1.0,
            "sensitivity_group_support_fraction": 1.0,
            "position_rescued_accession_count": 0,
            "conservation_rescued_accession_count": 0,
            "sensitivity_position_alignment_status": (
                "SAME_3D_POCKET_POSITION_SUPPORTED"
            ),
            "sensitivity_alignment_status": "CONSERVED_3D_POCKET_SUPPORTED",
        }
    ]
    write_tsv(
        stage09b / "structural_pocket_sensitivity_group_summary.tsv",
        sensitivity_group_rows,
        tuple(sensitivity_group_rows[0]),
    )
    sensitivity_member_rows = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "mobile_species": "species_2",
            "mobile_accession": "P2",
            "agreed_pocket_number": 1,
            "agreed_pocket_rank": 1,
            "position_rescued_by_alternative_pocket": False,
            "conservation_rescued_by_alternative_pocket": False,
        }
    ]
    write_tsv(
        stage09b / "structural_pocket_sensitivity_member_summary.tsv",
        sensitivity_member_rows,
        tuple(sensitivity_member_rows[0]),
    )
    viewer_relative = (
        "interactive/pairs/us-align/cluster_1__OG0001/P1__P2.html"
    )
    viewer = (
        stage09b.parent
        / "interactive"
        / "pairs"
        / "us-align"
        / "cluster_1__OG0001"
        / "P1__P2.html"
    )
    viewer.parent.mkdir(parents=True)
    viewer.write_text(
        "<!doctype html><html><body><canvas id='viewer'></canvas>"
        "<p>validated pairwise superposition</p></body></html>",
        encoding="utf-8",
    )
    alignment_rows = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "reference_accession": "P1",
            "mobile_accession": "P2",
            "reference_species": "species_1",
            "mobile_species": "species_2",
            "alignment_tool": "US-align",
            "status": "COMPLETE",
            "minimum_tm_score": 1.0,
            "rmsd_angstrom": 0.0,
            "interactive_view_relative_path": viewer_relative,
        }
    ]
    write_tsv(
        stage09b / "structural_alignments.tsv",
        alignment_rows,
        tuple(alignment_rows[0]),
    )
    comparison_rows = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "reference_accession": "P1",
            "mobile_accession": "P2",
            "reference_species": "species_1",
            "mobile_species": "species_2",
            "alignment_tool": "US-align",
            "centroid_distance_angstrom": 0.0,
            "symmetric_overlap_fraction": 1.0,
            "structural_residue_match_fraction": 1.0,
            "structural_chemical_group_conservation": 1.0,
            "same_pocket_position_supported": True,
            "pocket_structure_conserved": True,
            "status": "ASSESSED",
        }
    ]
    write_tsv(
        stage09b / "pocket_comparisons.tsv",
        comparison_rows,
        tuple(comparison_rows[0]),
    )
    return {
        "run_root": run_root,
        "output": tmp_path / "review_report",
        "alignment": alignment,
        "shortlist": stage10 / "top_50_computational_review_shortlist.tsv",
    }
