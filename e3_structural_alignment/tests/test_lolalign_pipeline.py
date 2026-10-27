"""LoL-align participates in the structural workflow with separate score fields."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from e3structalign.io_utils import read_records
from e3structalign.errors import NoAlignmentFoundError, StructuralAlignmentError
from e3structalign.models import Transform, USAlignResult
from e3structalign.pipeline import AlignmentSettings, run_pipeline
from e3structalign.structure_io import parse_ca_atoms


def test_three_method_consensus_and_separate_lol_scores(*, structural_inputs, monkeypatch) -> None:
    """All three methods contribute while only LoL-align rows receive LoL scores."""
    monkeypatch.setattr("e3structalign.pipeline.foldseek_version", lambda **kwargs: "revision")

    def aligned(*, matrix_path: Path, stdout_path: Path, **kwargs) -> USAlignResult:
        """Return the known translation between the structural fixture models."""
        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        matrix_path.write_text(data="0 -10 1 0 0\n1 0 0 1 0\n2 0 0 0 1\n", encoding="utf-8")
        stdout_path.write_text(data="LoL-align fixture", encoding="utf-8")
        return USAlignResult(
            aligned_length=2, rmsd_angstrom=0.0, sequence_identity=1.0,
            tm_score_mobile_normalised=1.0, tm_score_reference_normalised=1.0,
            transform=Transform(
                translation=(-10.0, 0.0, 0.0),
                rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ), version="revision", alignment_scope="local",
            lol_normalised_score=0.9, lol_homology_probability=0.99,
        )

    monkeypatch.setattr("e3structalign.pipeline.run_lolalign", aligned)
    manifest_path = run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
        pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
        asset_manifest_path=structural_inputs["assets"], output_dir=structural_inputs["output"],
        settings=AlignmentSettings(
            usalign_executable=str(structural_inputs["executable"]),
            tmalign_executable=str(structural_inputs["tmalign"]), run_lolalign=True,
        ), resume=False, force=False, verbose=False,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["alignment_tools"] == ["US-align", "TM-align", "LoL-align"]
    rows = read_records(structural_inputs["output"] / "tables" / "structural_alignments.parquet")
    mobile_rows = [row for row in rows if row["status"] == "COMPLETE"]
    assert len(mobile_rows) == 3
    for row in mobile_rows:
        if row["alignment_tool"] == "LoL-align":
            assert row["lol_normalised_score"] == 0.9
            assert row["lol_homology_probability"] == 0.99
            assert row["alignment_scope"] == "local"
        else:
            assert row["lol_normalised_score"] is None
    summary = read_records(
        structural_inputs["output"] / "tables" / "structural_alignment_summary.parquet"
    )[0]
    assert summary["alignment_tool_count"] == 3
    assert summary["alignment_status"] == "CONSERVED_3D_POCKET_SUPPORTED"
    assert summary["pairwise_tool_agreement_fraction"] == 1.0


def test_local_no_hit_is_explicit_and_cannot_pass_consensus(
    *, structural_inputs, monkeypatch,
) -> None:
    """Keep an empty local result unassessed, with no invented transform or scores."""
    monkeypatch.setattr("e3structalign.pipeline.foldseek_version", lambda **kwargs: "revision")

    def no_hit(*, stdout_path: Path, **kwargs):
        """Simulate a successful local command with no returned correspondence."""
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(data="Successful search, zero alignments", encoding="utf-8")
        raise NoAlignmentFoundError("No local correspondence")

    monkeypatch.setattr("e3structalign.pipeline.run_lolalign", no_hit)
    run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
        pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
        asset_manifest_path=structural_inputs["assets"], output_dir=structural_inputs["output"],
        settings=AlignmentSettings(run_usalign=False, run_tmalign=False, run_lolalign=True),
        resume=False, force=False, verbose=False,
    )
    rows = read_records(structural_inputs["output"] / "tables" / "structural_alignments.parquet")
    no_alignment = next(row for row in rows if row["status"] == "NO_ALIGNMENT_FOUND")
    assert no_alignment["matrix_relative_path"] == ""
    assert no_alignment["minimum_tm_score"] is None
    assert no_alignment["lol_normalised_score"] is None
    summary = read_records(
        structural_inputs["output"] / "tables" / "structural_alignment_summary.parquet"
    )[0]
    assert summary["model_available_accession_count"] == 2
    assert summary["aligned_accession_count"] == 1
    assert summary["position_alignment_status"] != "SAME_3D_POCKET_POSITION_SUPPORTED"


def test_lolalign_rejects_unselected_multiple_chains(*, structural_inputs, monkeypatch) -> None:
    """Do not silently select one chain of a multimer when the workflow expects a monomer."""
    monkeypatch.setattr("e3structalign.pipeline.foldseek_version", lambda **kwargs: "revision")

    def multichain(path):
        """Represent an input structure with an additional C-alpha chain."""
        atoms = parse_ca_atoms(path=path)
        return atoms + [replace(atoms[0], label_chain="B", auth_chain="B")]

    monkeypatch.setattr("e3structalign.pipeline.parse_ca_atoms", multichain)
    with pytest.raises(StructuralAlignmentError, match="single-chain"):
        run_pipeline(
            selected_pockets_path=structural_inputs["selected"],
            pocket_residue_mappings_path=structural_inputs["mappings"],
            asset_manifest_path=structural_inputs["assets"], output_dir=structural_inputs["output"],
            settings=AlignmentSettings(run_usalign=False, run_tmalign=False, run_lolalign=True),
            resume=False, force=False, verbose=False,
        )
