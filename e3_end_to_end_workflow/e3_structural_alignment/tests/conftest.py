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
