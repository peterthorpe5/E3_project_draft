"""Bounded pairwise alignment, species overlap and hierarchical comparison statistics."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from .common import ResearchError, normalise_protein

LOGGER = logging.getLogger(__name__)
CANONICAL = frozenset("ACDEFGHIKLMNPQRSTVWY")
MAX_COMPARISON_ROWS = 1_000
MAX_COMPARISON_CELLS = 25_000_000


@dataclass(frozen=True, kw_only=True)
class ComparisonMatrix:
    """Labelled similarity, exact denominators and a display hierarchy when distances exist."""

    similarity: pd.DataFrame
    denominators: pd.DataFrame
    order: tuple[str, ...]
    linkage_matrix: tuple[tuple[float, ...], ...]
    hierarchy_status: str


def _matrix(
    *, labels: Sequence[str], values: np.ndarray, denominators: np.ndarray,
) -> ComparisonMatrix:
    """Use average linkage on finite 1-similarity distances; retain missing comparisons."""
    frame = pd.DataFrame(data=values, index=labels, columns=labels)
    counts = pd.DataFrame(data=denominators, index=labels, columns=labels)
    if len(labels) < 2:
        return ComparisonMatrix(
            similarity=frame, denominators=counts, order=tuple(labels), linkage_matrix=(),
            hierarchy_status="AT_LEAST_TWO_ROWS_REQUIRED",
        )
    if not np.isfinite(values).all():
        return ComparisonMatrix(
            similarity=frame, denominators=counts, order=tuple(labels), linkage_matrix=(),
            hierarchy_status="UNDEFINED_PAIRS_NO_HIERARCHY",
        )
    distances = np.clip(1.0 - values, 0.0, 1.0)
    np.fill_diagonal(distances, 0.0)
    linked = linkage(y=squareform(X=distances, checks=True), method="average",
                     optimal_ordering=True)
    return ComparisonMatrix(
        similarity=frame, denominators=counts,
        order=tuple(labels[int(index)] for index in leaves_list(Z=linked)),
        linkage_matrix=tuple(tuple(float(value) for value in row) for row in linked),
        hierarchy_status="AVERAGE_LINKAGE_1_MINUS_SIMILARITY",
    )


def alignment_comparison(*, records: Mapping[str, str]) -> ComparisonMatrix:
    """Compute all-pairs identity over comparable canonical aligned residues, with missing pairs.

    Args:
        records: Exact aligned protein rows with equal length and stable unique identifiers.

    Returns:
        Identity fractions, comparable-residue counts and an explicitly labelled display hierarchy.

    Raises:
        ResearchError: If rows, dimensions or bounds are invalid.
    """
    if not records or len(records) > MAX_COMPARISON_ROWS:
        raise ResearchError(f"Select 1 to {MAX_COMPARISON_ROWS} rows for pairwise comparison")
    lengths = {len(sequence) for sequence in records.values()}
    if len(lengths) != 1 or len(records) * next(iter(lengths)) > MAX_COMPARISON_CELLS:
        raise ResearchError("Pairwise alignment rows must be equal length within the cell bound")
    labels = list(records)
    sequences = [
        normalise_protein(sequence=sequence, aligned=True) for sequence in records.values()
    ]
    length = next(iter(lengths))
    encoded = np.array([list(sequence) for sequence in sequences], dtype="U1")
    valid = np.isin(encoded, list(CANONICAL))
    values = np.full((len(labels), len(labels)), np.nan)
    counts = np.zeros((len(labels), len(labels)), dtype=np.int64)
    for left in range(len(labels)):
        for right in range(left, len(labels)):
            comparable = valid[left] & valid[right]
            count = int(comparable.sum())
            counts[left, right] = counts[right, left] = count
            if count:
                fraction = float(((encoded[left] == encoded[right]) & comparable).sum()) / count
                values[left, right] = values[right, left] = fraction
    LOGGER.info("Compared %d aligned proteins over %d columns", len(labels), length)
    return _matrix(labels=labels, values=values, denominators=counts)


def species_comparison(*, rows: pd.DataFrame) -> tuple[ComparisonMatrix, pd.DataFrame]:
    """Compare species/taxon sets across clusters, excluding explicitly unclassified evidence.

    Args:
        rows: cluster_id, species, taxon_id and member_count records from reviewed metadata.

    Returns:
        Jaccard similarities/union denominators and complete classification-coverage summaries.

    Raises:
        ResearchError: If counts, taxonomy labels or dimensions are inconsistent.
    """
    required = {"cluster_id", "species", "taxon_id", "member_count"}
    if not required.issubset(rows) or rows.empty:
        raise ResearchError("Species comparison requires cluster_id/species/taxon_id/member_count")
    frame = rows.copy()
    counts = pd.to_numeric(arg=frame["member_count"], errors="coerce")
    if counts.isna().any() or (counts < 0).any() or (counts % 1 != 0).any():
        raise ResearchError("Species member counts must be non-negative integers")
    frame["member_count"] = counts.astype("int64")
    taxa = pd.to_numeric(arg=frame["taxon_id"], errors="coerce")
    classified = taxa.notna() & (taxa > 0) & (taxa % 1 == 0) & counts.gt(0)
    labels = sorted(frame["cluster_id"].astype(str).unique())
    if not 1 <= len(labels) <= MAX_COMPARISON_ROWS:
        raise ResearchError(f"Compare at most {MAX_COMPARISON_ROWS} clusters at once")
    sets, summaries = {}, []
    for cluster in labels:
        selected = frame["cluster_id"].astype(str).eq(cluster)
        sets[cluster] = set(taxa.loc[selected & classified].astype("int64"))
        total = int(frame.loc[selected, "member_count"].sum())
        known = int(frame.loc[selected & classified, "member_count"].sum())
        summaries.append({
            "cluster_id": cluster, "member_count": total, "classified_members": known,
            "unclassified_members": total - known,
            "classification_fraction": known / total if total else None,
            "reviewed_taxon_count": len(sets[cluster]),
        })
    values = np.full((len(labels), len(labels)), np.nan)
    denominators = np.zeros((len(labels), len(labels)), dtype=np.int64)
    for left, first in enumerate(labels):
        for right, second in enumerate(labels):
            union = sets[first] | sets[second]
            denominators[left, right] = len(union)
            if sets[first] and sets[second]:
                values[left, right] = len(sets[first] & sets[second]) / len(union)
    return _matrix(labels=labels, values=values, denominators=denominators), pd.DataFrame(
        data=summaries,
    )


def venn_regions(*, rows: pd.DataFrame, cluster_ids: Sequence[str]) -> dict[str, int]:
    """Count disjoint two/three-cluster species-set regions for a labelled Venn diagram.

    Args:
        rows: Reviewed cluster/taxon counts; unknown taxonomy never forms a species.
        cluster_ids: Two or three distinct cluster IDs in their displayed A/B/C order.

    Returns:
        Binary membership-region strings mapped to exact unique-taxon counts.

    Raises:
        ResearchError: If selection or taxonomy evidence is invalid.
    """
    if len(set(cluster_ids)) != len(cluster_ids) or len(cluster_ids) not in {2, 3}:
        raise ResearchError("A species Venn diagram requires two or three distinct clusters")
    species_comparison(rows=rows)
    taxa = pd.to_numeric(arg=rows["taxon_id"], errors="coerce")
    valid = taxa.gt(0) & (taxa % 1 == 0) & pd.to_numeric(arg=rows["member_count"]).gt(0)
    sets = [set(taxa.loc[rows["cluster_id"].astype(str).eq(cluster) & valid].dropna().astype(int))
            for cluster in cluster_ids]
    if any(not values for values in sets):
        raise ResearchError("Each selected Venn cluster needs reviewed taxonomic assignments")
    regions = {format(mask, f"0{len(sets)}b"): 0 for mask in range(1, 2 ** len(sets))}
    for taxon in set().union(*sets):
        region = "".join("1" if taxon in values else "0" for values in sets)
        regions[region] += 1
    return regions
