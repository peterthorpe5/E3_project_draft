"""Explicit, auditable sequence and phylogenetic distance calculations."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import DistanceCalculationError, InputValidationError

DISTANCE_FIELDS = (
    "run_id",
    "group_type",
    "hierarchy_node",
    "group_id",
    "member_a",
    "member_b",
    "distance_method",
    "distance",
    "comparable_sites",
    "mismatch_sites",
    "computation_status",
    "source_file",
)
DISTANCE_STATISTIC_FIELDS = (
    "run_id",
    "group_type",
    "hierarchy_node",
    "group_id",
    "distance_method",
    "computation_status",
    "member_identifier_resolution",
    "total_member_count",
    "sampled_member_count",
    "distance_pair_count",
    "unresolved_pair_count",
    "minimum_distance",
    "q05_distance",
    "q25_distance",
    "median_distance",
    "mean_distance",
    "q75_distance",
    "q95_distance",
    "maximum_distance",
    "population_stddev_distance",
    "mean_comparable_sites",
    "source_file",
    "failure_reason",
)

_GAP_OR_UNKNOWN = frozenset("-.?Xx*BJOUZbjouz")


def read_fasta(*, path: Path) -> dict[str, str]:
    """Read an alignment or sequence FASTA with exact unique identifiers.

    Args:
        path: FASTA file path.

    Returns:
        Ordered identifier-to-sequence mapping.

    Raises:
        InputValidationError: If the FASTA is malformed or identifiers are duplicated.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise InputValidationError(f"Missing or empty FASTA file: {source}")
    records: dict[str, list[str]] = {}
    current: str | None = None
    with source.open(mode="r", encoding="utf-8", errors="strict") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                identifier_text = line[1:].strip()
                identifier = identifier_text.split(maxsplit=1)[0] if identifier_text else ""
                if not identifier:
                    raise InputValidationError(
                        f"Empty FASTA identifier at line {line_number} in {source}."
                    )
                if identifier in records:
                    raise InputValidationError(
                        f"Duplicate FASTA identifier {identifier!r} in {source}."
                    )
                records[identifier] = []
                current = identifier
            else:
                if current is None:
                    raise InputValidationError(
                        "Sequence precedes the first FASTA header at line "
                        f"{line_number} in {source}."
                    )
                records[current].append("".join(line.split()).upper())
    joined = {identifier: "".join(parts) for identifier, parts in records.items()}
    if not joined or any(not sequence for sequence in joined.values()):
        raise InputValidationError(f"FASTA contains no complete sequences: {source}")
    return joined


def calculate_alignment_distances(
    *,
    sequences: Mapping[str, str],
    run_id: str,
    group_type: str,
    hierarchy_node: str,
    group_id: str,
    max_members: int,
    source_file: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Calculate pairwise-deletion amino-acid p-distances for an alignment.

    Large groups are deterministically member-sampled. Sampling is explicit in
    every record and summary; it is never presented as an exact calculation.

    Args:
        sequences: Aligned sequences keyed by unique member identifier.
        run_id: Immutable run identifier.
        group_type: Run-scoped group semantics.
        hierarchy_node: Optional HOG species-tree node.
        group_id: Run-scoped group identifier.
        max_members: Maximum members in an exact or sampled distance matrix.
        source_file: Exact source alignment path for provenance.

    Returns:
        Pairwise distance records and a distribution summary.

    Raises:
        ValueError: If ``max_members`` is less than two.
        DistanceCalculationError: If fewer than two sequences or unequal lengths are supplied.
    """

    if max_members < 2:
        raise ValueError("max_members must be at least two.")
    if len(sequences) < 2:
        raise DistanceCalculationError(f"Group {group_id} contains fewer than two sequences.")
    lengths = {len(sequence) for sequence in sequences.values()}
    if len(lengths) != 1:
        raise DistanceCalculationError(
            f"Alignment for {group_id} contains unequal sequence lengths: {sorted(lengths)}"
        )
    selected, status = deterministic_member_sample(
        member_ids=tuple(sequences),
        run_id=run_id,
        group_id=group_id,
        max_members=max_members,
    )
    rows: list[dict[str, Any]] = []
    for left_index, member_a in enumerate(selected):
        for member_b in selected[left_index + 1 :]:
            distance, comparable, mismatches = pairwise_p_distance(
                sequence_a=sequences[member_a],
                sequence_b=sequences[member_b],
            )
            rows.append(
                {
                    "run_id": run_id,
                    "group_type": group_type,
                    "hierarchy_node": hierarchy_node,
                    "group_id": group_id,
                    "member_a": member_a,
                    "member_b": member_b,
                    "distance_method": "amino_acid_p_distance_pairwise_deletion",
                    "distance": "" if distance is None else distance,
                    "comparable_sites": comparable,
                    "mismatch_sites": mismatches,
                    "computation_status": status,
                    "source_file": source_file,
                }
            )
    summary = summarise_distances(
        rows=rows,
        run_id=run_id,
        group_type=group_type,
        hierarchy_node=hierarchy_node,
        group_id=group_id,
        method="amino_acid_p_distance_pairwise_deletion",
        status=status,
        total_member_count=len(sequences),
        sampled_member_count=len(selected),
        member_identifier_resolution="ALIGNMENT_HEADER_EXACT",
        source_file=source_file,
    )
    return rows, summary


def calculate_patristic_distances(
    *,
    tree_path: Path,
    run_id: str,
    group_type: str,
    hierarchy_node: str,
    group_id: str,
    max_members: int,
    member_ids: Sequence[str] | None = None,
    member_aliases: Mapping[str, Mapping[str, str]] | None = None,
    source_file: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Calculate pairwise branch-length distances from one Newick gene tree.

    Args:
        tree_path: Newick gene or resolved-gene tree.
        run_id: Immutable run identifier.
        group_type: Run-scoped group semantics.
        hierarchy_node: Optional HOG node.
        group_id: Run-scoped group identifier.
        max_members: Maximum leaves in the distance matrix.
        member_ids: Optional canonical member subset, for example one HOG within a tree.
        member_aliases: Optional canonical-member mapping whose inner keys are
            alternative tree labels and values describe the resolution method.
        source_file: Exact tree path for provenance; defaults to ``tree_path``.

    Returns:
        Pairwise patristic records and a distribution summary.

    Raises:
        DistanceCalculationError: If leaves are duplicated, missing, insufficient or unscaled.
    """

    from Bio import Phylo
    from Bio.Phylo.NewickIO import NewickError

    source = Path(tree_path).expanduser().resolve()
    provenance_source = source_file or str(source)
    if not source.is_file() or source.stat().st_size == 0:
        raise DistanceCalculationError(f"Missing or empty tree: {source}")
    try:
        tree = Phylo.read(str(source), "newick")
    except (NewickError, ValueError, OSError) as error:
        raise DistanceCalculationError(f"Could not parse tree {source}: {error}") from error
    terminals = tree.get_terminals()
    names = [terminal.name or "" for terminal in terminals]
    if any(not name for name in names):
        raise DistanceCalculationError(f"Tree contains an unnamed leaf: {source}")
    if len(set(names)) != len(names):
        raise DistanceCalculationError(f"Tree contains duplicate leaf names: {source}")
    available = set(names)
    requested = tuple(names) if member_ids is None else tuple(member_ids)
    if len(set(requested)) != len(requested):
        raise DistanceCalculationError(
            f"Group {group_id} contains duplicate canonical member identifiers."
        )
    resolved_leaves: dict[str, str] = {}
    resolution_methods: set[str] = set()
    missing: list[str] = []
    for member_id in requested:
        candidates = {member_id: "EXACT_MEMBER_ID"}
        if member_aliases is not None:
            candidates.update(member_aliases.get(member_id, {}))
        matches = [
            (candidate, method)
            for candidate, method in candidates.items()
            if candidate in available
        ]
        if not matches:
            missing.append(member_id)
            continue
        if len(matches) > 1:
            labels = ";".join(sorted(candidate for candidate, _ in matches))
            raise DistanceCalculationError(
                f"Tree {source} has ambiguous labels for canonical member "
                f"{member_id!r}: {labels}"
            )
        tree_label, resolution_method = matches[0]
        resolved_leaves[member_id] = tree_label
        resolution_methods.add(resolution_method)
    if missing:
        preview = ";".join(sorted(missing)[:10])
        raise DistanceCalculationError(
            f"Tree {source} lacks {len(missing)} requested members: {preview}"
        )
    reverse: dict[str, list[str]] = {}
    for member_id, tree_label in resolved_leaves.items():
        reverse.setdefault(tree_label, []).append(member_id)
    collisions = {
        tree_label: canonical_ids
        for tree_label, canonical_ids in reverse.items()
        if len(canonical_ids) > 1
    }
    if collisions:
        tree_label, canonical_ids = sorted(collisions.items())[0]
        raise DistanceCalculationError(
            f"Tree label {tree_label!r} resolves from multiple canonical members: "
            f"{';'.join(sorted(canonical_ids))}"
        )
    selected, status = deterministic_member_sample(
        member_ids=requested,
        run_id=run_id,
        group_id=group_id,
        max_members=max_members,
    )
    if len(selected) < 2:
        raise DistanceCalculationError(f"Group {group_id} contains fewer than two tree leaves.")
    leaves = {terminal.name: terminal for terminal in terminals}
    rows: list[dict[str, Any]] = []
    for left_index, member_a in enumerate(selected):
        for member_b in selected[left_index + 1 :]:
            distance = tree.distance(
                leaves[resolved_leaves[member_a]],
                leaves[resolved_leaves[member_b]],
            )
            if distance is None or not math.isfinite(float(distance)):
                raise DistanceCalculationError(
                    f"Tree distance is not finite for {member_a!r} and {member_b!r}."
                )
            rows.append(
                {
                    "run_id": run_id,
                    "group_type": group_type,
                    "hierarchy_node": hierarchy_node,
                    "group_id": group_id,
                    "member_a": member_a,
                    "member_b": member_b,
                    "distance_method": "patristic_branch_length",
                    "distance": float(distance),
                    "comparable_sites": "",
                    "mismatch_sites": "",
                    "computation_status": status,
                    "source_file": provenance_source,
                }
            )
    identifier_resolution = (
        next(iter(resolution_methods))
        if len(resolution_methods) == 1
        else "MIXED_TREE_ALIASES"
    )
    summary = summarise_distances(
        rows=rows,
        run_id=run_id,
        group_type=group_type,
        hierarchy_node=hierarchy_node,
        group_id=group_id,
        method="patristic_branch_length",
        status=status,
        total_member_count=len(requested),
        sampled_member_count=len(selected),
        member_identifier_resolution=identifier_resolution,
        source_file=provenance_source,
    )
    return rows, summary


def pairwise_p_distance(*, sequence_a: str, sequence_b: str) -> tuple[float | None, int, int]:
    """Calculate mismatch fraction after pairwise gap/unknown deletion.

    Args:
        sequence_a: First aligned amino-acid sequence.
        sequence_b: Second aligned amino-acid sequence.

    Returns:
        Distance or ``None``, comparable-site count and mismatch count.

    Raises:
        DistanceCalculationError: If aligned lengths differ.
    """

    if len(sequence_a) != len(sequence_b):
        raise DistanceCalculationError("Pairwise p-distance requires equal alignment lengths.")
    comparable = 0
    mismatches = 0
    for residue_a, residue_b in zip(sequence_a, sequence_b, strict=True):
        if residue_a in _GAP_OR_UNKNOWN or residue_b in _GAP_OR_UNKNOWN:
            continue
        comparable += 1
        mismatches += residue_a != residue_b
    return (mismatches / comparable if comparable else None, comparable, mismatches)


def deterministic_member_sample(
    *, member_ids: Sequence[str], run_id: str, group_id: str, max_members: int
) -> tuple[tuple[str, ...], str]:
    """Select a deterministic, order-independent subset of group members.

    Args:
        member_ids: Unique member identifiers.
        run_id: Immutable run identifier.
        group_id: Run-scoped group identifier.
        max_members: Maximum selected members.

    Returns:
        Sorted selected identifiers and explicit calculation status.

    Raises:
        ValueError: If limits or identifiers are invalid.
    """

    if max_members < 2:
        raise ValueError("max_members must be at least two.")
    if len(set(member_ids)) != len(member_ids):
        raise ValueError("member_ids must be unique.")
    if any(not member_id for member_id in member_ids):
        raise ValueError("member_ids must not contain empty values.")
    if len(member_ids) <= max_members:
        return tuple(sorted(member_ids)), "EXACT"
    ranked = sorted(
        member_ids,
        key=lambda member_id: hashlib.sha256(
            f"{run_id}\0{group_id}\0{member_id}".encode("utf-8")
        ).hexdigest(),
    )
    return tuple(sorted(ranked[:max_members])), "DETERMINISTIC_MEMBER_SAMPLE"


def summarise_distances(
    *,
    rows: Iterable[Mapping[str, Any]],
    run_id: str,
    group_type: str,
    hierarchy_node: str,
    group_id: str,
    method: str,
    status: str,
    total_member_count: int,
    sampled_member_count: int,
    member_identifier_resolution: str = "",
    source_file: str = "",
    failure_reason: str = "",
) -> dict[str, Any]:
    """Summarise a pairwise distance distribution without hiding missing pairs.

    Args:
        rows: Pairwise distance records.
        run_id: Immutable run identifier.
        group_type: Run-scoped group semantics.
        hierarchy_node: Optional HOG node.
        group_id: Run-scoped group identifier.
        method: Exact distance method label.
        status: Exact or sampled status.
        total_member_count: Members in the source group.
        sampled_member_count: Members used for the distance matrix.
        member_identifier_resolution: Exact identifier mapping used for the calculation.
        source_file: Exact source alignment or tree path.
        failure_reason: Explicit reason when a calculation is unavailable.

    Returns:
        Distribution and coverage statistics.
    """

    materialised = list(rows)
    values = [float(row["distance"]) for row in materialised if row["distance"] != ""]
    comparable = [
        int(row["comparable_sites"])
        for row in materialised
        if row.get("comparable_sites") not in {"", None}
    ]
    summary: dict[str, Any] = {
        "run_id": run_id,
        "group_type": group_type,
        "hierarchy_node": hierarchy_node,
        "group_id": group_id,
        "distance_method": method,
        "computation_status": status,
        "member_identifier_resolution": member_identifier_resolution,
        "total_member_count": total_member_count,
        "sampled_member_count": sampled_member_count,
        "distance_pair_count": len(values),
        "unresolved_pair_count": len(materialised) - len(values),
        "mean_comparable_sites": statistics.fmean(comparable) if comparable else 0.0,
        "source_file": source_file,
        "failure_reason": failure_reason,
    }
    quantiles = {
        "minimum_distance": 0.0,
        "q05_distance": 0.0,
        "q25_distance": 0.0,
        "median_distance": 0.0,
        "mean_distance": 0.0,
        "q75_distance": 0.0,
        "q95_distance": 0.0,
        "maximum_distance": 0.0,
        "population_stddev_distance": 0.0,
    }
    if values:
        ordered = sorted(values)
        quantiles.update(
            {
                "minimum_distance": ordered[0],
                "q05_distance": _quantile(values=ordered, probability=0.05),
                "q25_distance": _quantile(values=ordered, probability=0.25),
                "median_distance": _quantile(values=ordered, probability=0.5),
                "mean_distance": statistics.fmean(ordered),
                "q75_distance": _quantile(values=ordered, probability=0.75),
                "q95_distance": _quantile(values=ordered, probability=0.95),
                "maximum_distance": ordered[-1],
                "population_stddev_distance": statistics.pstdev(ordered),
            }
        )
    summary.update(quantiles)
    return summary


def _quantile(*, values: Sequence[float], probability: float) -> float:
    """Calculate a linearly interpolated quantile.

    Args:
        values: Non-empty sorted observations.
        probability: Quantile probability in the closed interval zero to one.

    Returns:
        Interpolated quantile.

    Raises:
        ValueError: If inputs are invalid.
    """

    if not values:
        raise ValueError("values must not be empty.")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between zero and one.")
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return float(values[lower] * (1.0 - fraction) + values[upper] * fraction)
