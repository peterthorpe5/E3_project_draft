"""Integration tests for atomic ranked pocket-review publication."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from e3structalign.errors import StructuralAlignmentError
from e3structalign.io_utils import sha256_file, write_tsv
from e3structalign.review_models import ReviewInputOverrides, ReviewSettings
from e3structalign.review_pipeline import (
    _sequence_rows,
    _validate_existing_output,
    _write_sequence_fasta,
    build_review_report,
)


def _build(review_run: dict[str, Path], **kwargs: bool) -> Path:
    """Build the shared report with controlled output-mode overrides."""
    return build_review_report(
        run_root=review_run["run_root"],
        output_dir=review_run["output"],
        settings=ReviewSettings(),
        overrides=ReviewInputOverrides(),
        resume=kwargs.get("resume", False),
        force=kwargs.get("force", False),
        verbose=False,
    )


def test_complete_report_build_and_checksum_resume(
    review_run: dict[str, Path],
) -> None:
    """A complete report publishes every page, table, log, QC and manifest."""
    manifest_path = _build(review_run)
    output = review_run["output"]
    assert manifest_path == output / "provenance" / "run_manifest.json"
    assert (output / "index.html").is_file()
    assert (output / "evidence_matrix.html").is_file()
    pages = list((output / "groups").glob("*.html"))
    assert len(pages) == 1
    assert (output / "review_decisions_template.tsv").is_file()
    assert (output / "tables" / "review_report_index.tsv").is_file()
    assert (output / "tables" / "top_group_evidence_matrix.tsv").is_file()
    assert (output / "tables" / "pocket_residue_annotations.tsv").is_file()
    assert (output / "tables" / "protein_model_inventory.tsv").is_file()
    viewer_table = output / "tables" / "structural_alignment_viewers.tsv"
    assert viewer_table.is_file()
    with viewer_table.open("r", encoding="utf-8", newline="") as handle:
        viewer_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(viewer_rows) == 1
    viewer_page = output / viewer_rows[0]["interactive_view_html"]
    assert viewer_page.is_file()
    assert sha256_file(viewer_page) == viewer_rows[0]["viewer_source_sha256"]
    sequence_table = output / "tables" / "prioritised_group_sequences.tsv"
    sequence_fasta = output / "sequences" / "prioritised_group_sequences.fasta"
    assert sequence_table.is_file()
    assert sequence_fasta.is_file()
    with sequence_table.open("r", encoding="utf-8", newline="") as handle:
        sequence_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["candidate_accession"] for row in sequence_rows] == ["P1", "P2"]
    assert {row["amino_acid_sequence"] for row in sequence_rows} == {"AA"}
    assert {row["sequence_length"] for row in sequence_rows} == {"2"}
    assert sequence_fasta.read_text(encoding="utf-8") == (
        ">rank_001__orthogroup__OG0001__cluster_1__P1\n"
        "AA\n"
        ">rank_001__orthogroup__OG0001__cluster_1__P2\n"
        "AA\n"
    )
    assert (output / "qc" / "pocket_review_validation.tsv").is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["package_version"] == "0.5.0"
    assert payload["validation"]["reported_group_count"] == 1
    assert payload["validation"]["exact_pocket_residue_annotation_count"] == 4
    assert payload["validation"]["sequence_export_group_count"] == 1
    assert payload["validation"]["sequence_export_record_count"] == 2
    assert payload["validation"]["structural_superposition_viewer_count"] == 1
    assert payload["embedded_sources"][0]["models"][0]["sha256"]
    assert _build(review_run, resume=True) == manifest_path


def test_sequence_export_retains_alignment_members_without_pockets(
    review_run: dict[str, Path],
) -> None:
    """The sequence files retain group members lacking ranked-pocket evidence."""
    alignment = review_run["alignment"]
    alignment.write_text(">P1\nAA\n>P2\nAA\n>P3\nA-\n", encoding="utf-8")
    _build(review_run)
    table = (
        review_run["output"]
        / "tables"
        / "prioritised_group_sequences.tsv"
    )
    with table.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["candidate_accession"] for row in rows] == ["P1", "P2", "P3"]
    third = rows[2]
    assert third["species_column"] == ""
    assert third["has_ranked_pocket_evidence"] == "False"
    assert third["sequence_length"] == "1"
    assert third["amino_acid_sequence"] == "A"
    assert third["aligned_sequence"] == "A-"


def test_supplementary_exact_sequences_are_checksum_bound_and_published(
    review_run: dict[str, Path],
) -> None:
    """Members without structures remain explicit in a separate FASTA/table."""
    sequence = "ACDE"
    supplementary = review_run["run_root"] / "human_group_members.tsv"
    rows = [
        {
            "review_rank": 1,
            "cluster_id": "cluster_1",
            "primary_group_type": "orthogroup",
            "primary_group_id": "OG0001",
            "species_column": "Homo_sapiens",
            "accession": "H1",
            "sequence_length": len(sequence),
            "sequence_sha256": hashlib.sha256(
                sequence.encode("ascii")
            ).hexdigest(),
            "protein_sequence": sequence,
        }
    ]
    write_tsv(supplementary, rows, tuple(rows[0]))
    manifest = build_review_report(
        run_root=review_run["run_root"],
        output_dir=review_run["output"],
        settings=ReviewSettings(),
        overrides=ReviewInputOverrides(
            supplementary_group_sequences=supplementary
        ),
        resume=False,
        force=False,
        verbose=False,
    )
    output = review_run["output"]
    table = output / "tables" / "supplementary_group_sequences.tsv"
    fasta = output / "sequences" / "supplementary_group_sequences.fasta"
    assert table.is_file()
    assert fasta.read_text(encoding="utf-8").endswith("\nACDE\n")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["validation"]["supplementary_sequence_record_count"] == 1
    assert "supplementary_group_sequences" in payload["inputs"]


def test_report_resolves_group_nested_extension_viewer_layout(
    review_run: dict[str, Path],
) -> None:
    """Combined extension viewers may be nested beneath their group slug."""
    interactive = (
        review_run["run_root"]
        / "09b_structural_alignment"
        / "structural_alignment"
        / "interactive"
    )
    source = (
        interactive
        / "pairs"
        / "us-align"
        / "cluster_1__OG0001"
        / "P1__P2.html"
    )
    destination = (
        interactive
        / "groups"
        / "orthogroup__OG0001"
        / "pairs"
        / "us-align"
        / "cluster_1__OG0001"
        / "P1__P2.html"
    )
    destination.parent.mkdir(parents=True)
    source.replace(destination)
    manifest = _build(review_run)
    assert manifest.is_file()
    published = (
        review_run["output"]
        / "structural_alignment"
        / "groups"
        / "orthogroup__OG0001"
        / "pairs"
        / "us-align"
        / "cluster_1__OG0001"
        / "P1__P2.html"
    )
    assert published.is_file()


def test_sequence_export_rejects_all_gap_and_empty_outputs(
    tmp_path: Path,
) -> None:
    """FASTA publication fails closed for invalid sequence exports."""
    with pytest.raises(StructuralAlignmentError, match="all-gap"):
        _sequence_rows(
            [
                {
                    "review_rank": 1,
                    "group_key": {
                        "primary_group_type": "orthogroup",
                        "primary_group_id": "OG0001",
                        "cluster_id": "cluster_1",
                    },
                    "alignment": {
                        "source_sha256": "abc",
                        "all_records": [
                            {
                                "accession": "P1",
                                "species": "species_1",
                                "is_reference": True,
                                "has_ranked_pocket_evidence": True,
                                "sequence": "--",
                            }
                        ],
                    },
                }
            ]
        )
    with pytest.raises(StructuralAlignmentError, match="No prioritised"):
        _write_sequence_fasta(path=tmp_path / "empty.fasta", records=[])
    with pytest.raises(StructuralAlignmentError, match="line width"):
        _write_sequence_fasta(
            path=tmp_path / "bad_width.fasta",
            records=[
                {
                    "fasta_identifier": "P1",
                    "amino_acid_sequence": "AA",
                }
            ],
            line_width=0,
        )


def test_existing_mismatch_requires_force_and_preserves_old_report(
    review_run: dict[str, Path],
) -> None:
    """Tampered or unrelated outputs fail closed unless explicitly superseded."""
    _build(review_run)
    index = review_run["output"] / "index.html"
    index.write_text("tampered", encoding="utf-8")
    with pytest.raises(StructuralAlignmentError):
        _build(review_run, resume=True)
    rebuilt = _build(review_run, force=True)
    assert rebuilt.is_file()
    superseded = list(
        review_run["output"].parent.glob(
            f"{review_run['output'].name}.superseded.*"
        )
    )
    assert len(superseded) == 1
    assert (superseded[0] / "index.html").read_text(encoding="utf-8") == "tampered"


def test_output_modes_are_mutually_exclusive(
    review_run: dict[str, Path],
) -> None:
    """Programmatic callers cannot request resume and force together."""
    with pytest.raises(StructuralAlignmentError):
        _build(review_run, resume=True, force=True)


def test_resume_validator_rejects_malformed_manifests(tmp_path: Path) -> None:
    """Resume requires a complete manifest and safe checksum-bound outputs."""
    output = tmp_path / "output"
    provenance = output / "provenance"
    provenance.mkdir(parents=True)
    assert not _validate_existing_output(tmp_path / "missing", "digest")
    manifest = provenance / "run_manifest.json"
    manifest.write_text("{", encoding="utf-8")
    assert not _validate_existing_output(output, "digest")
    cases = (
        {"status": "failed", "run_digest": "digest", "outputs": []},
        {"status": "complete", "run_digest": "other", "outputs": []},
        {"status": "complete", "run_digest": "digest", "outputs": []},
        {"status": "complete", "run_digest": "digest", "outputs": ["bad"]},
        {
            "status": "complete",
            "run_digest": "digest",
            "outputs": [{"path": "../escape", "size_bytes": 1, "sha256": "x"}],
        },
        {
            "status": "complete",
            "run_digest": "digest",
            "outputs": [{"path": "missing", "size_bytes": 1, "sha256": "x"}],
        },
    )
    for payload in cases:
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        assert not _validate_existing_output(output, "digest")


def test_failed_publication_is_retained_for_diagnosis(
    review_run: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected renderer failure retains an explicit failed staging tree."""
    def fail_publish(**_: object) -> None:
        """Raise a synthetic rendering error."""
        raise RuntimeError("synthetic renderer failure")

    monkeypatch.setattr(
        "e3structalign.review_pipeline._publish_report",
        fail_publish,
    )
    with pytest.raises(RuntimeError, match="synthetic"):
        _build(review_run)
    failed = list(
        review_run["output"].parent.glob(
            f".{review_run['output'].name}.failed.*"
        )
    )
    assert len(failed) == 1
    assert (failed[0] / "logs" / "pocket_review.log").is_file()
