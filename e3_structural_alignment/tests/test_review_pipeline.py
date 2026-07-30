"""Integration tests for atomic ranked pocket-review publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e3structalign.errors import StructuralAlignmentError
from e3structalign.review_models import ReviewInputOverrides, ReviewSettings
from e3structalign.review_pipeline import (
    _validate_existing_output,
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
    assert (output / "qc" / "pocket_review_validation.tsv").is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["package_version"] == "0.3.0"
    assert payload["validation"]["reported_group_count"] == 1
    assert payload["validation"]["exact_pocket_residue_annotation_count"] == 4
    assert payload["embedded_sources"][0]["models"][0]["sha256"]
    assert _build(review_run, resume=True) == manifest_path


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
