"""Shared fixtures for the structure-guided chemistry tests."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def package_root() -> Path:
    """Return the structure-guided chemistry package root."""
    return Path(__file__).resolve().parents[1]


def write_tsv(path: Path, rows: list[dict[str, object]]) -> Path:
    """Write one fixture TSV using the first row's stable field order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("Fixture rows must not be empty")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_config(
    path: Path,
    *,
    mode: str = "prepare_only",
    fragment_library: Path | None = None,
) -> Path:
    """Write one valid open-source chemistry configuration."""
    components = [
        {"name": "DuckDB", "spdx": "MIT"},
        {"name": "Gemmi", "spdx": "MPL-2.0"},
    ]
    if mode == "open_fragment_screen":
        components.append({"name": "RDKit", "spdx": "BSD-3-Clause"})
    payload = {
        "schema_version": 1,
        "method": {
            "name": "open_structure_guided_pharmacophore_v1",
            "group_limit": 10,
            "minimum_conserved_component_fraction": 0.5,
            "minimum_chemical_group_conservation": 0.5,
            "minimum_uniqueness_score": 0.1,
            "maximum_fragments_per_group": 10,
        },
        "fragment_screening": {
            "mode": mode,
            "fragment_library": (
                None if fragment_library is None else str(fragment_library)
            ),
        },
        "licensing": {
            "allow_restricted_licence_tools": False,
            "declared_components": components,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_pdb(path: Path) -> Path:
    """Write a valid two-residue protein pocket fixture."""
    path.write_text(
        """ATOM      1  N   LYS A   1      10.000  10.000  10.000  1.00 80.00           N
ATOM      2  CA  LYS A   1      11.000  10.000  10.000  1.00 80.00           C
ATOM      3  C   LYS A   1      12.000  10.000  10.000  1.00 80.00           C
ATOM      4  O   LYS A   1      13.000  10.000  10.000  1.00 80.00           O
ATOM      5  CB  LYS A   1      11.000  11.000  10.000  1.00 80.00           C
ATOM      6  CG  LYS A   1      11.000  12.000  10.000  1.00 80.00           C
ATOM      7  CD  LYS A   1      11.000  13.000  10.000  1.00 80.00           C
ATOM      8  CE  LYS A   1      11.000  14.000  10.000  1.00 80.00           C
ATOM      9  NZ  LYS A   1      11.000  15.000  10.000  1.00 80.00           N
ATOM     10  N   ASP A   2      12.000   9.000  10.000  1.00 85.00           N
ATOM     11  CA  ASP A   2      13.000   9.000  10.000  1.00 85.00           C
ATOM     12  C   ASP A   2      14.000   9.000  10.000  1.00 85.00           C
ATOM     13  O   ASP A   2      15.000   9.000  10.000  1.00 85.00           O
ATOM     14  CB  ASP A   2      13.000   8.000  10.000  1.00 85.00           C
ATOM     15  CG  ASP A   2      13.000   7.000  10.000  1.00 85.00           C
ATOM     16  OD1 ASP A   2      12.000   6.500  10.000  1.00 85.00           O
ATOM     17  OD2 ASP A   2      14.000   6.500  10.000  1.00 85.00           O
TER      18      ASP A   2
END
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def scientific_inputs(tmp_path: Path) -> dict[str, Path]:
    """Create one complete TSV/PDB input set for integration tests."""
    structure = write_pdb(tmp_path / "model.pdb")
    digest = hashlib.sha256(structure.read_bytes()).hexdigest()
    ranking = write_tsv(
        tmp_path / "ranking.tsv",
        [
            {
                "evolutionary_group_rank": 1,
                "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG1",
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "HOG1",
                "lead_cluster_id": "DC1",
            }
        ],
    )
    pockets = write_tsv(
        tmp_path / "pockets.tsv",
        [
            {
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "HOG1",
                "candidate_accession": "P00001",
                "species_column": "Species_one",
                "pocket_number": 1,
                "druggability_score": 0.8,
                "mapping_fraction": 1.0,
                "conservative_fraction_plddt_ge_70": 1.0,
            }
        ],
    )
    mappings = write_tsv(
        tmp_path / "mappings.tsv",
        [
            {
                "accession": "P00001",
                "pocket_number": 1,
                "mapping_status": "MAPPED",
                "model_auth_chain": "A",
                "model_auth_seq_id": 1,
                "model_insertion_code": "",
            },
            {
                "accession": "P00001",
                "pocket_number": 1,
                "mapping_status": "MAPPED",
                "model_auth_chain": "A",
                "model_auth_seq_id": 2,
                "model_insertion_code": "",
            },
        ],
    )
    conservation = write_tsv(
        tmp_path / "conservation.tsv",
        [
            {
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "HOG1",
                "conserved_component_fraction": 0.9,
                "mean_chemical_group_conservation": 0.8,
            }
        ],
    )
    assets = write_tsv(
        tmp_path / "assets.tsv",
        [
            {
                "accession": "P00001",
                "path": str(structure),
                "sha256": digest,
            }
        ],
    )
    fragments = write_tsv(
        tmp_path / "fragments.tsv",
        [
            {"fragment_id": "F1", "smiles": "c1ccncc1", "source": "test"},
            {"fragment_id": "F2", "smiles": "CC(=O)N", "source": "test"},
        ],
    )
    return {
        "structure": structure,
        "ranking": ranking,
        "pockets": pockets,
        "mappings": mappings,
        "conservation": conservation,
        "assets": assets,
        "fragments": fragments,
    }
