"""Tests for input validation, atomic execution and resume."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e3structalign.errors import InputValidationError, StructuralAlignmentError
from e3structalign.io_utils import read_records
from e3structalign.pipeline import (
    AlignmentSettings,
    parse_pocket_locators,
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
    resumed = run_pipeline(
        selected_pockets_path=structural_inputs["selected"],
        pocket_residue_mappings_path=structural_inputs["mappings"],
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
