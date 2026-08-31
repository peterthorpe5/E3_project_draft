"""Streaming group-size and species-copy statistics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

GROUP_STATISTIC_FIELDS = (
    "run_id",
    "group_type",
    "hierarchy_node",
    "group_id",
    "legacy_orthogroup_id",
    "gene_tree_parent_clade",
    "member_count",
    "species_count",
    "single_copy_species_count",
    "max_copies_per_species",
    "mean_copies_per_species",
    "is_singleton",
    "species_labels",
    "source_file",
)


@dataclass
class GroupAccumulator:
    """Mutable streaming state for one run-scoped group."""

    run_id: str
    group_type: str
    hierarchy_node: str
    group_id: str
    legacy_orthogroup_id: str
    gene_tree_parent_clade: str
    source_file: str
    species_counts: Counter[str] = field(default_factory=Counter)
    member_count: int = 0

    def add_member(self, *, species_label: str) -> None:
        """Record one protein membership.

        Args:
            species_label: Exact OrthoFinder species column.

        Raises:
            ValueError: If the species label is empty.
        """

        if not species_label:
            raise ValueError("species_label must not be empty.")
        self.member_count += 1
        self.species_counts[species_label] += 1

    def to_record(self) -> dict[str, Any]:
        """Return final group-size statistics.

        Returns:
            Long-form group summary record.
        """

        species_count = len(self.species_counts)
        mean_copies = self.member_count / species_count if species_count else 0.0
        return {
            "run_id": self.run_id,
            "group_type": self.group_type,
            "hierarchy_node": self.hierarchy_node,
            "group_id": self.group_id,
            "legacy_orthogroup_id": self.legacy_orthogroup_id,
            "gene_tree_parent_clade": self.gene_tree_parent_clade,
            "member_count": self.member_count,
            "species_count": species_count,
            "single_copy_species_count": sum(count == 1 for count in self.species_counts.values()),
            "max_copies_per_species": max(self.species_counts.values(), default=0),
            "mean_copies_per_species": mean_copies,
            "is_singleton": self.member_count == 1,
            "species_labels": ";".join(sorted(self.species_counts)),
            "source_file": self.source_file,
        }


def update_accumulators(
    *,
    accumulators: dict[tuple[str, str, str], GroupAccumulator],
    membership: dict[str, Any],
) -> None:
    """Update a keyed group accumulator from one membership record.

    Args:
        accumulators: Mutable group-state mapping.
        membership: Membership record produced by :func:`iter_memberships`.

    Raises:
        ValueError: If a repeated group has inconsistent metadata.
    """

    key = (
        str(membership["group_type"]),
        str(membership["hierarchy_node"]),
        str(membership["group_id"]),
    )
    accumulator = accumulators.get(key)
    if accumulator is None:
        accumulator = GroupAccumulator(
            run_id=str(membership["run_id"]),
            group_type=key[0],
            hierarchy_node=key[1],
            group_id=key[2],
            legacy_orthogroup_id=str(membership["legacy_orthogroup_id"]),
            gene_tree_parent_clade=str(membership["gene_tree_parent_clade"]),
            source_file=str(membership["source_file"]),
        )
        accumulators[key] = accumulator
    metadata = (
        str(membership["run_id"]),
        str(membership["legacy_orthogroup_id"]),
        str(membership["gene_tree_parent_clade"]),
        str(membership["source_file"]),
    )
    expected = (
        accumulator.run_id,
        accumulator.legacy_orthogroup_id,
        accumulator.gene_tree_parent_clade,
        accumulator.source_file,
    )
    if metadata != expected:
        raise ValueError(f"Inconsistent metadata for group {key}: {metadata} != {expected}")
    accumulator.add_member(species_label=str(membership["species_label"]))


def finalise_accumulators(
    *, accumulators: dict[tuple[str, str, str], GroupAccumulator]
) -> list[dict[str, Any]]:
    """Return deterministically ordered group summaries.

    Args:
        accumulators: Completed group-state mapping.

    Returns:
        Sorted summary records.
    """

    return [accumulators[key].to_record() for key in sorted(accumulators)]
