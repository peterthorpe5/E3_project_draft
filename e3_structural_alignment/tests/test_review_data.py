"""Tests for pocket-review discovery, joins and annotations."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from e3structalign.errors import InputValidationError
from e3structalign.io_utils import quote_literal
from e3structalign.models import SelectedPocket
from e3structalign.review_data import (
    _alignment_payload,
    _protein_payload,
    alignment_path,
    alignment_position_map,
    choose_reference,
    group_key,
    input_digest,
    json_safe_record,
    load_report_payloads,
    read_fasta,
    resolve_review_inputs,
    review_rank,
)
from e3structalign.models import PocketSequenceCoordinate, ResidueLocator
from e3structalign.review_models import ReviewInputOverrides, ReviewSettings


def test_resolve_and_load_complete_review_payload(
    review_run: dict[str, Path],
) -> None:
    """A completed run becomes one fully annotated group payload."""
    inputs = resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=ReviewInputOverrides(),
    )
    settings = ReviewSettings(review_limit=50, member_pocket_top_k=5)
    digest, inventory = input_digest(inputs=inputs, settings=settings)
    payloads = load_report_payloads(inputs=inputs, settings=settings)
    assert len(digest) == 64
    assert len(inventory) == 8
    assert payloads[0]["review_rank"] == 1
    assert payloads[0]["reference_accession"] == "P1"
    assert payloads[0]["reference_source"] == "STRUCTURAL_ALIGNMENT_SUMMARY"
    assert len(payloads[0]["proteins"]) == 2
    assert payloads[0]["proteins"][0]["mapped_pocket_atom_count"] == 2
    assert payloads[0]["alignment"]["alignment_length"] == 2
    assert len(payloads[0]["alignment"]["records"][0]["pocket_annotations"]) == 2


def test_group_and_alignment_helpers(tmp_path: Path) -> None:
    """Group identifiers and aligned coordinates are deterministic."""
    record = {
        "lead_cluster_id": "cluster 1",
        "primary_group_type": "orthogroup",
        "primary_group_id": "OG/1",
    }
    key = group_key(record)
    assert key == ("cluster 1", "orthogroup", "OG/1")
    assert alignment_position_map("A--BC.") == {1: 0, 2: 3, 3: 4}
    assert alignment_path(alignments_root=tmp_path, key=key) == (
        tmp_path / "cluster_1__OG_1" / "aligned.fasta"
    )
    with pytest.raises(InputValidationError):
        group_key({"lead_cluster_id": "cluster"})
    assert review_rank({"final_evolutionary_rank": "2"}) == 2
    for value in ("bad", None, 0):
        with pytest.raises(InputValidationError):
            review_rank({"final_evolutionary_rank": value})


def test_read_fasta_rejects_malformed_inputs(tmp_path: Path) -> None:
    """FASTA reader fails closed for duplicate, unequal and malformed records."""
    valid = tmp_path / "valid.fasta"
    valid.write_text(">A description\nA-\n>B\nAA\n", encoding="utf-8")
    assert read_fasta(valid) == {"A": "A-", "B": "AA"}
    cases = (
        ("before.fasta", "AA\n"),
        ("empty_id.fasta", ">\nAA\n"),
        ("empty_record.fasta", ">A\n>B\nAA\n"),
        ("duplicate.fasta", ">A\nAA\n>A\nAA\n"),
        ("unequal.fasta", ">A\nA\n>B\nAA\n"),
        ("symbol.fasta", ">A\nA1\n"),
    )
    for name, content in cases:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        with pytest.raises(InputValidationError):
            read_fasta(path)


def test_reference_selection_and_json_safety() -> None:
    """Reference fallback and non-primitive table values are explicit."""
    pocket = SelectedPocket(
        cluster_id="cluster",
        primary_group_type="orthogroup",
        primary_group_id="OG",
        accession="P1",
        species="species",
        pocket_number=1,
        druggability_score=0.9,
        mapping_fraction=1.0,
        pocket_plddt_fraction=1.0,
        predictor_agreement=True,
        structural_evidence_status="SELECTED_HIGH_CONFIDENCE",
    )
    assert choose_reference(summary={}, selected=[pocket]) == (
        "P1",
        "INFERRED_FROM_SELECTED_POCKET_EVIDENCE",
    )
    with pytest.raises(InputValidationError):
        choose_reference(summary={}, selected=[])
    with pytest.raises(InputValidationError):
        choose_reference(
            summary={"reference_accession": "OTHER"},
            selected=[pocket],
        )
    unknown = object()
    assert json_safe_record({"path": Path("/tmp/example"), "value": unknown}) == {
        "path": "/tmp/example",
        "value": str(unknown),
    }


def test_discovery_requires_conventional_inputs(tmp_path: Path) -> None:
    """Automatic discovery rejects absent roots and missing authorities."""
    with pytest.raises(InputValidationError):
        resolve_review_inputs(
            run_root=tmp_path / "missing",
            overrides=ReviewInputOverrides(),
        )
    run_root = tmp_path / "run"
    run_root.mkdir()
    with pytest.raises(InputValidationError):
        resolve_review_inputs(
            run_root=run_root,
            overrides=ReviewInputOverrides(),
        )


def test_discovery_prefers_generic_parquet_when_both_formats_exist(
    review_run: dict[str, Path],
) -> None:
    """Production TSV/Parquet pairs resolve deterministically to Parquet."""
    final_results = (
        review_run["run_root"]
        / "10_integrated_resource"
        / "final_results"
    )
    generic_parquet = final_results / "top_computational_review_shortlist.parquet"
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "COPY (SELECT * FROM read_csv("
            f"{quote_literal(review_run['shortlist'])}, "
            "delim='\\t', header=true, all_varchar=true)) TO "
            f"{quote_literal(generic_parquet)} (FORMAT PARQUET)"
        )
    finally:
        connection.close()
    discovered = resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=ReviewInputOverrides(),
    )
    assert discovered.shortlist == generic_parquet.resolve()


def test_explicit_input_overrides_and_invalid_alignment_root(
    review_run: dict[str, Path],
) -> None:
    """Every conventional authority can be supplied explicitly."""
    discovered = resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=ReviewInputOverrides(),
    )
    overrides = ReviewInputOverrides(
        shortlist=discovered.shortlist,
        selected_pockets=discovered.selected_pockets,
        ranked_pockets=discovered.ranked_pockets,
        ranked_pocket_sequence_coordinates=(
            discovered.ranked_pocket_sequence_coordinates
        ),
        asset_manifest=discovered.asset_manifest,
        alignments_root=discovered.alignments_root,
        structural_summary=discovered.structural_summary,
        sensitivity_group_summary=discovered.sensitivity_group_summary,
        sensitivity_member_summary=discovered.sensitivity_member_summary,
    )
    assert resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=overrides,
    ) == discovered
    with pytest.raises(InputValidationError):
        resolve_review_inputs(
            run_root=review_run["run_root"],
            overrides=ReviewInputOverrides(
                alignments_root=review_run["run_root"] / "missing"
            ),
        )


def test_blank_fasta_and_missing_report_alignment(
    tmp_path: Path,
    review_run: dict[str, Path],
) -> None:
    """Blank alignments fail, while absent group alignments remain explicit."""
    blank = tmp_path / "blank.fasta"
    blank.write_text("\n", encoding="utf-8")
    with pytest.raises(InputValidationError):
        read_fasta(blank)
    review_run["alignment"].unlink()
    inputs = resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=ReviewInputOverrides(),
    )
    payload = load_report_payloads(
        inputs=inputs,
        settings=ReviewSettings(),
    )[0]
    assert payload["alignment"]["status"] == "UNAVAILABLE"


def test_missing_model_and_coordinate_failure_branches() -> None:
    """Unavailable models and invalid exact FASTA coordinates are explicit."""
    pocket = SelectedPocket(
        cluster_id="cluster",
        primary_group_type="orthogroup",
        primary_group_id="OG",
        accession="P1",
        species="species",
        pocket_number=1,
        druggability_score=0.9,
        mapping_fraction=1.0,
        pocket_plddt_fraction=1.0,
        predictor_agreement=True,
        structural_evidence_status="SELECTED_HIGH_CONFIDENCE",
    )
    protein = _protein_payload(
        pocket_records=[pocket],
        coordinate_index={},
        asset=None,
        reference_accession="P1",
    )
    assert protein["model_status"] == "MODEL_UNAVAILABLE"
    locator = ResidueLocator("A", "1", "A", "1", "")
    base = PocketSequenceCoordinate(
        accession="P1",
        pocket_number=1,
        locator=locator,
        structure_residue_name="ALA",
        fasta_position=2,
        fasta_residue="A",
        sequence_coordinate_status="MAPPED_EXACT",
    )
    proteins = [
        {
            "accession": "P1",
            "species": "species",
            "is_reference": True,
        }
    ]
    unannotated_alignment = _alignment_payload(
        sequences={"OTHER": "A"},
        proteins=proteins,
        coordinate_index={},
        ranked_by_accession={},
    )
    assert unannotated_alignment["status"] == "AVAILABLE"
    assert not unannotated_alignment["records"][0]["has_ranked_pocket_evidence"]
    with pytest.raises(InputValidationError, match="exceeds"):
        _alignment_payload(
            sequences={"P1": "A"},
            proteins=proteins,
            coordinate_index={("P1", 1): (base,)},
            ranked_by_accession={"P1": [pocket]},
        )
    mismatch = PocketSequenceCoordinate(
        accession="P1",
        pocket_number=1,
        locator=locator,
        structure_residue_name="ALA",
        fasta_position=1,
        fasta_residue="G",
        sequence_coordinate_status="MAPPED_EXACT",
    )
    with pytest.raises(InputValidationError, match="identity disagrees"):
        _alignment_payload(
            sequences={"P1": "A"},
            proteins=proteins,
            coordinate_index={("P1", 1): (mismatch,)},
            ranked_by_accession={"P1": [pocket]},
        )
    unavailable = PocketSequenceCoordinate(
        accession="P1",
        pocket_number=1,
        locator=locator,
        structure_residue_name="ALA",
        fasta_position=None,
        fasta_residue="",
        sequence_coordinate_status="UNMAPPED",
    )
    payload = _alignment_payload(
        sequences={"P1": "A"},
        proteins=proteins,
        coordinate_index={("P1", 1): (unavailable,)},
        ranked_by_accession={"P1": [pocket]},
    )
    assert payload["records"][0]["pocket_annotations"] == []


def test_payload_loader_rejects_order_and_group_contract_changes(
    review_run: dict[str, Path],
) -> None:
    """Ranking order and Stage 09 group membership cannot drift silently."""
    inputs = resolve_review_inputs(
        run_root=review_run["run_root"],
        overrides=ReviewInputOverrides(),
    )
    original = review_run["shortlist"].read_text(encoding="utf-8")
    header, row = original.strip().split("\n")
    review_run["shortlist"].write_text(
        header + "\n" + row + "\n" + row + "\n",
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError, match="uniquely ordered"):
        load_report_payloads(inputs=inputs, settings=ReviewSettings())
    fields = header.split("\t")
    values = row.split("\t")
    values[fields.index("primary_group_id")] = "OTHER"
    review_run["shortlist"].write_text(
        header + "\n" + "\t".join(values) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError, match="no Stage 09 pockets"):
        load_report_payloads(inputs=inputs, settings=ReviewSettings())
