"""Typed data structures used by the ligandability workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResidueRecord:
    """One polymer residue and its structure-confidence value."""

    label_chain: str
    label_seq_id: int | None
    auth_chain: str
    auth_seq_id: int | None
    insertion_code: str
    residue_name: str
    plddt: float
    source_atom_count: int
    source_atom_plddt_range: float

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable dictionary representation."""

        return asdict(self)


@dataclass(frozen=True)
class PocketResidueRecord:
    """One residue associated with a predicted pocket."""

    accession: str
    pocket_number: int
    label_chain: str
    label_seq_id: int | None
    auth_chain: str
    auth_seq_id: int | None
    insertion_code: str
    residue_name: str
    source_file: str

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable dictionary representation."""

        return asdict(self)


@dataclass
class AccessionResult:
    """Mutable pipeline state for one accession."""

    accession: str
    status: str = "PENDING"
    stage: str = "initialise"
    message: str = ""
    model_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model_quality: dict[str, Any] = field(default_factory=dict)
    fpocket_records: list[dict[str, Any]] = field(default_factory=list)
    p2rank_records: list[dict[str, Any]] = field(default_factory=list)
    pocket_residues: list[dict[str, Any]] = field(default_factory=list)
    pocket_quality: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)

    def status_record(self) -> dict[str, Any]:
        """Return the current accession status as a flat record."""

        return {
            "accession": self.accession,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "model_path": "" if self.model_path is None else str(self.model_path),
        }
