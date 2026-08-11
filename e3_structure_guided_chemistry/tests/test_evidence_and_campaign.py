"""Lossless evidence integration and upstream campaign configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from e3chemistry.campaign_config import (
    build_full_universe_config,
    write_full_universe_config,
)
from e3chemistry.errors import InputValidationError
from e3chemistry.evidence import (
    build_field_dictionary,
    build_integrated_evidence,
    integrated_fieldnames,
)


def _evidence_inputs() -> dict[str, list[dict[str, object]]]:
    """Return one complete multi-layer evidence fixture."""
    identity = {
        "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
        "primary_group_id": "HOG1",
        "cluster_id": "DC1",
    }
    return {
        "ranking": [
            {
                **identity,
                "evolutionary_group_rank": 1,
                "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG1",
                "lead_expression_species_fraction": 0.8,
            }
        ],
        "pockets": [
            {
                **identity,
                "candidate_accession": "P1",
                "species_column": "Species_one",
                "pocket_number": 4,
                "druggability_score": 0.9,
            }
        ],
        "conservation": [
            {
                **identity,
                "structured_accession_count": 10,
                "conserved_component_accession_count": 9,
            }
        ],
        "targets": [
            {
                **identity,
                "evolutionary_group_rank": 1,
                "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG1",
                "candidate_accession": "P1",
                "species_column": "Species_one",
                "pocket_number": 4,
            }
        ],
        "summaries": [
            {
                **identity,
                "evolutionary_group_key": "HIERARCHICAL_ORTHOGROUP:HOG1",
                "chemistry_review_tier": "TIER_1_HIGH_CONFIDENCE_REVIEW",
                "chemistry_handoff_status": (
                    "READY_FOR_OPEN_FRAGMENT_PRIORITISATION"
                ),
                "chemistry_handoff_failure_reasons": "",
                "pharmacophore_uniqueness_score": 0.4,
            }
        ],
        "integrated": [
            {
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "HOG1",
                "final_rank": 7,
            }
        ],
        "structural": [
            {**identity, "alignment_status": "CONSERVED_3D_POCKET_SUPPORTED"}
        ],
    }


def test_lossless_integrated_evidence_and_dictionary() -> None:
    """Every evidence layer must remain prefixed, attributable and defined."""
    data = _evidence_inputs()
    rows = build_integrated_evidence(
        group_ranking=data["ranking"],
        selected_pockets=data["pockets"],
        conservation=data["conservation"],
        targets=data["targets"],
        group_summaries=data["summaries"],
        integrated_evidence=data["integrated"],
        structural_alignment=data["structural"],
    )

    assert rows[0]["ranking__lead_expression_species_fraction"] == 0.8
    assert rows[0]["pocket__druggability_score"] == 0.9
    assert rows[0]["conservation__structured_accession_count"] == 10
    assert rows[0]["integrated__final_rank"] == 7
    assert rows[0]["structural__alignment_status"].startswith("CONSERVED")
    fields = integrated_fieldnames(rows)
    assert fields[0] == "evolutionary_group_rank"
    dictionary = build_field_dictionary(records=rows)
    definition = {
        row["output_field"]: row["definition"] for row in dictionary
    }
    assert "without transformation" in definition["pocket__druggability_score"]


def test_integrated_evidence_rejects_ambiguous_or_missing_joins() -> None:
    """Duplicate authorities and missing exact pockets must fail closed."""
    data = _evidence_inputs()
    with pytest.raises(InputValidationError, match="Duplicate evolutionary-group"):
        build_integrated_evidence(
            group_ranking=data["ranking"] * 2,
            selected_pockets=data["pockets"],
            conservation=data["conservation"],
            targets=data["targets"],
            group_summaries=data["summaries"],
        )
    changed_target = {**data["targets"][0], "pocket_number": 99}
    with pytest.raises(InputValidationError, match="Could not join selected pocket"):
        build_integrated_evidence(
            group_ranking=data["ranking"],
            selected_pockets=data["pockets"],
            conservation=data["conservation"],
            targets=[changed_target],
            group_summaries=data["summaries"],
        )


def _workflow_template() -> dict[str, object]:
    """Return the minimal required upstream workflow template sections."""
    return {
        "schema_version": 1,
        "run": {"name": "old", "parent_run_root": "/old"},
        "analysis": {
            "prioritisation": {
                "structure_group_limit": 100,
                "final_candidate_limit": 50,
            }
        },
        "stages": {
            "09_ligandability": {"enabled": True},
            "09b_structural_alignment": {"enabled": True},
            "09c_computational_chemistry": {"enabled": True},
        },
    }


def test_full_universe_campaign_configuration_is_immutable(tmp_path: Path) -> None:
    """The generator must expand structure scope and disable embedded chemistry."""
    template = tmp_path / "template.yaml"
    template.write_text(
        yaml.safe_dump(_workflow_template(), sort_keys=False), encoding="utf-8"
    )
    output = tmp_path / "generated.yaml"
    common = {
        "template_path": template,
        "output_path": output,
        "run_name": "all1972_v0_15_0",
        "parent_run_root": tmp_path / "parent",
        "structure_group_limit": 1972,
    }

    created = write_full_universe_config(**common)
    unchanged = write_full_universe_config(**common)
    result = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert created["status"] == "created"
    assert unchanged["status"] == "unchanged"
    assert result["analysis"]["prioritisation"]["structure_group_limit"] == 1972
    assert result["stages"]["09c_computational_chemistry"]["enabled"] is False
    assert Path(result["path_base"]) == template.parent.resolve()
    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="conflicts"):
        write_full_universe_config(**common)


def test_campaign_configuration_handles_missing_and_invalid_templates(
    tmp_path: Path,
) -> None:
    """Missing, malformed and chemistry-free workflow templates are explicit."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(InputValidationError, match="missing or empty"):
        write_full_universe_config(
            template_path=missing,
            output_path=tmp_path / "unused.yaml",
            run_name="full_universe",
            parent_run_root=tmp_path / "parent",
            structure_group_limit=1972,
        )

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("stages: [\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Could not read"):
        write_full_universe_config(
            template_path=malformed,
            output_path=tmp_path / "also-unused.yaml",
            run_name="full_universe",
            parent_run_root=tmp_path / "parent",
            structure_group_limit=1972,
        )

    no_chemistry = _workflow_template()
    del no_chemistry["stages"]["09c_computational_chemistry"]
    result = build_full_universe_config(
        template=no_chemistry,
        run_name="full_universe",
        parent_run_root=tmp_path / "parent",
        structure_group_limit=1972,
    )
    assert "09c_computational_chemistry" not in result["stages"]

    relative_base = tmp_path / "relative-base.yaml"
    relative_template = _workflow_template()
    relative_template["path_base"] = "../project"
    relative_base.write_text(
        yaml.safe_dump(relative_template, sort_keys=False), encoding="utf-8"
    )
    relative_output = tmp_path / "elsewhere" / "generated.yaml"
    write_full_universe_config(
        template_path=relative_base,
        output_path=relative_output,
        run_name="full_universe_relative",
        parent_run_root=tmp_path / "parent",
        structure_group_limit=1972,
    )
    relative_result = yaml.safe_load(relative_output.read_text(encoding="utf-8"))
    assert Path(relative_result["path_base"]) == (tmp_path / "../project").resolve()

    invalid_path_base = tmp_path / "invalid-path-base.yaml"
    invalid_template = _workflow_template()
    invalid_template["path_base"] = []
    invalid_path_base.write_text(
        yaml.safe_dump(invalid_template, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(InputValidationError, match="path_base"):
        write_full_universe_config(
            template_path=invalid_path_base,
            output_path=tmp_path / "invalid-output.yaml",
            run_name="full_universe_invalid",
            parent_run_root=tmp_path / "parent",
            structure_group_limit=1972,
        )


@pytest.mark.parametrize(
    ("run_name", "limit", "message"),
    [("", 10, "run_name"), ("has spaces", 10, "run_name"), ("valid", 0, "between")],
)
def test_campaign_configuration_rejects_unsafe_scope(
    tmp_path: Path, run_name: str, limit: int, message: str
) -> None:
    """Unsafe names, limits and incomplete templates must not be accepted."""
    with pytest.raises(InputValidationError, match=message):
        build_full_universe_config(
            template=_workflow_template(),
            run_name=run_name,
            parent_run_root=tmp_path,
            structure_group_limit=limit,
        )
    with pytest.raises(InputValidationError, match="analysis"):
        build_full_universe_config(
            template={"run": {}, "stages": {}},
            run_name="valid",
            parent_run_root=tmp_path,
            structure_group_limit=10,
        )
