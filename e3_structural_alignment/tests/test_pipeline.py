"""Tests for input validation, atomic execution and resume."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e3structalign.errors import InputValidationError, StructuralAlignmentError
from e3structalign.io_utils import read_records
from e3structalign.models import SelectedPocket
from e3structalign.pipeline import (
    AlignmentSettings,
    _sensitivity_group_summary,
    _sensitivity_member_summaries,
    parse_pocket_locators,
    parse_ranked_pockets,
    parse_selected_pockets,
    resolve_structure_assets,
    run_pipeline,
    validate_existing_output,
)


def test_complete_pipeline_and_resume(structural_inputs: dict[str, Path]) -> None:
    """Two translated pockets align, publish and resume without recomputation."""
    settings = AlignmentSettings(
        usalign_executable=str(structural_inputs["executable"]),
        tmalign_executable=str(structural_inputs["tmalign"]),
        threads=2,
    )
    manifest = run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
        pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
        asset_manifest_path=structural_inputs["assets"],
        output_dir=structural_inputs["output"],
        settings=settings,
        resume=False,
        force=False,
        verbose=True,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["validation"]["alignment_tools"] == ["US-align", "TM-align"]
    assert validate_existing_output(
        structural_inputs["output"],
        payload["run_digest"],
    )
    summaries = read_records(
        structural_inputs["output"]
        / "tables"
        / "structural_alignment_summary.parquet"
    )
    assert summaries[0]["alignment_status"] == "CONSERVED_3D_POCKET_SUPPORTED"
    assert summaries[0]["mean_pocket_overlap_fraction"] == 1.0
    assert summaries[0]["position_alignment_status"] == (
        "SAME_3D_POCKET_POSITION_SUPPORTED"
    )
    assert summaries[0]["mean_structural_chemical_group_conservation"] == 1.0
    sensitivity = read_records(
        structural_inputs["output"]
        / "tables"
        / "structural_pocket_sensitivity_group_summary.parquet"
    )
    assert sensitivity[0]["member_pocket_top_k"] == 1
    assert sensitivity[0]["sensitivity_alignment_status"] == (
        "CONSERVED_3D_POCKET_SUPPORTED"
    )
    residue_matches = read_records(
        structural_inputs["output"] / "tables" / "pocket_residue_matches.parquet"
    )
    assert len(residue_matches) == 4
    assert all(row["sequence_comparison_status"].startswith("ASSESSED") for row in residue_matches)
    static_report = (
        structural_inputs["output"]
        / "reports"
        / "structural_alignment_summary.html"
    )
    browser_index = (
        structural_inputs["output"]
        / "interactive"
        / "structural_alignment_browser.html"
    )
    assert "Mean TM-score" in static_report.read_text(encoding="utf-8")
    assert "Open 3D viewer" in browser_index.read_text(encoding="utf-8")
    pair_viewers = list(
        (structural_inputs["output"] / "interactive" / "pairs").rglob("*.html")
    )
    assert len(pair_viewers) == 2
    assert "Drag to rotate" in pair_viewers[0].read_text(encoding="utf-8")
    resumed = run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
        pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
        asset_manifest_path=structural_inputs["assets"],
        output_dir=structural_inputs["output"],
        settings=settings,
        resume=True,
        force=False,
        verbose=False,
    )
    assert resumed == manifest


def test_existing_output_requires_resume_or_force(
    structural_inputs: dict[str, Path],
) -> None:
    """An unvalidated existing output is never overwritten implicitly."""
    structural_inputs["output"].mkdir()
    with pytest.raises(StructuralAlignmentError, match="already exists"):
        run_pipeline(
            selected_pockets_path=structural_inputs["selected"],
            pocket_residue_mappings_path=structural_inputs["mappings"],
            asset_manifest_path=structural_inputs["assets"],
            output_dir=structural_inputs["output"],
            settings=AlignmentSettings(
                usalign_executable=str(structural_inputs["executable"]),
                tmalign_executable=str(structural_inputs["tmalign"]),
            ),
            resume=False,
            force=False,
            verbose=False,
        )


def test_preferred_reference_manifest_preserves_requested_plant_model(
    structural_inputs: dict[str, Path],
) -> None:
    """An explicit eligible reference overrides deterministic fallback selection."""
    reference_manifest = structural_inputs["output"].parent / "references.tsv"
    reference_manifest.write_text(
        "cluster_id\tprimary_group_type\tprimary_group_id\treference_accession\n"
        "cluster_1\torthogroup\tOG0001\tP2\n",
        encoding="utf-8",
    )
    output = structural_inputs["output"].parent / "preferred_reference"
    manifest = run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
        pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
        asset_manifest_path=structural_inputs["assets"],
        reference_manifest_path=reference_manifest,
        output_dir=output,
        settings=AlignmentSettings(
            usalign_executable=str(structural_inputs["executable"]),
            tmalign_executable=str(structural_inputs["tmalign"]),
            threads=1,
        ),
        resume=False,
        force=False,
        verbose=False,
    )
    assert manifest.is_file()
    summaries = read_records(
        output / "tables" / "structural_alignment_summary.parquet"
    )
    assert summaries[0]["reference_accession"] == "P2"


def test_selected_pocket_validation() -> None:
    """Empty identifiers and duplicate selections fail with context."""
    with pytest.raises(InputValidationError, match="no rows"):
        parse_selected_pockets([])
    row = {
        "cluster_id": "c",
        "primary_group_type": "orthogroup",
        "primary_group_id": "g",
        "candidate_accession": "A",
        "species_column": "s",
        "pocket_number": 1,
    }
    with pytest.raises(InputValidationError, match="Duplicate"):
        parse_selected_pockets([row, row])


@pytest.mark.parametrize(
    "settings",
    [
        AlignmentSettings(threads=0),
        AlignmentSettings(distance_threshold_angstrom=0.0),
        AlignmentSettings(minimum_global_tm_score=2.0),
        AlignmentSettings(usalign_executable=""),
        AlignmentSettings(run_usalign=False, run_tmalign=False),
        AlignmentSettings(member_pocket_top_k=21),
    ],
)
def test_invalid_settings(settings: AlignmentSettings) -> None:
    """Invalid resources and thresholds fail before output creation."""
    with pytest.raises(InputValidationError):
        settings.validate()


def test_selected_values_assets_and_locators_validate(
    structural_inputs: dict[str, Path],
) -> None:
    """Typed row conversion, checksums and residue filters reject bad evidence."""
    base = {
        "cluster_id": "c",
        "primary_group_type": "orthogroup",
        "primary_group_id": "g",
        "candidate_accession": "A",
        "species_column": "s",
        "pocket_number": 1,
    }
    for mutation, message in (
        ({"candidate_accession": ""}, "empty"),
        ({"pocket_number": "not-an-integer"}, "integer"),
        ({"predictor_agreement": "perhaps"}, "Boolean"),
        ({"druggability_score": "not-a-number"}, "numeric"),
    ):
        row = {**base, **mutation}
        with pytest.raises(InputValidationError, match=message):
            parse_selected_pockets([row])

    bad_assets = read_records(structural_inputs["assets"])
    bad_assets[0]["sha256"] = "0" * 64
    with pytest.raises(InputValidationError, match="checksum mismatch"):
        resolve_structure_assets(bad_assets)

    selected = parse_selected_pockets([base])
    mapping_rows = [
        {
            "accession": "A",
            "pocket_number": 2,
            "mapping_status": "MAPPED",
            "model_label_seq_id": "1",
        },
        {
            "accession": "A",
            "pocket_number": 1,
            "mapping_status": "UNMAPPED",
            "model_label_seq_id": "1",
        },
        {
            "accession": "A",
            "pocket_number": 1,
            "mapping_status": "MAPPED",
            "model_label_seq_id": "",
            "model_auth_seq_id": "",
        },
        {
            "accession": "A",
            "pocket_number": 1,
            "mapping_status": "MAPPED",
            "model_label_chain": "A",
            "model_label_seq_id": "1",
        },
    ]
    locators = parse_pocket_locators(mapping_rows + [mapping_rows[-1]], selected)
    assert len(locators["A"]) == 1


def test_top_k_member_pocket_requires_same_candidate_from_both_aligners() -> None:
    """A lower-ranked pocket rescues a member only with two-aligner agreement."""
    base = {
        "cluster_id": "c",
        "primary_group_type": "ORTHOGROUP",
        "primary_group_id": "g",
        "reference_accession": "REF",
        "mobile_accession": "MEM",
        "reference_species": "species_1",
        "mobile_species": "species_2",
        "status": "ASSESSED",
        "minimum_tm_score": 0.8,
        "symmetric_overlap_fraction": 0.8,
        "centroid_distance_angstrom": 2.0,
        "three_dimensional_pocket_score": 0.8,
    }
    strict_rows = [
        {
            **base,
            "alignment_tool": tool,
            "mobile_pocket_number": 1,
            "same_pocket_position_supported": False,
            "pocket_structure_conserved": False,
        }
        for tool in ("US-align", "TM-align")
    ]
    sensitivity_rows = []
    for tool in ("US-align", "TM-align"):
        sensitivity_rows.extend(
            (
                {
                    **strict_rows[0],
                    "alignment_tool": tool,
                    "mobile_pocket_rank": 1,
                    "strict_selected_mobile_pocket": True,
                },
                {
                    **base,
                    "alignment_tool": tool,
                    "mobile_pocket_number": 2,
                    "mobile_pocket_rank": 2,
                    "strict_selected_mobile_pocket": False,
                    "same_pocket_position_supported": True,
                    "pocket_structure_conserved": True,
                },
            )
        )
    settings = AlignmentSettings(member_pocket_top_k=5)
    rows = _sensitivity_member_summaries(
        sensitivity_comparisons=sensitivity_rows,
        strict_comparisons=strict_rows,
        alignment_tools=("US-align", "TM-align"),
        settings=settings,
    )
    assert rows[0]["best_mobile_pocket_number"] == 2
    assert rows[0]["conservation_rescued_by_alternative_pocket"]

    sensitivity_rows[-1]["pocket_structure_conserved"] = False
    sensitivity_rows[-1]["same_pocket_position_supported"] = False
    disagreement = _sensitivity_member_summaries(
        sensitivity_comparisons=sensitivity_rows,
        strict_comparisons=strict_rows,
        alignment_tools=("US-align", "TM-align"),
        settings=settings,
    )
    assert not disagreement[0]["same_pocket_position_supported"]
    assert not disagreement[0]["pocket_structure_conserved"]


def test_top_k_group_summary_preserves_strict_result() -> None:
    """Group sensitivity reports rescue while retaining strict fractions."""
    reference = SelectedPocket(
        cluster_id="c",
        primary_group_type="ORTHOGROUP",
        primary_group_id="g",
        accession="REF",
        species="species_1",
        pocket_number=1,
        druggability_score=0.9,
        mapping_fraction=1.0,
        pocket_plddt_fraction=0.9,
        predictor_agreement=True,
        structural_evidence_status="HIGH_CONFIDENCE_POCKET",
    )
    member = SelectedPocket(
        cluster_id="c",
        primary_group_type="ORTHOGROUP",
        primary_group_id="g",
        accession="MEM",
        species="species_2",
        pocket_number=1,
        druggability_score=0.8,
        mapping_fraction=1.0,
        pocket_plddt_fraction=0.8,
        predictor_agreement=True,
        structural_evidence_status="HIGH_CONFIDENCE_POCKET",
    )
    summary = _sensitivity_group_summary(
        records=(reference, member),
        reference=reference,
        eligible=(reference, member),
        strict_summary={
            "group_position_support_fraction": 0.5,
            "group_support_fraction": 0.5,
        },
        member_summaries=(
            {
                "mobile_accession": "MEM",
                "same_pocket_position_supported": True,
                "pocket_structure_conserved": True,
                "position_rescued_by_alternative_pocket": True,
                "conservation_rescued_by_alternative_pocket": True,
            },
        ),
        settings=AlignmentSettings(member_pocket_top_k=5),
    )
    assert summary["strict_group_support_fraction"] == 0.5
    assert summary["sensitivity_group_support_fraction"] == 1.0
    assert summary["sensitivity_alignment_status"] == (
        "CONSERVED_3D_POCKET_SUPPORTED"
    )


def test_ranked_pockets_validate_rank_and_limit() -> None:
    """Ranked pocket parsing rejects invalid ranks and applies top-k."""
    base = {
        "cluster_id": "c",
        "primary_group_type": "ORTHOGROUP",
        "primary_group_id": "g",
        "candidate_accession": "MEM",
        "species_column": "species",
        "pocket_number": 1,
        "selection_rank": 1,
    }
    ranked = parse_ranked_pockets(
        [
            base,
            {**base, "pocket_number": 2, "selection_rank": 2},
        ],
        maximum_rank=1,
    )
    assert [pocket.pocket_number for pocket in ranked] == [1]
    with pytest.raises(InputValidationError, match="positive"):
        parse_ranked_pockets(
            [{**base, "selection_rank": 0}],
            maximum_rank=5,
        )


def test_force_and_failed_attempt_retention(structural_inputs: dict[str, Path]) -> None:
    """Force preserves prior output and a failed rerun preserves its staging evidence."""
    output = structural_inputs["output"]
    output.mkdir()
    (output / "prior.txt").write_text("prior\n", encoding="utf-8")
    settings = AlignmentSettings(
        usalign_executable=str(structural_inputs["executable"]),
        tmalign_executable=str(structural_inputs["tmalign"]),
        threads=1,
    )
    manifest = run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
        pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
        asset_manifest_path=structural_inputs["assets"],
        output_dir=output,
        settings=settings,
        resume=False,
        force=True,
        verbose=False,
    )
    assert manifest.is_file()
    assert list(output.parent.glob(f"{output.name}.superseded.*"))

    with pytest.raises(Exception):
        run_pipeline(
            selected_pockets_path=structural_inputs["selected"],
            pocket_residue_mappings_path=structural_inputs["mappings"],
            pocket_sequence_coordinates_path=structural_inputs["sequence_coordinates"],
            asset_manifest_path=structural_inputs["assets"],
            output_dir=output,
            settings=AlignmentSettings(
                usalign_executable=str(output.parent / "missing-USalign"),
                tmalign_executable=str(output.parent / "missing-TMalign"),
                threads=1,
            ),
            resume=False,
            force=True,
            verbose=False,
        )
    assert list(output.parent.glob(f"{output.name}.failed.*"))
