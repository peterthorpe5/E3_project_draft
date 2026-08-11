"""Immutable data models used by the chemistry workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ComponentLicence:
    """One declared runtime component and its SPDX licence."""

    name: str
    spdx: str


@dataclass(frozen=True)
class ChemistryConfig:
    """Validated computational-chemistry method configuration."""

    source_path: Path
    method_name: str
    maximum_candidate_groups: int
    minimum_conserved_component_fraction: float
    minimum_chemical_group_conservation: float
    minimum_mapping_fraction: float
    minimum_pocket_plddt_fraction: float
    minimum_druggability_score: float
    minimum_mapped_residue_count: int
    minimum_uniqueness_score: float
    high_confidence_conserved_component_fraction: float
    high_confidence_chemical_group_conservation: float
    high_confidence_pocket_plddt_fraction: float
    high_confidence_druggability_score: float
    high_confidence_mapped_residue_count: int
    maximum_fragments_per_group: int
    fragment_screening_mode: str
    fragment_library: Path | None
    allow_restricted_licence_tools: bool
    declared_components: tuple[ComponentLicence, ...]
    require_clean_tracked_source: bool
    digest: str


@dataclass(frozen=True)
class Coordinate:
    """One Cartesian coordinate in Angstrom."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class ResidueGeometry:
    """One mapped pocket residue and its atom coordinates."""

    accession: str
    pocket_number: int
    chain_id: str
    sequence_id: str
    insertion_code: str
    residue_name: str
    atoms: dict[str, Coordinate]


@dataclass(frozen=True)
class StructureAsset:
    """One checksum-validated protein structure asset."""

    accession: str
    path: Path
    sha256: str
