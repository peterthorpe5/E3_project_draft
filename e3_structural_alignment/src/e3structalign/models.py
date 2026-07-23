"""Immutable domain objects for structural and pocket comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SelectedPocket:
    """One selected pocket and its group-level provenance."""

    cluster_id: str
    primary_group_type: str
    primary_group_id: str
    accession: str
    species: str
    pocket_number: int
    druggability_score: float | None
    mapping_fraction: float | None
    pocket_plddt_fraction: float | None
    predictor_agreement: bool
    structural_evidence_status: str


@dataclass(frozen=True)
class StructureAsset:
    """One checksum-bound model file resolved for an accession."""

    accession: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class ResidueLocator:
    """Alternative label/auth identifiers for one pocket residue."""

    label_chain: str
    label_seq_id: str
    auth_chain: str
    auth_seq_id: str
    insertion_code: str


@dataclass(frozen=True)
class AtomCoordinate:
    """One C-alpha coordinate with label and author residue identifiers."""

    label_chain: str
    label_seq_id: str
    auth_chain: str
    auth_seq_id: str
    insertion_code: str
    residue_name: str
    x: float
    y: float
    z: float

    @property
    def coordinate(self) -> tuple[float, float, float]:
        """Return the Cartesian coordinate tuple."""
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class Transform:
    """Structural-aligner translation vector and rotation matrix."""

    translation: tuple[float, float, float]
    rotation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]

    def apply(
        self, coordinate: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        """Transform a mobile coordinate into the reference coordinate frame."""
        return tuple(
            self.translation[row]
            + sum(
                self.rotation[row][column] * coordinate[column]
                for column in range(3)
            )
            for row in range(3)
        )


@dataclass(frozen=True)
class PocketSequenceCoordinate:
    """One pocket residue linked explicitly to a FASTA coordinate."""

    accession: str
    pocket_number: int
    locator: ResidueLocator
    structure_residue_name: str
    fasta_position: int | None
    fasta_residue: str
    sequence_coordinate_status: str


@dataclass(frozen=True)
class USAlignResult:
    """Parsed global alignment metrics and transformation."""

    aligned_length: int
    rmsd_angstrom: float
    sequence_identity: float
    tm_score_mobile_normalised: float
    tm_score_reference_normalised: float
    transform: Transform
    version: str
