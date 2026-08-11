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
    "mapping_fraction",
    "pocket_plddt_fraction",
    "druggability_score",
    "mapped_residue_count",
    "stable_region_supported",
    "mapping_quality_supported",
    "pocket_confidence_supported",
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
    "mapping_fraction",
    "pocket_plddt_fraction",
    "druggability_score",
    "mapped_residue_count",
    "maximum_other_group_feature_similarity",
    "maximum_other_group_spatial_similarity",
    "maximum_other_group_similarity",
    "pharmacophore_uniqueness_score",
    "stable_region_supported",
    "mapping_quality_supported",
    "pocket_confidence_supported",
    "druggability_supported",
    "mapped_residue_count_supported",
    "unique_region_supported",
    "biology_and_structure_supported",
    "high_confidence_core_supported",
    "chemistry_review_tier",
    "chemistry_handoff_status",
    "chemistry_handoff_failure_reasons",
    "method",
    "interpretation",
)

SENSITIVITY_FIELDS = (
    "minimum_conserved_component_fraction",
    "minimum_chemical_group_conservation",
    "minimum_mapping_fraction",
    "minimum_pocket_plddt_fraction",
    "minimum_uniqueness_score",
    "minimum_druggability_score",
    "minimum_mapped_residue_count",
    "ready_group_count",
    "ready_group_fraction",
    "is_configured_threshold_combination",
)

ONE_AT_A_TIME_SENSITIVITY_FIELDS = (
    "gate",
    "threshold",
    "threshold_type",
    "ready_group_count",
    "ready_group_fraction",
    "change_from_configured_count",
    "ready_evolutionary_group_keys",
    "is_configured_threshold",
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
                    "mapping_fraction": target["mapping_fraction"],
                    "pocket_plddt_fraction": target["pocket_plddt_fraction"],
                    "druggability_score": target["druggability_score"],
                    "mapped_residue_count": target["mapped_residue_count"],
                    "stable_region_supported": stable,
                    "mapping_quality_supported": target[
                        "mapping_quality_supported"
                    ],
                    "pocket_confidence_supported": target[
                        "pocket_confidence_supported"
                    ],
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
    pairwise_maxima = {
        key: {"feature": 0.0, "spatial": 0.0, "combined": 0.0}
        for key in feature_signatures
    }
    signature_keys = sorted(feature_signatures)
    for left_index, key in enumerate(signature_keys):
        for other_key in signature_keys[left_index + 1:]:
            feature_similarity = _weighted_jaccard(
                feature_signatures[key], feature_signatures[other_key]
            )
            spatial_signature = spatial_signatures.get(key, Counter())
            other_spatial = spatial_signatures.get(other_key, Counter())
            spatial_similarity = _weighted_jaccard(
                spatial_signature, other_spatial
            )
            combined_similarity = (
                0.4 * feature_similarity + 0.6 * spatial_similarity
                if spatial_signature and other_spatial
                else feature_similarity
            )
            for current_key in (key, other_key):
                pairwise_maxima[current_key]["feature"] = max(
                    pairwise_maxima[current_key]["feature"], feature_similarity
                )
                pairwise_maxima[current_key]["spatial"] = max(
                    pairwise_maxima[current_key]["spatial"], spatial_similarity
                )
                pairwise_maxima[current_key]["combined"] = max(
                    pairwise_maxima[current_key]["combined"], combined_similarity
                )
    summaries = []
    for target in targets:
        key = str(target["evolutionary_group_key"])
        group_features = features_by_group.get(key, [])
        signature = feature_signatures.get(key, Counter())
        maxima = pairwise_maxima.get(
            key, {"feature": 0.0, "spatial": 0.0, "combined": 0.0}
        )
        maximum_feature_similarity = maxima["feature"]
        maximum_spatial_similarity = maxima["spatial"]
        maximum_similarity = maxima["combined"]
        uniqueness = max(0.0, min(1.0, 1.0 - maximum_similarity))
        stable = (
            float(target["conserved_component_fraction"])
            >= config.minimum_conserved_component_fraction
            and float(target["mean_chemical_group_conservation"])
            >= config.minimum_chemical_group_conservation
        )
        mapping_supported = (
            float(target["mapping_fraction"]) >= config.minimum_mapping_fraction
        )
        confidence_supported = (
            float(target["pocket_plddt_fraction"])
            >= config.minimum_pocket_plddt_fraction
        )
        druggability_supported = (
            float(target["druggability_score"])
            >= config.minimum_druggability_score
        )
        residue_count_supported = (
            int(target["mapped_residue_count"])
            >= config.minimum_mapped_residue_count
        )
        unique = bool(group_features) and uniqueness >= config.minimum_uniqueness_score
        failure_reasons = []
        if not group_features:
            status = "NO_RESOLVED_PHARMACOPHORE_FEATURES"
            failure_reasons.append(status)
        if not mapping_supported:
            failure_reasons.append("INSUFFICIENT_MAPPING_QUALITY")
        if not confidence_supported:
            failure_reasons.append("INSUFFICIENT_POCKET_CONFIDENCE")
        if (
            float(target["conserved_component_fraction"])
            < config.minimum_conserved_component_fraction
        ):
            failure_reasons.append("INSUFFICIENT_CONSERVED_COMPONENT")
        if (
            float(target["mean_chemical_group_conservation"])
            < config.minimum_chemical_group_conservation
        ):
            failure_reasons.append("INSUFFICIENT_CHEMICAL_GROUP_CONSERVATION")
        if group_features and not unique:
            failure_reasons.append("INSUFFICIENT_BETWEEN_GROUP_UNIQUENESS")
        if not druggability_supported:
            failure_reasons.append("INSUFFICIENT_REPRESENTATIVE_DRUGGABILITY")
        if not residue_count_supported:
            failure_reasons.append("INSUFFICIENT_MAPPED_POCKET_RESIDUES")
        biology_supported = bool(
            group_features
            and mapping_supported
            and confidence_supported
            and stable
            and unique
        )
        configured_handoff = bool(
            biology_supported
            and druggability_supported
            and residue_count_supported
        )
        high_confidence = bool(
            configured_handoff
            and float(target["conserved_component_fraction"])
            >= config.high_confidence_conserved_component_fraction
            and float(target["mean_chemical_group_conservation"])
            >= config.high_confidence_chemical_group_conservation
            and float(target["pocket_plddt_fraction"])
            >= config.high_confidence_pocket_plddt_fraction
            and float(target["druggability_score"])
            >= config.high_confidence_druggability_score
            and int(target["mapped_residue_count"])
            >= config.high_confidence_mapped_residue_count
        )
        if not group_features:
            status = "NO_RESOLVED_PHARMACOPHORE_FEATURES"
        elif not mapping_supported:
            status = "INSUFFICIENT_MAPPING_QUALITY"
        elif not confidence_supported:
            status = "INSUFFICIENT_POCKET_CONFIDENCE"
        elif not stable:
            status = "INSUFFICIENT_EVOLUTIONARY_STABILITY"
        elif not unique:
            status = "INSUFFICIENT_BETWEEN_GROUP_UNIQUENESS"
        elif not druggability_supported:
            status = "INSUFFICIENT_REPRESENTATIVE_DRUGGABILITY"
        elif not residue_count_supported:
            status = "INSUFFICIENT_MAPPED_POCKET_RESIDUES"
        else:
            status = "READY_FOR_OPEN_FRAGMENT_PRIORITISATION"
        if high_confidence:
            review_tier = "TIER_1_HIGH_CONFIDENCE_REVIEW"
        elif configured_handoff:
            review_tier = "TIER_2_CONFIGURED_CHEMISTRY_HANDOFF"
        elif biology_supported and not druggability_supported:
            review_tier = "STRUCTURALLY_SUPPORTED_LOW_DRUGGABILITY"
        elif biology_supported and not residue_count_supported:
            review_tier = "STRUCTURALLY_SUPPORTED_SMALL_MAPPED_POCKET"
        elif biology_supported:
            review_tier = "STRUCTURALLY_SUPPORTED_CHEMISTRY_LIMITED"
        else:
            review_tier = "NOT_SUPPORTED_AT_CONFIGURED_GATES"
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
                "mapping_fraction": target["mapping_fraction"],
                "pocket_plddt_fraction": target["pocket_plddt_fraction"],
                "druggability_score": target["druggability_score"],
                "mapped_residue_count": target["mapped_residue_count"],
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
                "mapping_quality_supported": mapping_supported,
                "pocket_confidence_supported": confidence_supported,
                "druggability_supported": druggability_supported,
                "mapped_residue_count_supported": residue_count_supported,
                "unique_region_supported": unique,
                "biology_and_structure_supported": biology_supported,
                "high_confidence_core_supported": high_confidence,
                "chemistry_review_tier": review_tier,
                "chemistry_handoff_status": status,
                "chemistry_handoff_failure_reasons": ";".join(failure_reasons),
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


def threshold_sensitivity(
    *,
    group_summaries: Sequence[Mapping[str, Any]],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Evaluate a transparent grid around the configured chemistry gates."""
    conservation_thresholds = sorted(
        {0.25, 0.5, 0.75, config.minimum_conserved_component_fraction}
    )
    chemical_thresholds = sorted(
        {0.5, 0.6, 0.8, config.minimum_chemical_group_conservation}
    )
    confidence_thresholds = sorted(
        {0.5, 0.7, 0.9, config.minimum_pocket_plddt_fraction}
    )
    uniqueness_thresholds = sorted(
        {0.1, 0.2, 0.25, 0.3, 0.4, 0.5, config.minimum_uniqueness_score}
    )
    druggability_thresholds = sorted(
        {0.2, 0.5, 0.7, config.minimum_druggability_score}
    )
    rows = []
    denominator = len(group_summaries)
    for conservation_threshold in conservation_thresholds:
        for chemical_threshold in chemical_thresholds:
            for confidence_threshold in confidence_thresholds:
                for uniqueness_threshold in uniqueness_thresholds:
                    for druggability_threshold in druggability_thresholds:
                        ready_count = sum(
                            _passes_thresholds(
                                row=row,
                                conserved_component=conservation_threshold,
                                chemical_conservation=chemical_threshold,
                                mapping=config.minimum_mapping_fraction,
                                pocket_plddt=confidence_threshold,
                                uniqueness=uniqueness_threshold,
                                druggability=druggability_threshold,
                                mapped_residue_count=(
                                    config.minimum_mapped_residue_count
                                ),
                            )
                            for row in group_summaries
                        )
                        rows.append(
                            {
                                "minimum_conserved_component_fraction": (
                                    conservation_threshold
                                ),
                                "minimum_chemical_group_conservation": (
                                    chemical_threshold
                                ),
                                "minimum_mapping_fraction": (
                                    config.minimum_mapping_fraction
                                ),
                                "minimum_pocket_plddt_fraction": (
                                    confidence_threshold
                                ),
                                "minimum_uniqueness_score": uniqueness_threshold,
                                "minimum_druggability_score": (
                                    druggability_threshold
                                ),
                                "minimum_mapped_residue_count": (
                                    config.minimum_mapped_residue_count
                                ),
                                "ready_group_count": ready_count,
                                "ready_group_fraction": (
                                    round(ready_count / denominator, 6)
                                    if denominator
                                    else 0.0
                                ),
                                "is_configured_threshold_combination": (
                                    conservation_threshold
                                    == config.minimum_conserved_component_fraction
                                    and chemical_threshold
                                    == config.minimum_chemical_group_conservation
                                    and confidence_threshold
                                    == config.minimum_pocket_plddt_fraction
                                    and uniqueness_threshold
                                    == config.minimum_uniqueness_score
                                    and druggability_threshold
                                    == config.minimum_druggability_score
                                ),
                            }
                        )
    return rows


def _passes_thresholds(
    *,
    row: Mapping[str, Any],
    conserved_component: float,
    chemical_conservation: float,
    mapping: float,
    pocket_plddt: float,
    uniqueness: float,
    druggability: float,
    mapped_residue_count: int,
) -> bool:
    """Return whether one summary passes an explicit threshold set."""
    return bool(
        int(row["feature_count"]) > 0
        and float(row["conserved_component_fraction"]) >= conserved_component
        and float(row["mean_chemical_group_conservation"])
        >= chemical_conservation
        and float(row["mapping_fraction"]) >= mapping
        and float(row["pocket_plddt_fraction"]) >= pocket_plddt
        and float(row["pharmacophore_uniqueness_score"]) >= uniqueness
        and float(row["druggability_score"]) >= druggability
        and int(row["mapped_residue_count"]) >= mapped_residue_count
    )


def one_at_a_time_sensitivity(
    *,
    group_summaries: Sequence[Mapping[str, Any]],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Vary each gate alone while holding every other gate configured."""
    thresholds: dict[str, tuple[str, Sequence[float | int]]] = {
        "conserved_component_fraction": (
            "fraction",
            sorted({0.25, 0.5, 0.75, config.minimum_conserved_component_fraction}),
        ),
        "chemical_group_conservation": (
            "fraction",
            sorted({0.5, 0.6, 0.8, config.minimum_chemical_group_conservation}),
        ),
        "mapping_fraction": (
            "fraction",
            sorted({0.8, 0.95, 1.0, config.minimum_mapping_fraction}),
        ),
        "pocket_plddt_fraction": (
            "fraction",
            sorted({0.5, 0.7, 0.9, config.minimum_pocket_plddt_fraction}),
        ),
        "uniqueness_score": (
            "fraction",
            sorted({0.1, 0.2, 0.25, 0.3, 0.4, 0.5, config.minimum_uniqueness_score}),
        ),
        "druggability_score": (
            "fraction",
            sorted({0.2, 0.5, 0.7, config.minimum_druggability_score}),
        ),
        "mapped_residue_count": (
            "count",
            sorted({5, 10, 15, config.minimum_mapped_residue_count}),
        ),
    }
    configured = {
        "conserved_component_fraction": config.minimum_conserved_component_fraction,
        "chemical_group_conservation": config.minimum_chemical_group_conservation,
        "mapping_fraction": config.minimum_mapping_fraction,
        "pocket_plddt_fraction": config.minimum_pocket_plddt_fraction,
        "uniqueness_score": config.minimum_uniqueness_score,
        "druggability_score": config.minimum_druggability_score,
        "mapped_residue_count": config.minimum_mapped_residue_count,
    }
    denominator = len(group_summaries)

    def passing_keys(values: Mapping[str, float | int]) -> list[str]:
        return sorted(
            str(row["evolutionary_group_key"])
            for row in group_summaries
            if _passes_thresholds(
                row=row,
                conserved_component=float(values["conserved_component_fraction"]),
                chemical_conservation=float(values["chemical_group_conservation"]),
                mapping=float(values["mapping_fraction"]),
                pocket_plddt=float(values["pocket_plddt_fraction"]),
                uniqueness=float(values["uniqueness_score"]),
                druggability=float(values["druggability_score"]),
                mapped_residue_count=int(values["mapped_residue_count"]),
            )
        )

    configured_count = len(passing_keys(configured))
    rows: list[dict[str, Any]] = []
    for gate, (threshold_type, values) in thresholds.items():
        for threshold in values:
            scenario = dict(configured)
            scenario[gate] = threshold
            keys = passing_keys(scenario)
            rows.append(
                {
                    "gate": gate,
                    "threshold": threshold,
                    "threshold_type": threshold_type,
                    "ready_group_count": len(keys),
                    "ready_group_fraction": (
                        round(len(keys) / denominator, 6) if denominator else 0.0
                    ),
                    "change_from_configured_count": (
                        len(keys) - configured_count
                    ),
                    "ready_evolutionary_group_keys": ";".join(keys),
                    "is_configured_threshold": threshold == configured[gate],
                }
            )
    return rows


def euclidean_distance(left: Coordinate, right: Coordinate) -> float:
    """Return Euclidean distance in Angstrom for defensive unit testing."""
    return math.sqrt(
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )
