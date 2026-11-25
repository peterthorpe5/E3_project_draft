"""Check native WhatRes diagnostics, residue identities and pocket denominators."""

from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from e3app import whatres_residues as geometry
from e3app.errors import AppError
from e3app.whatres import run_whatres_command
from test_whatres import PDB, local_whatres, make_mmcif

HEADER = "pdb\tchain\taa\tresnum\tref_count\tresidue_score\tn_outliers\tworst_metric\tworst_score"
ALANINE = "e3_model\tA\tA\t1\t100\t30.25\t2\tclashscore\t6.64"
GLYCINE = "e3_model\tA\tG\t2\t200\t12.25\t0\tbond_N_CA\t2.50"


@pytest.fixture
def measured(*, local_whatres: Path) -> geometry.ResidueReport:
    """Score the two-residue model via an isolated v1.0.0 protocol fixture."""
    return geometry.score_residue_geometry(directory=local_whatres, content=PDB,
                                           filename="native.pdb")


def test_geometry_process_uses_private_native_model_and_space_free_reference(
    *, local_whatres: Path, measured: geometry.ResidueReport,
) -> None:
    """Run the feature binary from private scratch for PDB and mmCIF with the same geometry."""
    assert measured.model_sha256 == measured.scored_pdb_sha256 == sha256(PDB).hexdigest()
    assert measured.whatres_version == "1.0.0"
    assert [row["residue_score"] for row in measured.rows] == [30.25, 12.25]
    assert [row["n_outliers"] for row in measured.rows] == [2, 0]
    assert measured.colour_limit == pytest.approx(29.35)
    cif = make_mmcif()
    other = geometry.score_residue_geometry(
        directory=local_whatres, content=cif, filename="model.cif",
        expected_sha256=sha256(cif).hexdigest(),
    )
    assert other.model_sha256 != other.scored_pdb_sha256 and other.input_format == "mmCIF"
    assert other.rows == measured.rows
    with pytest.raises(AppError, match="SHA-256"):
        geometry.score_residue_geometry(directory=local_whatres, content=cif, filename="model.cif",
                                        expected_sha256=measured.model_sha256)
    assert not list(local_whatres.rglob("local_quality_report.tsv"))


def test_quality_command_failure_and_invalid_options(
    *, local_whatres: Path, tmp_path: Path,
) -> None:
    """Surface recoverable native execution, installation and filesystem failures."""
    with pytest.raises(AppError, match="Could not run"):
        run_whatres_command(argv=[str(tmp_path / "missing")], cwd=tmp_path, scratch=tmp_path)
    options = local_whatres / "data/Options_features.txt"
    options.write_text("<prefix>incorrect;\n", encoding="utf-8")
    with pytest.raises(AppError, match="options"):
        geometry.score_residue_geometry(directory=local_whatres, content=PDB, filename="model.pdb")
    options.unlink()
    with pytest.raises(AppError, match="working files"):
        geometry.score_residue_geometry(directory=local_whatres, content=PDB, filename="model.pdb")


def test_label_aliases_exclude_ambiguous_or_unobserved_and_other_models() -> None:
    """Resolve author offsets and insertion codes independently from the mmCIF label axis."""
    cif = b"""data_fixture
loop_
_atom_site.label_atom_id
_atom_site.pdbx_PDB_model_num
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.label_asym_id
_atom_site.label_seq_id
CA 1 B 12 A L 1
CA 1 B 13 ? L 2
CA 1 B 13 ? L 3
CA 1 B 14 . L .
N 1 B 15 ? L 5
CA 2 B 12 A Z 9
"""
    assert geometry._label_ids(cif=cif) == {("B", 12, "A"): ("L", 1)}
    assert geometry._label_ids(cif=b"data_empty\n_atom_site.label_atom_id CA\n") == {}


def test_coordinate_rows_capture_unassessed_positions_and_chain_breaks(
    *, measured: geometry.ResidueReport, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve native numbering and positions when Cα atoms or continuous bonds are absent."""
    rows = list(measured.rows)
    assert geometry._native_rows(pdb=PDB, aliases={})[0]["label_number"] is None
    missing = dict(rows[1], x=None, y=None, z=None)
    other = dict(rows[1], chain="B", author_number=-4, insertion_code="A")
    report = replace(measured, rows=(rows[0], missing, rows[1], dict(rows[1], x=25), other))
    view = geometry.native_geometry_view(report=report, chain="A")
    assert view["sequence"] == "AGGG" and [p["position"] for p in view["model"]] == [1, 3, 4]
    assert all(point["break_before"] for point in view["model"])
    assert view["untraced_geometry"][0]["residue_score"] == missing["residue_score"]
    other_chain = geometry.native_geometry_view(report=report, chain="B")
    assert other_chain["model"][0]["native_id"] == "B -4A"
    assert geometry.native_geometry_view(report=report, chain="C")["model"] == []
    monkeypatch.setattr(geometry, "MAX_LINKED_RESIDUES", 1)
    with pytest.raises(AppError, match="model residues"):
        geometry._native_rows(pdb=PDB, aliases=None)


@pytest.mark.parametrize("body", [
    "", HEADER, HEADER + "\taa\n" + ALANINE + "\tA",
    HEADER + "\n" + ALANINE.replace("e3_model", "other"),
    HEADER + "\n" + ALANINE.replace("30.25", "nan"),
    HEADER + "\n" + ALANINE.replace("6.64", "-1"),
    HEADER + "\n" + ALANINE.replace("100", "-1"),
    HEADER + "\n" + ALANINE + "\textra", HEADER + "\n" + ALANINE.rsplit("\t", 1)[0],
])
def test_invalid_geometry_report_is_rejected(*, body: str, tmp_path: Path) -> None:
    """Reject a mismatched model, invalid numbers and malformed or duplicate columns."""
    path = tmp_path / "report.tsv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(AppError, match="geometry report"):
        geometry._read_diagnostics(path=path, rows=[], minimum_reference=5)


def test_unavailable_reference_duplicate_keys_and_genuine_zero(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve missingness and avoid guessing identities or assigning rows by order."""
    path = tmp_path / "report.tsv"
    rows = geometry._native_rows(pdb=PDB, aliases=None)
    rows += [dict(rows[1], chain="B"), dict(rows[1], chain="C", status="alternate_conformer"),
             dict(rows[1], author_number=5), dict(rows[1], author_number=5, insertion_code="A"),
             dict(rows[1], chain="D"), dict(rows[1], chain="E")]
    path.write_text("\n".join((HEADER, GLYCINE.replace("200", "4"), ALANINE,
                               GLYCINE.replace("\tA\tG", "\tB\tA"),
                               GLYCINE.replace("\tA\tG", "\tC\tG"),
                               GLYCINE.replace("\tA\tG", "\tD\tG").replace("12.25", "0"))))
    geometry._read_diagnostics(path=path, rows=rows, minimum_reference=5)
    assert [row["status"] for row in rows] == [
        "assessed", "insufficient_reference", "residue_mismatch", "alternate_conformer",
        "ambiguous_number", "ambiguous_number", "assessed", "not_reported",
    ]
    assert rows[1]["reference_count"] == 4 and rows[1]["n_outliers"] is None
    assert rows[-2]["residue_score"] == 0
    path.write_text(HEADER + "\n" + ALANINE + "\n" + ALANINE)
    fresh = geometry._native_rows(pdb=PDB, aliases=None)
    geometry._read_diagnostics(path=path, rows=fresh, minimum_reference=5)
    assert fresh[0]["status"] == "ambiguous_number" and fresh[0]["residue_score"] is None
    monkeypatch.setattr(geometry, "MAX_REPORT_BYTES", 2)
    with pytest.raises(AppError, match="geometry report"):
        geometry._read_diagnostics(path=path, rows=fresh, minimum_reference=5)


def test_link_geometry_requires_hash_chain_identity_number_and_coordinates(
    *, measured: geometry.ResidueReport,
) -> None:
    """Match sequence labels even when author chain and numbering differ, rejecting stale traces."""
    view = geometry.native_geometry_view(report=measured, chain="A")
    evidence = {**view, "pockets": [{"rank": 1, "number": 7, "positions": [1, 2]}]}
    shifted = replace(measured, rows=tuple(
        dict(row, author_number=row["author_number"] + 100, chain="X") for row in measured.rows
    ))
    linked = geometry.link_residue_geometry(evidence=evidence, report=shifted)
    assert linked["pockets"][0]["geometry"]["flagged_positions"] == "1"
    assert "geometry" not in evidence["pockets"][0]
    with pytest.raises(AppError, match="checksums"):
        geometry.link_residue_geometry(evidence={**evidence, "model_sha256": ""}, report=measured)
    for change in ({"chain": "B"}, {"position": 12}, {"x": 18}, {"residue": "W"}):
        with pytest.raises(AppError, match="verify"):
            geometry.link_residue_geometry(evidence={
                **evidence, "model": [dict(evidence["model"][0], **change)],
            }, report=measured)
    with pytest.raises(AppError, match="verify"):
        geometry.link_residue_geometry(evidence={**evidence, "model": []}, report=measured)


def test_pocket_geometry_overlap_coverage_ties_and_missing_values() -> None:
    """Keep denominators explicit and tie-break peaks on the lowest mapped position."""
    model = [
        {"position": 4, "residue_score": 20, "n_outliers": 3, "plddt": None},
        {"position": 1, "residue_score": 20, "n_outliers": 0, "plddt": 90},
        {"position": 3, "residue_score": None, "n_outliers": None, "plddt": 70},
    ]
    pockets = [{"number": i, "rank": i, "positions": positions} for i, positions in
               enumerate(([4, 1, 1, 3], [3, 4], [3], []), start=1)]
    first, overlapping, missing, empty = geometry.pocket_geometry(pockets=pockets, model=model)
    assert first["positions"] == [1, 3, 4]
    assert first["geometry"] == {
        "mapped_residues": 3, "assessed_residues": 2, "flagged_residues": 1,
        "outlier_count": 3, "flagged_percent_of_assessed": 50, "median_residue_score": 20,
        "peak_residue_score": 20, "peak_position": 1, "flagged_positions": "4",
        "plddt_residues": 2, "median_plddt": 80,
    }
    assert overlapping["geometry"]["flagged_percent_of_assessed"] == 100
    for pocket in (missing, empty):
        assert pocket["geometry"]["median_residue_score"] is None
        assert pocket["geometry"]["flagged_percent_of_assessed"] is None
        assert pocket["geometry"]["outlier_count"] is None


@pytest.mark.skipif(not os.getenv("E3_WHATRES_TEST_DIR"), reason="requires native WhatRes fixtures")
def test_author_reference_native_residue_values() -> None:
    """Compare the real extractor with values independently read from its native quality report."""
    directory = Path(os.environ["E3_WHATRES_TEST_DIR"]).resolve()
    path = directory / "tests/structures/AF-P02787.pdb"
    report = geometry.score_residue_geometry(
        directory=directory, content=path.read_bytes(), filename=path.name,
    )
    assert len(report.rows) == 698 and all(row["status"] == "assessed" for row in report.rows)
    for position, aa, surprise, flags, metric in [
        (1, "M", 38.35, 0, "clashscore"), (2, "R", 67.18, 2, "rama2D"),
        (89, "A", 40.39, 0, "clashscore"), (429, "E", 42.19, 1, "clashscore"),
    ]:
        row = report.rows[position - 1]
        assert (row["author_number"], row["residue"]) == (position, aa)
        assert (row["residue_score"], row["n_outliers"], row["worst_metric"]) == (
            surprise, flags, metric,
        )
