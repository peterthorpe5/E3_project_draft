"""Tabular I/O, checksum and structure-resolution tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from conftest import write_pdb
from e3chemistry.errors import InputValidationError
from e3chemistry.io_utils import (
    read_records,
    read_tsv,
    require_columns,
    sha256_file,
    write_json,
    write_records,
    write_tsv,
)
from e3chemistry.structures import (
    load_pocket_residues,
    mapped_residue_locators,
    resolve_structure_assets,
)


def test_tsv_json_and_checksum_helpers(tmp_path: Path) -> None:
    """Atomic helpers must preserve tabs, booleans and stable checksums."""
    table = tmp_path / "table.tsv"
    write_tsv(
        path=table,
        records=[{"name": "A", "flag": True, "missing": None}],
        fieldnames=("name", "flag", "missing"),
    )
    assert read_tsv(table) == [{"name": "A", "flag": "true", "missing": ""}]
    assert sha256_file(table) == hashlib.sha256(table.read_bytes()).hexdigest()
    payload = tmp_path / "payload.json"
    write_json(path=payload, payload={"status": "ok"})
    assert '"status": "ok"' in payload.read_text(encoding="utf-8")


def test_matching_tsv_and_parquet_round_trip(tmp_path: Path) -> None:
    """Published Parquet must contain the same scientific rows as TSV."""
    tsv_path = tmp_path / "table.tsv"
    parquet_path = tmp_path / "table.parquet"
    write_records(
        tsv_path=tsv_path,
        parquet_path=parquet_path,
        records=[{"name": "A", "score": 0.5}],
        fieldnames=("name", "score"),
    )

    assert read_records(parquet_path)[0]["name"] == "A"
    assert float(read_records(parquet_path)[0]["score"]) == pytest.approx(0.5)


def test_empty_parquet_retains_schema(tmp_path: Path) -> None:
    """Prepare-only fragment tables must remain valid empty Parquet authorities."""
    parquet_path = tmp_path / "empty.parquet"
    write_records(
        tsv_path=tmp_path / "empty.tsv",
        parquet_path=parquet_path,
        records=[],
        fieldnames=("fragment_id", "score"),
    )

    assert read_records(parquet_path) == []


def test_input_validation_helpers_reject_malformed_tables(tmp_path: Path) -> None:
    """Missing headers, columns and unsupported suffixes must be explicit errors."""
    empty = tmp_path / "empty.tsv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(InputValidationError, match="missing or empty"):
        read_tsv(empty)
    with pytest.raises(InputValidationError, match="missing required columns"):
        require_columns(records=[{"a": 1}], required=("b",), label="test")
    unknown = tmp_path / "input.csv"
    unknown.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="TSV or Parquet"):
        read_records(unknown)
    headerless = tmp_path / "headerless.tsv"
    headerless.write_text("\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no header"):
        read_tsv(headerless)
    with pytest.raises(InputValidationError, match="contains no records"):
        require_columns(records=[], required=("a",), label="empty test")
    with pytest.raises(InputValidationError, match="Parquet input is missing"):
        read_records(tmp_path / "missing.parquet")
    invalid_parquet = tmp_path / "invalid.parquet"
    invalid_parquet.write_text("not parquet\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Could not read Parquet"):
        read_records(invalid_parquet)


def test_invalid_parquet_publication_is_atomic(tmp_path: Path) -> None:
    """DuckDB publication errors must remove the temporary Parquet."""
    with pytest.raises(InputValidationError, match="Could not publish Parquet"):
        write_records(
            tsv_path=tmp_path / "duplicate.tsv",
            parquet_path=tmp_path / "duplicate.parquet",
            records=[],
            fieldnames=("duplicate", "duplicate"),
        )
    assert not (tmp_path / ".duplicate.parquet.partial").exists()


def test_structure_assets_locators_and_residue_loading(tmp_path: Path) -> None:
    """Mapped author residue locators must resolve against a validated PDB."""
    structure = write_pdb(tmp_path / "model.pdb")
    digest = sha256_file(structure)
    assets = resolve_structure_assets(
        [{"accession": "p00001", "path": structure, "sha256": digest}]
    )
    mappings = [
        {
            "accession": "P00001",
            "pocket_number": "1",
            "mapping_status": "MAPPED",
            "model_auth_chain": "A",
            "model_auth_seq_id": "1",
            "model_insertion_code": "",
        },
        {
            "accession": "P00001",
            "pocket_number": "1",
            "mapping_status": "UNMAPPED",
            "model_auth_chain": "A",
            "model_auth_seq_id": "99",
            "model_insertion_code": "",
        },
    ]
    locators = mapped_residue_locators(
        records=mappings,
        accession="P00001",
        pocket_number=1,
    )
    residues = load_pocket_residues(
        asset=assets["P00001"],
        pocket_number=1,
        locators=locators,
    )

    assert len(locators) == 1
    assert residues[0].residue_name == "LYS"
    assert "NZ" in residues[0].atoms


def test_structure_asset_checksum_and_conflict_fail_closed(tmp_path: Path) -> None:
    """Changed or ambiguous structures cannot enter the chemistry hand-off."""
    first = write_pdb(tmp_path / "first.pdb")
    second = write_pdb(tmp_path / "second.pdb")
    second.write_text(second.read_text(encoding="utf-8") + "REMARK changed\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="checksum mismatch"):
        resolve_structure_assets(
            [{"accession": "P1", "path": first, "sha256": "0" * 64}]
        )
    with pytest.raises(InputValidationError, match="conflicting structures"):
        resolve_structure_assets(
            [
                {"accession": "P1", "path": first, "sha256": sha256_file(first)},
                {"accession": "P1", "model_path": second, "sha256": sha256_file(second)},
            ]
        )


def test_unusable_assets_and_malformed_mapping_rows_fail_closed(tmp_path: Path) -> None:
    """Empty accessions, missing models and invalid pocket IDs cannot be selected."""
    unsupported = tmp_path / "model.txt"
    unsupported.write_text("not a structure\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no usable structure"):
        resolve_structure_assets(
            [
                {"accession": "", "path": unsupported},
                {"accession": "P1", "path": ""},
                {"accession": "P2", "path": unsupported},
            ]
        )
    with pytest.raises(InputValidationError, match="must be an integer"):
        mapped_residue_locators(
            records=[
                {
                    "accession": "P1",
                    "pocket_number": "bad",
                    "mapping_status": "MAPPED",
                }
            ],
            accession="P1",
            pocket_number=1,
        )


def test_mapping_filters_and_unresolved_residues_are_explicit(tmp_path: Path) -> None:
    """All mapping filters and partial structure resolution must be deterministic."""
    structure = write_pdb(tmp_path / "model.pdb")
    asset = resolve_structure_assets(
        [{"accession": "P1", "path": structure, "sha256": sha256_file(structure)}]
    )["P1"]
    mappings = [
        {
            "accession": "OTHER",
            "pocket_number": 1,
            "mapping_status": "MAPPED",
            "model_auth_chain": "A",
            "model_auth_seq_id": 1,
        },
        {
            "accession": "P1",
            "pocket_number": 2,
            "mapping_status": "MAPPED",
            "model_auth_chain": "A",
            "model_auth_seq_id": 1,
        },
        {
            "accession": "P1",
            "pocket_number": 1,
            "mapping_status": "UNMAPPED",
            "model_auth_chain": "A",
            "model_auth_seq_id": 1,
        },
        {
            "accession": "P1",
            "pocket_number": 1,
            "mapping_status": "MAPPED",
            "model_auth_chain": "",
            "model_auth_seq_id": "",
        },
        {
            "accession": "P1",
            "pocket_number": 1,
            "mapping_status": "MAPPED",
            "model_auth_chain": "A",
            "model_auth_seq_id": 1,
        },
    ]
    locators = mapped_residue_locators(
        records=mappings,
        accession="P1",
        pocket_number=1,
    )
    locators.append(
        {"chain_id": "Z", "sequence_id": "999", "insertion_code": ""}
    )

    residues = load_pocket_residues(
        asset=asset,
        pocket_number=1,
        locators=locators,
    )

    assert len(residues) == 1
    with pytest.raises(InputValidationError, match="No mapped pocket residue"):
        load_pocket_residues(
            asset=asset,
            pocket_number=1,
            locators=[
                {"chain_id": "Z", "sequence_id": "999", "insertion_code": ""}
            ],
        )


def test_structure_without_models_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty coordinate file must not be treated as a resolved structure."""
    empty_structure = tmp_path / "empty.pdb"
    empty_structure.write_text("REMARK no atoms\nEND\n", encoding="utf-8")
    asset = resolve_structure_assets(
        [
            {
                "accession": "P1",
                "path": empty_structure,
                "sha256": sha256_file(empty_structure),
            }
        ]
    )["P1"]
    import gemmi

    monkeypatch.setattr(gemmi, "read_structure", lambda path: [])

    with pytest.raises(InputValidationError, match="contains no models"):
        load_pocket_residues(
            asset=asset,
            pocket_number=1,
            locators=[
                {"chain_id": "A", "sequence_id": "1", "insertion_code": ""}
            ],
        )
