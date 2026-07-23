"""Tests for structure parsing and pocket geometry."""

from __future__ import annotations

from pathlib import Path

import pytest

from e3structalign.errors import InputValidationError
from e3structalign.models import AtomCoordinate, ResidueLocator, Transform
from e3structalign.structure_io import (
    _as_list,
    centroid,
    parse_ca_atoms,
    parse_mmcif_ca_atoms,
    parse_pdb_ca_atoms,
    pocket_coordinates,
    pocket_geometry,
    transform_coordinates,
)


def test_pdb_parsing_locator_selection_and_geometry(
    structural_inputs: dict[str, Path],
) -> None:
    """PDB C-alpha residues transform into a coincident pocket."""
    reference_atoms = parse_ca_atoms(structural_inputs["reference"])
    mobile_atoms = parse_ca_atoms(structural_inputs["mobile"])
    locators = [
        ResidueLocator("A", "1", "A", "1", ""),
        ResidueLocator("A", "2", "A", "2", ""),
    ]
    reference = pocket_coordinates(reference_atoms, locators)
    mobile = pocket_coordinates(mobile_atoms, locators)
    transform = Transform(
        translation=(-10.0, 0.0, 0.0),
        rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )
    transformed = transform_coordinates(mobile, transform)
    assert transformed == reference
    assert centroid(reference) == (0.0, 1.0, 0.0)
    metrics = pocket_geometry(
        reference_coordinates=reference,
        transformed_mobile_coordinates=transformed,
        distance_threshold_angstrom=4.0,
    )
    assert metrics["centroid_distance_angstrom"] == 0.0
    assert metrics["symmetric_overlap_fraction"] == 1.0


def test_minimal_mmcif_parsing(tmp_path: Path) -> None:
    """The mmCIF parser retains label and author residue identifiers."""
    path = tmp_path / "model.cif"
    path.write_text(
        """data_test
loop_
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.pdbx_PDB_model_num
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
CA . A 1 A 10 ? 1 1.0 2.0 3.0
""",
        encoding="utf-8",
    )
    atoms = parse_mmcif_ca_atoms(path)
    assert atoms[0].label_seq_id == "1"
    assert atoms[0].auth_seq_id == "10"
    assert atoms[0].coordinate == (1.0, 2.0, 3.0)


def test_structure_and_geometry_failures(tmp_path: Path) -> None:
    """Unsupported, empty and zero-coordinate inputs fail clearly."""
    unsupported = tmp_path / "model.xyz"
    unsupported.write_text("x", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Unsupported"):
        parse_ca_atoms(unsupported)
    with pytest.raises(InputValidationError, match="centroid"):
        centroid([])
    with pytest.raises(InputValidationError, match="Both pockets"):
        pocket_geometry(
            reference_coordinates=[],
            transformed_mobile_coordinates=[(0.0, 0.0, 0.0)],
            distance_threshold_angstrom=4.0,
        )


def test_pdb_and_mmcif_validation_branches(tmp_path: Path) -> None:
    """Malformed coordinate records and incomplete mmCIF columns fail closed."""
    empty_pdb = tmp_path / "empty.pdb"
    empty_pdb.write_text("HEADER empty\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no C-alpha"):
        parse_pdb_ca_atoms(empty_pdb)

    malformed_pdb = tmp_path / "malformed.pdb"
    malformed_pdb.write_text(
        "ATOM      1  CA  ALA A   1       broken  0.000   0.000\n",
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError, match="Malformed PDB"):
        parse_pdb_ca_atoms(malformed_pdb)

    missing_column = tmp_path / "missing_column.cif"
    missing_column.write_text("data_test\n_entry.id test\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="label_atom_id"):
        parse_mmcif_ca_atoms(missing_column)

    non_numeric = tmp_path / "non_numeric.cif"
    non_numeric.write_text(
        """data_test
loop_
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.pdbx_PDB_model_num
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
CA . A 1 A 1 ? 1 bad 2.0 3.0
""",
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError, match="Non-numeric"):
        parse_mmcif_ca_atoms(non_numeric)
    with pytest.raises(InputValidationError, match="column length"):
        _as_list(["one", "two"], 3)


def test_ambiguous_and_author_residue_matching() -> None:
    """Author identifiers work and conflicting matches are rejected."""
    atoms = [
        AtomCoordinate("A", "1", "X", "10", "", "ALA", 0.0, 0.0, 0.0),
        AtomCoordinate("B", "2", "X", "10", "", "ALA", 5.0, 0.0, 0.0),
    ]
    author_locator = ResidueLocator("", "", "X", "10", "")
    with pytest.raises(InputValidationError, match="multiple"):
        pocket_coordinates(atoms, [author_locator])
    exact = ResidueLocator("", "", "X", "10", "")
    assert pocket_coordinates(atoms[:1], [exact]) == [(0.0, 0.0, 0.0)]
