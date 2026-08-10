"""Open residue-pharmacophore extraction and group uniqueness scoring."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from e3chemistry.models import ChemistryConfig, Coordinate, ResidueGeometry

FEATURE_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "candidate_accession",
    "pocket_number",
    "chain_id",
    "sequence_id",
    "insertion_code",
    "residue_name",
    "feature_id",
    "feature_type",
    "x_angstrom",
    "y_angstrom",
    "z_angstrom",
    "conserved_component_fraction",
    "mean_chemical_group_conservation",
    "stable_region_supported",
    "method",
    "interpretation",
)

GROUP_SUMMARY_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "candidate_accession",
    "pocket_number",
    "feature_count",
    "feature_types",
    "feature_signature",
    "conserved_component_fraction",
    "mean_chemical_group_conservation",
    "maximum_other_group_feature_similarity",
    "maximum_other_group_spatial_similarity",
    "maximum_other_group_similarity",
    "pharmacophore_uniqueness_score",
    "stable_region_supported",
    "unique_region_supported",
    "chemistry_handoff_status",
    "method",
    "interpretation",
)

DONOR_ATOMS = {
    "ARG": ("NE", "NH1", "NH2"),
    "ASN": ("ND2",),
    "CYS": ("SG",),
    "GLN": ("NE2",),
    "HIS": ("ND1", "NE2"),
    "LYS": ("NZ",),
    "SER": ("OG",),
    "THR": ("OG1",),
    "TRP": ("NE1",),
    "TYR": ("OH",),
}
ACCEPTOR_ATOMS = {
    "ASN": ("OD1",),
    "ASP": ("OD1", "OD2"),
    "CYS": ("SG",),
    "GLN": ("OE1",),
    "GLU": ("OE1", "OE2"),
    "HIS": ("ND1", "NE2"),
    "SER": ("OG",),
    "THR": ("OG1",),
    "TYR": ("OH",),
}
POSITIVE_ATOMS = {
    "ARG": ("CZ", "NH1", "NH2"),
    "HIS": ("CG", "ND1", "CD2", "CE1", "NE2"),
    "LYS": ("NZ",),
}
NEGATIVE_ATOMS = {
    "ASP": ("CG", "OD1", "OD2"),
    "GLU": ("CD", "OE1", "OE2"),
}
AROMATIC_ATOMS = {
    "HIS": ("CG", "ND1", "CD2", "CE1", "NE2"),
    "PHE": ("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),
    "TRP": ("CG", "CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"),
    "TYR": ("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),
}
HYDROPHOBIC_RESIDUES = frozenset(
    {"ALA", "ILE", "LEU", "MET", "PHE", "PRO", "TRP", "TYR", "VAL"}
)
BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O", "OXT"})


def _centroid(coordinates: Sequence[Coordinate]) -> Coordinate:
    """Return the centroid of one non-empty coordinate sequence."""
    return Coordinate(
        x=sum(item.x for item in coordinates) / len(coordinates),
        y=sum(item.y for item in coordinates) / len(coordinates),
        z=sum(item.z for item in coordinates) / len(coordinates),
    )


def _feature_coordinate(
    *, residue: ResidueGeometry, atom_names: Sequence[str]
) -> Coordinate | None:
    """Return the centroid of available named atoms."""
    coordinates = [residue.atoms[name] for name in atom_names if name in residue.atoms]
    return _centroid(coordinates) if coordinates else None


def residue_feature_points(residue: ResidueGeometry) -> list[tuple[str, Coordinate]]:
    """Derive transparent pharmacophore points from one amino-acid residue."""
    feature_atoms = (
        ("hydrogen_bond_donor", DONOR_ATOMS.get(residue.residue_name, ())),
        ("hydrogen_bond_acceptor", ACCEPTOR_ATOMS.get(residue.residue_name, ())),
        ("positive_ionisable", POSITIVE_ATOMS.get(residue.residue_name, ())),
        ("negative_ionisable", NEGATIVE_ATOMS.get(residue.residue_name, ())),
        ("aromatic", AROMATIC_ATOMS.get(residue.residue_name, ())),
    )
    points = []
    for feature_type, atom_names in feature_atoms:
        coordinate = _feature_coordinate(residue=residue, atom_names=atom_names)
        if coordinate is not None:
            points.append((feature_type, coordinate))
    if residue.residue_name in HYDROPHOBIC_RESIDUES:
        side_chain = [
            coordinate
            for name, coordinate in residue.atoms.items()
            if name not in BACKBONE_ATOMS
        ]
        if side_chain:
            points.append(("hydrophobic", _centroid(side_chain)))
    return points


def build_feature_records(
    *,
    target: Mapping[str, Any],
    residues: Sequence[ResidueGeometry],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Build row-level three-dimensional pharmacophore features for one group."""
    conserved_fraction = float(target["conserved_component_fraction"])
    chemical_conservation = float(target["mean_chemical_group_conservation"])
    stable = (
        conserved_fraction >= config.minimum_conserved_component_fraction
        and chemical_conservation >= config.minimum_chemical_group_conservation
    )
    records = []
    for residue in residues:
        for index, (feature_type, coordinate) in enumerate(
            residue_feature_points(residue),
            start=1,
        ):
            records.append(
                {
                    "evolutionary_group_rank": target["evolutionary_group_rank"],
                    "evolutionary_group_key": target["evolutionary_group_key"],
                    "primary_group_type": target["primary_group_type"],
                    "primary_group_id": target["primary_group_id"],
                    "cluster_id": target["cluster_id"],
                    "candidate_accession": target["candidate_accession"],
                    "pocket_number": target["pocket_number"],
                    "chain_id": residue.chain_id,
                    "sequence_id": residue.sequence_id,
                    "insertion_code": residue.insertion_code,
                    "residue_name": residue.residue_name,
                    "feature_id": (
                        f"{residue.chain_id}:{residue.sequence_id}"
                        f"{residue.insertion_code}:{feature_type}:{index}"
                    ),
                    "feature_type": feature_type,
                    "x_angstrom": round(coordinate.x, 6),
                    "y_angstrom": round(coordinate.y, 6),
                    "z_angstrom": round(coordinate.z, 6),
                    "conserved_component_fraction": conserved_fraction,
                    "mean_chemical_group_conservation": chemical_conservation,
                    "stable_region_supported": stable,
                    "method": config.method_name,
                    "interpretation": (
                        "residue-derived pharmacophore hypothesis; not an FMO energy, "
                        "docking score or binding result"
                    ),
                }
            )
    return records


def _signature(records: Sequence[Mapping[str, Any]]) -> Counter[str]:
    """Return a feature-count signature for one evolutionary group."""
    return Counter(str(record["feature_type"]) for record in records)


def _spatial_signature(records: Sequence[Mapping[str, Any]]) -> Counter[str]:
    """Return a rotation-invariant feature-pair distance signature.

    Distances are binned in two-Angstrom intervals. The representation retains
    feature chemistry and approximate three-dimensional topology without
    requiring a structural superposition between unrelated candidate groups.
    """
    signature: Counter[str] = Counter()
    for left_index, left in enumerate(records):
        left_type = str(left["feature_type"])
        left_coordinate = Coordinate(
            float(left["x_angstrom"]),
            float(left["y_angstrom"]),
            float(left["z_angstrom"]),
        )
        for right in records[left_index + 1:]:
            right_type = str(right["feature_type"])
            right_coordinate = Coordinate(
                float(right["x_angstrom"]),
                float(right["y_angstrom"]),
                float(right["z_angstrom"]),
            )
            feature_pair = "|".join(sorted((left_type, right_type)))
            distance_bin = int(
                euclidean_distance(left_coordinate, right_coordinate) // 2.0
            )
            signature[f"{feature_pair}|distance_bin_{distance_bin}"] += 1
    return signature


def _weighted_jaccard(left: Counter[str], right: Counter[str]) -> float:
    """Return weighted Jaccard similarity for two feature-count signatures."""
    keys = set(left).union(right)
    denominator = sum(max(left[key], right[key]) for key in keys)
    if denominator == 0:
        return 0.0
    return sum(min(left[key], right[key]) for key in keys) / denominator


def summarise_groups(
    *,
    targets: Sequence[Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Summarise stability and between-group pharmacophore uniqueness."""
    features_by_group: dict[str, list[Mapping[str, Any]]] = {}
    for feature in features:
        key = str(feature["evolutionary_group_key"])
        features_by_group.setdefault(key, []).append(feature)
    feature_signatures = {
        key: _signature(group_features)
        for key, group_features in features_by_group.items()
    }
    spatial_signatures = {
        key: _spatial_signature(group_features)
        for key, group_features in features_by_group.items()
    }
    summaries = []
    for target in targets:
        key = str(target["evolutionary_group_key"])
        group_features = features_by_group.get(key, [])
        signature = feature_signatures.get(key, Counter())
        spatial_signature = spatial_signatures.get(key, Counter())
        feature_similarities = []
        spatial_similarities = []
        combined_similarities = []
        for other_key, other_signature in feature_signatures.items():
            if other_key == key:
                continue
            feature_similarity = _weighted_jaccard(signature, other_signature)
            other_spatial = spatial_signatures.get(other_key, Counter())
            spatial_similarity = _weighted_jaccard(
                spatial_signature,
                other_spatial,
            )
            combined_similarity = (
                0.4 * feature_similarity + 0.6 * spatial_similarity
                if spatial_signature and other_spatial
                else feature_similarity
            )
            feature_similarities.append(feature_similarity)
            spatial_similarities.append(spatial_similarity)
            combined_similarities.append(combined_similarity)
        maximum_feature_similarity = max(feature_similarities, default=0.0)
        maximum_spatial_similarity = max(spatial_similarities, default=0.0)
        maximum_similarity = max(combined_similarities, default=0.0)
        uniqueness = max(0.0, min(1.0, 1.0 - maximum_similarity))
        stable = (
            float(target["conserved_component_fraction"])
            >= config.minimum_conserved_component_fraction
            and float(target["mean_chemical_group_conservation"])
            >= config.minimum_chemical_group_conservation
        )
        unique = bool(group_features) and uniqueness >= config.minimum_uniqueness_score
        if not group_features:
            status = "NO_RESOLVED_PHARMACOPHORE_FEATURES"
        elif not stable:
            status = "INSUFFICIENT_EVOLUTIONARY_STABILITY"
        elif not unique:
            status = "INSUFFICIENT_BETWEEN_GROUP_UNIQUENESS"
        else:
            status = "READY_FOR_OPEN_FRAGMENT_PRIORITISATION"
        feature_types = sorted(signature)
        summaries.append(
            {
                "evolutionary_group_rank": target["evolutionary_group_rank"],
                "evolutionary_group_key": key,
                "primary_group_type": target["primary_group_type"],
                "primary_group_id": target["primary_group_id"],
                "cluster_id": target["cluster_id"],
                "candidate_accession": target["candidate_accession"],
                "pocket_number": target["pocket_number"],
                "feature_count": len(group_features),
                "feature_types": ";".join(feature_types),
                "feature_signature": ";".join(
                    f"{name}={signature[name]}" for name in feature_types
                ),
                "conserved_component_fraction": target[
                    "conserved_component_fraction"
                ],
                "mean_chemical_group_conservation": target[
                    "mean_chemical_group_conservation"
                ],
                "maximum_other_group_feature_similarity": round(
                    maximum_feature_similarity,
                    6,
                ),
                "maximum_other_group_spatial_similarity": round(
                    maximum_spatial_similarity,
                    6,
                ),
                "maximum_other_group_similarity": round(maximum_similarity, 6),
                "pharmacophore_uniqueness_score": round(uniqueness, 6),
                "stable_region_supported": stable,
                "unique_region_supported": unique,
                "chemistry_handoff_status": status,
                "method": config.method_name,
                "interpretation": (
                    "open residue-feature and pair-distance comparison; uniqueness "
                    "is relative only to the selected candidate-group panel"
                ),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            int(row["evolutionary_group_rank"]),
            str(row["evolutionary_group_key"]),
        ),
    )


def euclidean_distance(left: Coordinate, right: Coordinate) -> float:
    """Return Euclidean distance in Angstrom for defensive unit testing."""
    return math.sqrt(
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )
