"""Candidate-panel preparation, provenance and fail-closed validation tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from conftest import write_config, write_tsv
from e3chemistry.candidate_manifest import (
    prepare_candidate_manifest,
    prepare_candidate_manifest_files,
    validate_candidate_manifest,
)
from e3chemistry.config import load_config
from e3chemistry.errors import InputValidationError
from e3chemistry.io_utils import read_records
from e3chemistry.models import StructureAsset
from e3chemistry.structures import resolve_structure_assets


def _manifest_row(scientific_inputs: dict[str, Path]) -> dict[str, Any]:
    """Return the valid fixture manifest row."""
    return read_records(scientific_inputs["candidate_manifest"])[0]


def test_prepare_candidate_manifest_files_and_provenance(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """Expanded panel preparation must publish a checksummed exclusion audit."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    output = tmp_path / "panel"

    result = prepare_candidate_manifest_files(
        config=config,
        group_ranking_path=scientific_inputs["ranking"],
        selected_pockets_path=scientific_inputs["pockets"],
        pocket_residue_mappings_path=scientific_inputs["mappings"],
        structure_asset_manifest_path=scientific_inputs["assets"],
        output_dir=output,
        maximum_rank=200,
        decision_basis="EXPANDED_COMPUTATIONAL_SCREEN",
        decided_by="Peter Thorpe",
        rationale="Expanded test screen",
    )

    assert result["included_group_count"] == 1
    assert result["excluded_group_count"] == 0
    row = read_records(output / "candidate_manifest.tsv")[0]
    assert row["candidate_accession"] == "P00001"
    assert row["decision_basis"] == "EXPANDED_COMPUTATIONAL_SCREEN"
    provenance = json.loads(
        (output / "candidate_manifest_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["schema_version"] == 2
    assert provenance["candidate_manifest"]["sha256"]
    assert provenance["inputs"]["group_ranking"]["sha256"]

    with pytest.raises(InputValidationError, match="not empty"):
        prepare_candidate_manifest_files(
            config=config,
            group_ranking_path=scientific_inputs["ranking"],
            selected_pockets_path=scientific_inputs["pockets"],
            pocket_residue_mappings_path=scientific_inputs["mappings"],
            structure_asset_manifest_path=scientific_inputs["assets"],
            output_dir=output,
            maximum_rank=200,
            decision_basis="EXPANDED_COMPUTATIONAL_SCREEN",
            decided_by="Peter Thorpe",
            rationale="Expanded test screen",
        )


def test_quality_first_selection_and_missing_group_exclusion(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """Confidence must outrank druggability and unresolved groups remain audited."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    ranking = read_records(scientific_inputs["ranking"])
    ranking.append(
        {
            "evolutionary_group_rank": 2,
            "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG2",
            "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
            "primary_group_id": "HOG2",
            "lead_cluster_id": "DC2",
        }
    )
    pockets = read_records(scientific_inputs["pockets"])
    low_confidence = dict(pockets[0])
    low_confidence.update(
        {
            "pocket_number": 2,
            "druggability_score": 0.99,
            "conservative_fraction_plddt_ge_70": 0.1,
        }
    )
    pockets.append(low_confidence)
    mappings = read_records(scientific_inputs["mappings"])
    mappings.append(
        {
            **dict(mappings[0]),
            "pocket_number": 2,
        }
    )
    assets = resolve_structure_assets(read_records(scientific_inputs["assets"]))

    manifest, exclusions = prepare_candidate_manifest(
        config=config,
        group_ranking=ranking,
        selected_pockets=pockets,
        mappings=mappings,
        assets=assets,
        maximum_rank=2,
        decision_basis="expanded_computational_screen",
        decided_by="Peter Thorpe",
        rationale="Expanded test screen",
        decided_at_utc="2026-08-10T12:00:00Z",
    )

    assert manifest[0]["pocket_number"] == 1
    assert exclusions[0]["evolutionary_group_key"].endswith("HOG2")
    assert exclusions[0]["exclusion_reason"] == (
        "NO_CHECKSUM_BOUND_MAPPED_POCKET_STRUCTURE"
    )


def test_preparation_reassigns_or_excludes_overlapping_candidate_pockets(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """Overlapping groups must use a unique alternative or remain audited."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    ranking = read_records(scientific_inputs["ranking"])
    ranking.extend(
        [
            {
                "evolutionary_group_rank": 2,
                "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG2",
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "HOG2",
                "lead_cluster_id": "DC2",
            },
            {
                "evolutionary_group_rank": 3,
                "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG3",
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "HOG3",
                "lead_cluster_id": "DC3",
            },
        ]
    )
    original_pocket = read_records(scientific_inputs["pockets"])[0]
    pockets = [original_pocket]
    for group_id, cluster_id in (("HOG2", "DC2"), ("HOG3", "DC3")):
        pockets.append(
            {
                **original_pocket,
                "primary_group_id": group_id,
                "cluster_id": cluster_id,
            }
        )
    pockets.append(
        {
            **original_pocket,
            "primary_group_id": "HOG2",
            "cluster_id": "DC2_ALT",
            "candidate_accession": "P00002",
            "species_column": "Species_two",
            "pocket_number": 2,
            "druggability_score": 0.7,
            "conservative_fraction_plddt_ge_70": 0.8,
        }
    )
    mappings = read_records(scientific_inputs["mappings"])
    mappings.append(
        {
            **mappings[0],
            "accession": "P00002",
            "pocket_number": 2,
        }
    )
    first_asset = resolve_structure_assets(
        read_records(scientific_inputs["assets"])
    )["P00001"]
    assets = {
        "P00001": first_asset,
        "P00002": StructureAsset(
            accession="P00002",
            path=first_asset.path,
            sha256=first_asset.sha256,
        ),
    }

    manifest, exclusions = prepare_candidate_manifest(
        config=config,
        group_ranking=ranking,
        selected_pockets=pockets,
        mappings=mappings,
        assets=assets,
        maximum_rank=3,
        decision_basis="EXPANDED_COMPUTATIONAL_SCREEN",
        decided_by="Peter Thorpe",
        rationale="Expanded test screen",
        decided_at_utc="2026-08-11T07:45:00Z",
    )

    assert [row["candidate_accession"] for row in manifest] == ["P00001", "P00002"]
    assert [row["panel_order"] for row in manifest] == [1, 2]
    assert len(exclusions) == 1
    assert exclusions[0]["evolutionary_group_key"].endswith("HOG3")
    assert exclusions[0]["exclusion_reason"] == (
        "ALL_ELIGIBLE_CANDIDATE_POCKETS_ALREADY_ASSIGNED"
    )
    assert exclusions[0]["conflicting_candidate_pockets"] == "P00001/1"
    assert exclusions[0]["retained_evolutionary_group_keys"].endswith("HOG1")


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda rows: rows[0].update({"panel_order": 0}), "positive integer"),
        (lambda rows: rows[0].update({"decision_basis": "AUTOMATIC"}), "unsupported"),
        (lambda rows: rows[0].update({"structure_sha256": "bad"}), "invalid"),
        (lambda rows: rows[0].update({"decided_by": ""}), "empty fields"),
        (lambda rows: rows[0].update({"decided_at_utc": "today"}), "ISO-8601"),
        (
            lambda rows: rows[0].update(
                {"decided_at_utc": "2026-08-10T12:00:00+01:00"}
            ),
            "UTC timezone",
        ),
    ],
)
def test_invalid_candidate_manifest_rows_are_rejected(
    scientific_inputs: dict[str, Path],
    mutator: Any,
    message: str,
) -> None:
    """Malformed identity and decision provenance must fail closed."""
    rows = [_manifest_row(scientific_inputs)]
    mutator(rows)

    with pytest.raises(InputValidationError, match=message):
        validate_candidate_manifest(records=rows, maximum_candidate_groups=200)


def test_candidate_manifest_duplicate_and_panel_constraints(
    scientific_inputs: dict[str, Path],
) -> None:
    """Panel order, group, target, basis and configured size are strict."""
    first = _manifest_row(scientific_inputs)
    with pytest.raises(InputValidationError, match="maximum_candidate_groups"):
        validate_candidate_manifest(records=[first], maximum_candidate_groups=0)

    duplicate = deepcopy(first)
    duplicate["panel_order"] = 2
    with pytest.raises(InputValidationError, match="evolutionary group"):
        validate_candidate_manifest(
            records=[first, duplicate], maximum_candidate_groups=200
        )

    second = deepcopy(first)
    second.update(
        {
            "panel_order": 3,
            "evolutionary_group_rank": 2,
            "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG2",
            "primary_group_id": "HOG2",
            "cluster_id": "DC2",
            "candidate_accession": "P00002",
        }
    )
    with pytest.raises(InputValidationError, match="consecutive"):
        validate_candidate_manifest(records=[first, second], maximum_candidate_groups=200)

    second["panel_order"] = 2
    second["decision_basis"] = "PROJECT_LEAD_APPROVED"
    with pytest.raises(InputValidationError, match="consistent decision_basis"):
        validate_candidate_manifest(records=[first, second], maximum_candidate_groups=200)

    second["decision_basis"] = first["decision_basis"]
    second["candidate_accession"] = first["candidate_accession"]
    with pytest.raises(InputValidationError, match="accession/pocket"):
        validate_candidate_manifest(records=[first, second], maximum_candidate_groups=200)


def test_candidate_manifest_preparation_argument_errors(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """Unsafe preparation arguments and missing inputs must be explicit."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    inputs = {
        "group_ranking": read_records(scientific_inputs["ranking"]),
        "selected_pockets": read_records(scientific_inputs["pockets"]),
        "mappings": read_records(scientific_inputs["mappings"]),
        "assets": resolve_structure_assets(read_records(scientific_inputs["assets"])),
    }
    common = {
        "config": config,
        **inputs,
        "maximum_rank": 1,
        "decision_basis": "EXPANDED_COMPUTATIONAL_SCREEN",
        "decided_by": "Peter Thorpe",
        "rationale": "Expanded test screen",
    }
    with pytest.raises(InputValidationError, match="positive integer"):
        prepare_candidate_manifest(**{**common, "maximum_rank": 0})
    with pytest.raises(InputValidationError, match="Unsupported"):
        prepare_candidate_manifest(**{**common, "decision_basis": "AUTOMATIC"})
    with pytest.raises(InputValidationError, match="must not be empty"):
        prepare_candidate_manifest(**{**common, "decided_by": ""})

    missing = tmp_path / "missing.tsv"
    with pytest.raises(InputValidationError, match="group_ranking input"):
        prepare_candidate_manifest_files(
            config=config,
            group_ranking_path=missing,
            selected_pockets_path=scientific_inputs["pockets"],
            pocket_residue_mappings_path=scientific_inputs["mappings"],
            structure_asset_manifest_path=scientific_inputs["assets"],
            output_dir=tmp_path / "missing_output",
            maximum_rank=1,
            decision_basis="EXPANDED_COMPUTATIONAL_SCREEN",
            decided_by="Peter Thorpe",
            rationale="Expanded test screen",
        )
