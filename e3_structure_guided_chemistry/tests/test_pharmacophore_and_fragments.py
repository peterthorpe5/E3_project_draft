"""Residue feature, uniqueness and open fragment-ranking tests."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import write_config, write_tsv
from e3chemistry.config import load_config
from e3chemistry.errors import InputValidationError
from e3chemistry.fragments import (
    calculate_fragment_properties,
    load_fragment_properties,
    rank_fragments,
    score_fragment,
)
from e3chemistry.models import Coordinate, ResidueGeometry
from e3chemistry.pharmacophore import (
    _weighted_jaccard,
    build_feature_records,
    euclidean_distance,
    residue_feature_points,
    summarise_groups,
    one_at_a_time_sensitivity,
    threshold_sensitivity,
)


def _residue(name: str) -> ResidueGeometry:
    """Return one synthetic residue with representative side-chain atoms."""
    atoms = {
        "N": Coordinate(0.0, 0.0, 0.0),
        "CA": Coordinate(1.0, 0.0, 0.0),
        "C": Coordinate(2.0, 0.0, 0.0),
        "CB": Coordinate(1.0, 1.0, 0.0),
        "NZ": Coordinate(1.0, 2.0, 0.0),
        "CG": Coordinate(1.0, 2.0, 0.0),
        "OD1": Coordinate(0.5, 3.0, 0.0),
        "OD2": Coordinate(1.5, 3.0, 0.0),
    }
    return ResidueGeometry(
        accession="P1",
        pocket_number=1,
        chain_id="A",
        sequence_id="1",
        insertion_code="",
        residue_name=name,
        atoms=atoms,
    )


def _target(key: str = "HOG:H1") -> dict[str, object]:
    """Return one ready group target for pharmacophore tests."""
    return {
        "evolutionary_group_rank": 1,
        "evolutionary_group_key": key,
        "primary_group_type": "HOG",
        "primary_group_id": key.split(":", 1)[1],
        "cluster_id": "DC1",
        "candidate_accession": "P1",
        "pocket_number": 1,
        "conserved_component_fraction": 0.9,
        "mean_chemical_group_conservation": 0.8,
        "mapping_fraction": 1.0,
        "pocket_plddt_fraction": 1.0,
        "druggability_score": 0.8,
        "mapped_residue_count": 12,
        "mapping_quality_supported": True,
        "pocket_confidence_supported": True,
    }


def test_residue_features_and_distance() -> None:
    """Lysine and aspartate must expose chemically interpretable features."""
    lysine = {name for name, _ in residue_feature_points(_residue("LYS"))}
    aspartate = {name for name, _ in residue_feature_points(_residue("ASP"))}

    assert {"hydrogen_bond_donor", "positive_ionisable"}.issubset(lysine)
    assert {"hydrogen_bond_acceptor", "negative_ionisable"}.issubset(aspartate)
    assert euclidean_distance(Coordinate(0, 0, 0), Coordinate(3, 4, 0)) == 5.0
    hydrophobic = {name for name, _ in residue_feature_points(_residue("VAL"))}
    assert "hydrophobic" in hydrophobic
    assert _weighted_jaccard(Counter(), Counter()) == 0.0


def test_feature_records_and_group_uniqueness(tmp_path: Path) -> None:
    """Stable features must produce explicit within-panel uniqueness scores."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    first_target = _target("HOG:H1")
    second_target = {**_target("HOG:H2"), "evolutionary_group_rank": 2}
    first = build_feature_records(
        target=first_target,
        residues=[_residue("LYS")],
        config=config,
    )
    second = build_feature_records(
        target=second_target,
        residues=[_residue("ASP")],
        config=config,
    )
    summaries = summarise_groups(
        targets=[first_target, second_target],
        features=first + second,
        config=config,
    )

    assert all(row["stable_region_supported"] for row in summaries)
    assert all(row["druggability_supported"] for row in summaries)
    assert all(float(row["pharmacophore_uniqueness_score"]) > 0 for row in summaries)
    assert all("maximum_other_group_spatial_similarity" in row for row in summaries)
    assert "not an FMO energy" in first[0]["interpretation"]


def test_group_without_features_is_not_ready(tmp_path: Path) -> None:
    """A selected group cannot pass chemistry hand-off without resolved features."""
    config = load_config(write_config(tmp_path / "config.yaml"))

    summary = summarise_groups(targets=[_target()], features=[], config=config)[0]

    assert summary["chemistry_handoff_status"] == "NO_RESOLVED_PHARMACOPHORE_FEATURES"
    sensitivity = threshold_sensitivity(group_summaries=[], config=config)
    assert all(row["ready_group_fraction"] == 0.0 for row in sensitivity)
    one_at_a_time = one_at_a_time_sensitivity(
        group_summaries=[summary], config=config
    )
    assert {row["gate"] for row in one_at_a_time} == {
        "conserved_component_fraction",
        "chemical_group_conservation",
        "mapping_fraction",
        "pocket_plddt_fraction",
        "uniqueness_score",
        "druggability_score",
        "mapped_residue_count",
    }


@pytest.mark.parametrize(
    ("changes", "status", "reason"),
    [
        (
            {"mapping_fraction": 0.1},
            "INSUFFICIENT_MAPPING_QUALITY",
            "INSUFFICIENT_MAPPING_QUALITY",
        ),
        (
            {"conserved_component_fraction": 0.1},
            "INSUFFICIENT_EVOLUTIONARY_STABILITY",
            "INSUFFICIENT_CONSERVED_COMPONENT",
        ),
        (
            {"mean_chemical_group_conservation": 0.1},
            "INSUFFICIENT_EVOLUTIONARY_STABILITY",
            "INSUFFICIENT_CHEMICAL_GROUP_CONSERVATION",
        ),
    ],
)
def test_each_hand_off_gate_has_an_explicit_reason(
    tmp_path: Path,
    changes: dict[str, float],
    status: str,
    reason: str,
) -> None:
    """Mapping and both stability failures must remain distinguishable."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    target = {**_target(), **changes}
    features = build_feature_records(
        target=target,
        residues=[_residue("LYS")],
        config=config,
    )

    summary = summarise_groups(targets=[target], features=features, config=config)[0]

    assert summary["chemistry_handoff_status"] == status
    assert reason in summary["chemistry_handoff_failure_reasons"]


def test_non_unique_group_is_not_ready(tmp_path: Path) -> None:
    """A configured exact uniqueness requirement must reject identical groups."""
    config = replace(
        load_config(write_config(tmp_path / "config.yaml")),
        minimum_uniqueness_score=1.0,
    )
    first_target = _target("HOG:H1")
    second_target = {**_target("HOG:H2"), "evolutionary_group_rank": 2}
    first = build_feature_records(
        target=first_target,
        residues=[_residue("LYS")],
        config=config,
    )
    second = build_feature_records(
        target=second_target,
        residues=[_residue("LYS")],
        config=config,
    )

    summaries = summarise_groups(
        targets=[first_target, second_target],
        features=first + second,
        config=config,
    )

    assert all(
        row["chemistry_handoff_status"]
        == "INSUFFICIENT_BETWEEN_GROUP_UNIQUENESS"
        for row in summaries
    )


def test_rdkit_fragment_properties_and_invalid_smiles() -> None:
    """Valid and invalid SMILES must remain explicit in fragment properties."""
    valid = calculate_fragment_properties(
        {"fragment_id": "F1", "smiles": "CC(=O)N", "source": "test"}
    )
    invalid = calculate_fragment_properties(
        {"fragment_id": "F2", "smiles": "not-a-smiles", "source": "test"}
    )

    assert valid["rule_of_three_pass"] is True
    assert valid["canonical_smiles"]
    assert invalid["fragment_status"] == "INVALID_SMILES"


def test_duplicate_fragment_identifiers_are_rejected(tmp_path: Path) -> None:
    """Stable fragment identifiers are required for reproducible ranking."""
    library = write_tsv(
        tmp_path / "fragments.tsv",
        [
            {"fragment_id": "F1", "smiles": "CC"},
            {"fragment_id": "F1", "smiles": "CCC"},
        ],
    )

    with pytest.raises(InputValidationError, match="duplicate"):
        load_fragment_properties(library)


def test_fragment_score_and_deterministic_ranking(tmp_path: Path) -> None:
    """Rule-of-three fragments must rank deterministically by compatibility."""
    library = write_tsv(
        tmp_path / "fragments.tsv",
        [
            {"fragment_id": "F1", "smiles": "CC(=O)N", "source": "test"},
            {"fragment_id": "F2", "smiles": "c1ccncc1", "source": "test"},
        ],
    )
    config = load_config(
        write_config(
            tmp_path / "config.yaml",
            mode="open_fragment_screen",
            fragment_library=library,
        )
    )
    fragments = load_fragment_properties(library)
    target = _target()
    features = [
        {"evolutionary_group_key": "HOG:H1", "feature_type": "hydrogen_bond_acceptor"},
        {"evolutionary_group_key": "HOG:H1", "feature_type": "aromatic"},
    ]
    group = {
        **target,
        "chemistry_handoff_status": "READY_FOR_OPEN_FRAGMENT_PRIORITISATION",
    }
    ranking = rank_fragments(
        group_summaries=[group],
        features=features,
        fragments=fragments,
        config=config,
    )
    coverage, balance, score = score_fragment(
        target_signature=Counter({"hydrogen_bond_acceptor": 1}),
        fragment=fragments[0],
    )

    assert len(ranking) == 2
    assert [row["fragment_rank"] for row in ranking] == [1, 2]
    assert 0 <= coverage <= 1 and 0 <= balance <= 1 and 0 <= score <= 1
