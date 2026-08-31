"""Immutable data models shared across package modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResultCapabilities:
    """Features discovered in one OrthoFinder result directory."""

    has_species_ids: bool
    has_sequence_ids: bool
    has_legacy_orthogroups: bool
    has_hog_tables: bool
    has_orthogroup_sequences: bool
    has_alignments: bool
    has_gene_trees: bool
    has_resolved_gene_trees: bool
    has_species_tree: bool

    def to_record(self) -> dict[str, bool]:
        """Return a serialisable capability record.

        Returns:
            Capability names and Boolean values.
        """

        return asdict(self)


@dataclass(frozen=True)
class ResultLayout:
    """Resolved paths and semantics for one OrthoFinder result set."""

    results_dir: Path
    orthofinder_version: str
    adapter_name: str
    primary_group_authority: str
    log_path: Path
    species_ids_path: Path | None
    sequence_ids_path: Path | None
    orthogroups_path: Path | None
    hog_paths: tuple[Path, ...]
    species_tree_path: Path | None
    orthogroup_sequences_dir: Path | None
    alignments_dir: Path | None
    gene_trees_dir: Path | None
    resolved_gene_trees_dir: Path | None
    capabilities: ResultCapabilities

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-safe description of the layout.

        Returns:
            Paths, version semantics and detected capabilities.
        """

        record: dict[str, Any] = {
            "results_dir": str(self.results_dir),
            "orthofinder_version": self.orthofinder_version,
            "adapter_name": self.adapter_name,
            "primary_group_authority": self.primary_group_authority,
            "log_path": str(self.log_path),
            "species_ids_path": _optional_path(self.species_ids_path),
            "sequence_ids_path": _optional_path(self.sequence_ids_path),
            "orthogroups_path": _optional_path(self.orthogroups_path),
            "hog_paths": [str(path) for path in self.hog_paths],
            "species_tree_path": _optional_path(self.species_tree_path),
            "orthogroup_sequences_dir": _optional_path(self.orthogroup_sequences_dir),
            "alignments_dir": _optional_path(self.alignments_dir),
            "gene_trees_dir": _optional_path(self.gene_trees_dir),
            "resolved_gene_trees_dir": _optional_path(self.resolved_gene_trees_dir),
            "capabilities": self.capabilities.to_record(),
        }
        return record


def _optional_path(path: Path | None) -> str | None:
    """Convert an optional path to a portable scalar.

    Args:
        path: Optional filesystem path.

    Returns:
        String path or ``None``.
    """

    return None if path is None else str(path)
