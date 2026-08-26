"""Tests for portable structure and pocket-alignment review bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from e3app.config import AppConfig
from e3app.errors import AppError
from e3app.pocket_review import (
    MAX_HTML_BYTES,
    PocketReviewBundle,
    _read_tsv,
    _safe_group_page,
    discover_pocket_review_dir,
    group_choice_labels,
    load_pocket_review,
    pocket_review_available,
    prepare_pocket_review,
    repair_pocket_review_viewer_controls,
    read_group_html,
    read_review_html,
    required_review_paths,
    selected_group_members,
    selected_group_alignment_fasta_bytes,
    selected_group_row,
    selected_group_supplementary_fasta_bytes,
    selected_group_supplementary_sequences,
)


def make_pocket_review(parent: Path, name: str = "pocket_review") -> Path:
    """Create a minimal valid self-contained pocket-review bundle."""
    root = parent / name
    (root / "groups").mkdir(parents=True)
    (root / "tables").mkdir()
    (root / "provenance").mkdir()
    (root / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (root / "evidence_matrix.html").write_text(
        "<html>matrix</html>", encoding="utf-8"
    )
    group_page = root / "groups" / "rank_001__hog__N0.HOG1.html"
    group_page.write_text(
        "<html><h2>Interactive 3D pocket location</h2>"
        "<h2>Pocket-annotated MAFFT sequence alignment</h2></html>",
        encoding="utf-8",
    )
    (root / "provenance" / "run_manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    pd.DataFrame(
        [
            {
                "review_rank": 1,
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "N0.HOG1",
                "lead_cluster_id": "cluster_1",
                "reference_accession": "P1",
                "protein_count": 2,
                "alignment_sequence_count": 3,
                "group_review_html": "groups/rank_001__hog__N0.HOG1.html",
            }
        ]
    ).to_csv(
        root / "tables" / "review_report_index.tsv",
        sep="\t",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "review_rank": 1,
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "N0.HOG1",
                "lead_cluster_id": "cluster_1",
                "fasta_identifier": "rank_001__P1",
                "candidate_accession": "P1",
                "species_column": "Arabidopsis_thaliana",
                "is_reference": True,
                "has_ranked_pocket_evidence": True,
                "sequence_length": 100,
                "alignment_length": 110,
                "amino_acid_sequence": "ACDE",
                "aligned_sequence": "AC-DE",
            },
            {
                "review_rank": 1,
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "N0.HOG1",
                "lead_cluster_id": "cluster_1",
                "fasta_identifier": "rank_001__P2",
                "candidate_accession": "P2",
                "species_column": "Zea_mays",
                "is_reference": False,
                "has_ranked_pocket_evidence": False,
                "sequence_length": 95,
                "alignment_length": 110,
                "amino_acid_sequence": "FGHI",
                "aligned_sequence": "FGH-I",
            },
        ]
    ).to_csv(
        root / "tables" / "prioritised_group_sequences.tsv",
        sep="\t",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "review_rank": 1,
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "N0.HOG1",
                "lead_cluster_id": "cluster_1",
                "candidate_accession": "P1",
                "species_column": "Arabidopsis_thaliana",
                "is_reference": True,
                "model_status": "MODEL_AVAILABLE",
                "ca_atom_count": 100,
                "mapped_pocket_ca_count": 10,
                "retained_pocket_count": 5,
            }
        ]
    ).to_csv(
        root / "tables" / "protein_model_inventory.tsv",
        sep="\t",
        index=False,
    )
    viewer_relative = (
        "structural_alignment/groups/HIERARCHICAL_ORTHOGROUP__N0.HOG1/"
        "pairs/us-align/cluster_1__N0.HOG1/P1__P2.html"
    )
    viewer = root / viewer_relative
    viewer.parent.mkdir(parents=True)
    viewer.write_text(
        "<!doctype html><html><body><canvas id='viewer'></canvas>"
        "<p>pairwise superposition</p></body></html>",
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "review_rank": 1,
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "N0.HOG1",
                "lead_cluster_id": "cluster_1",
                "reference_accession": "P1",
                "mobile_accession": "P2",
                "reference_species": "Arabidopsis_thaliana",
                "mobile_species": "Zea_mays",
                "alignment_tool": "US-align",
                "minimum_tm_score": 0.9,
                "interactive_view_html": viewer_relative,
                "viewer_source_sha256": hashlib.sha256(
                    viewer.read_bytes()
                ).hexdigest(),
            }
        ]
    ).to_csv(
        root / "tables" / "structural_alignment_viewers.tsv",
        sep="\t",
        index=False,
    )
    return root


def test_review_bundle_loads_and_selects_members(tmp_path: Path) -> None:
    """Valid bundles preserve group, model and OrthoFinder sequence identifiers."""
    root = make_pocket_review(tmp_path)
    assert pocket_review_available(root)
    assert required_review_paths(root)["groups"].is_dir()
    bundle = load_pocket_review(root)
    assert bundle.available
    assert len(bundle.structural_viewers) == 1
    assert bundle.index["review_rank"].tolist() == [1]
    labels = group_choice_labels(bundle)
    page = next(iter(labels))
    assert "N0.HOG1" in labels[page]
    row = selected_group_row(bundle, page)
    assert row["reference_accession"] == "P1"
    models = selected_group_members(bundle, 1, "structure")
    sequences = selected_group_members(bundle, 1, "alignment")
    assert models["model_status"].tolist() == ["MODEL_AVAILABLE"]
    assert sequences["candidate_accession"].tolist() == ["P1", "P2"]
    assert "fasta_identifier" in sequences.columns
    alignment_fasta = selected_group_alignment_fasta_bytes(
        bundle=bundle,
        review_rank=1,
    ).decode("utf-8")
    assert ">rank_001__P1" in alignment_fasta
    assert "AC-DE" in alignment_fasta
    structure_html = read_group_html(bundle, page, "structure")
    alignment_html = read_group_html(bundle, page, "alignment")
    assert "Interactive 3D pocket location" in structure_html
    assert "Pocket-annotated MAFFT sequence alignment" in alignment_html
    assert "scrollIntoView" in alignment_html
    assert read_review_html(bundle, "evidence_matrix.html") == "<html>matrix</html>"


def test_supplementary_human_sequences_are_validated_and_downloadable(
    tmp_path: Path,
) -> None:
    """Exact human sequences remain visible without implying pocket evidence."""
    root = make_pocket_review(tmp_path)
    sequence = "ACDE"
    pd.DataFrame(
        [
            {
                "review_rank": 1,
                "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
                "primary_group_id": "N0.HOG1",
                "lead_cluster_id": "cluster_1",
                "fasta_identifier": "rank_001__N0.HOG1__H1",
                "candidate_accession": "H1",
                "species_column": "Homo_sapiens",
                "sequence_length": len(sequence),
                "sequence_sha256": hashlib.sha256(
                    sequence.encode("ascii")
                ).hexdigest(),
                "amino_acid_sequence": sequence,
                "structural_assessment_note": "Exact sequence only",
            }
        ]
    ).to_csv(
        root / "tables" / "supplementary_group_sequences.tsv",
        sep="\t",
        index=False,
    )
    bundle = load_pocket_review(root)
    selected = selected_group_supplementary_sequences(
        bundle=bundle,
        review_rank=1,
    )
    assert selected["candidate_accession"].tolist() == ["H1"]
    fasta = selected_group_supplementary_fasta_bytes(
        bundle=bundle,
        review_rank=1,
    ).decode("utf-8")
    assert fasta.startswith(">rank_001__N0.HOG1__H1")
    assert fasta.endswith("ACDE\n")


def test_legacy_fit_control_is_repaired_idempotently() -> None:
    """Already-generated report pages gain a meaningful fit-and-centre action."""
    legacy = (
        '<button id="fit" type="button">Fit structure</button>'
        '<p id="proteinMeta"></p><script>'
        'document.getElementById("fit").onclick=()=>{zoom=1;draw();};'
        '</script>'
    )
    upgraded = repair_pocket_review_viewer_controls(legacy)
    assert "Fit structure" not in upgraded
    assert "Fit and centre" in upgraded
    assert "rx=-.28;ry=.45;zoom=1;draw();" in upgraded
    assert 'id="viewerStatus" class="note" aria-live="polite"' in upgraded
    assert "View fitted and centred." in upgraded
    assert repair_pocket_review_viewer_controls(upgraded) == upgraded


def test_legacy_group_page_gains_offline_pdf_controls() -> None:
    """Legacy self-contained pages gain both real browser PDF exporters."""
    legacy = (
        '<html><body><canvas id="viewer"></canvas>'
        '<h2>Pocket-annotated MAFFT sequence alignment</h2>'
        '<button id="fit" type="button">Fit structure</button>'
        '<p id="proteinMeta"></p><script>'
        'document.getElementById("fit").onclick=()=>{zoom=1;draw();};'
        '</script></body></html>'
    )
    upgraded = repair_pocket_review_viewer_controls(legacy)
    assert 'id="downloadViewPdf"' in upgraded
    assert 'id="downloadAlignmentPdf"' in upgraded
    assert "downloadCurrentViewPdf" in upgraded
    assert "downloadAlignmentPdf" in upgraded
    assert "application/pdf" in upgraded
    assert repair_pocket_review_viewer_controls(upgraded) == upgraded


def test_review_discovery_requires_one_unambiguous_bundle(tmp_path: Path) -> None:
    """Automatic discovery accepts one sibling but never guesses between two."""
    resource = tmp_path / "e3_integrated_resource.duckdb"
    resource.write_text("placeholder", encoding="utf-8")
    config = AppConfig(resource_duckdb=resource)
    assert discover_pocket_review_dir(config) is None
    first = make_pocket_review(tmp_path, "pocket_review_top200")
    assert discover_pocket_review_dir(config) == first.resolve()
    second = make_pocket_review(tmp_path, "pocket_review_alternative")
    assert second.is_dir()
    assert discover_pocket_review_dir(config) is None
    explicit = AppConfig(resource_duckdb=resource, pocket_review_dir=first)
    assert discover_pocket_review_dir(explicit) == first.resolve()

    run = tmp_path / "run"
    run.mkdir()
    run_review = make_pocket_review(run, "pocket_review")
    run_config = AppConfig(resource_run_dir=run)
    assert discover_pocket_review_dir(run_config) == run_review.resolve()
    assert discover_pocket_review_dir(AppConfig()) is None
    missing_source = AppConfig(resource_duckdb=tmp_path / "missing.duckdb")
    assert discover_pocket_review_dir(missing_source) is None


def test_prepare_review_is_optional_and_reports_invalid_bundle(tmp_path: Path) -> None:
    """Missing visual assets do not block the relational application."""
    resource = tmp_path / "resource.duckdb"
    resource.write_text("placeholder", encoding="utf-8")
    unavailable = prepare_pocket_review(AppConfig(resource_duckdb=resource))
    assert not unavailable.available
    assert "--pocket-review-dir" in unavailable.reason
    assert group_choice_labels(unavailable) == {}
    with pytest.raises(AppError, match="unavailable"):
        selected_group_row(unavailable, "missing")

    incomplete = tmp_path / "pocket_review_incomplete"
    incomplete.mkdir()
    invalid = prepare_pocket_review(
        AppConfig(resource_duckdb=resource, pocket_review_dir=incomplete)
    )
    assert not invalid.available
    assert "incomplete" in invalid.reason


def test_review_validation_fails_closed(tmp_path: Path) -> None:
    """Traversal, duplicate ranks, bad selections and bad focus are rejected."""
    root = make_pocket_review(tmp_path)
    index_path = root / "tables" / "review_report_index.tsv"
    index = pd.read_csv(index_path, sep="\t")
    index.loc[0, "group_review_html"] = "../outside.html"
    index.to_csv(index_path, sep="\t", index=False)
    with pytest.raises(AppError, match="Unsafe"):
        load_pocket_review(root)

    root = make_pocket_review(tmp_path, "pocket_review_second")
    bundle = load_pocket_review(root)
    page = bundle.index.loc[0, "group_review_html"]
    with pytest.raises(AppError, match="Unknown"):
        selected_group_row(bundle, "missing.html")
    with pytest.raises(AppError, match="focus"):
        selected_group_members(bundle, 1, "bad")  # type: ignore[arg-type]
    with pytest.raises(AppError, match="focus"):
        read_group_html(bundle, page, "bad")  # type: ignore[arg-type]
    unavailable = PocketReviewBundle(
        available=False,
        path=None,
        reason="missing",
        index=pd.DataFrame(),
        sequences=pd.DataFrame(),
        models=pd.DataFrame(),
        structural_viewers=pd.DataFrame(),
    )
    with pytest.raises(AppError, match="unavailable"):
        read_group_html(unavailable, page, "structure")

    index = pd.read_csv(root / "tables" / "review_report_index.tsv", sep="\t")
    index = pd.concat([index, index], ignore_index=True)
    index.to_csv(root / "tables" / "review_report_index.tsv", sep="\t", index=False)
    with pytest.raises(AppError, match="unique integers"):
        load_pocket_review(root)


def test_review_rejects_missing_columns_and_oversized_html(tmp_path: Path) -> None:
    """Incomplete tables and unexpectedly huge pages have controlled failures."""
    missing_root = make_pocket_review(tmp_path, "pocket_review_missing_column")
    sequences_path = missing_root / "tables" / "prioritised_group_sequences.tsv"
    sequences = pd.read_csv(sequences_path, sep="\t").drop(
        columns=["fasta_identifier"]
    )
    sequences.to_csv(sequences_path, sep="\t", index=False)
    with pytest.raises(AppError, match="missing columns"):
        load_pocket_review(missing_root)

    large_root = make_pocket_review(tmp_path, "pocket_review_large")
    bundle = load_pocket_review(large_root)
    page = str(bundle.index.loc[0, "group_review_html"])
    html_path = large_root / page
    with html_path.open("r+b") as handle:
        handle.seek(MAX_HTML_BYTES)
        handle.write(b"x")
    with pytest.raises(AppError, match="100 MiB"):
        read_group_html(bundle, page, "structure")


def test_incomplete_review_path_is_unavailable(tmp_path: Path) -> None:
    """A missing manifest or missing directory prevents availability."""
    root = make_pocket_review(tmp_path)
    (root / "provenance" / "run_manifest.json").unlink()
    assert not pocket_review_available(root)
    assert not pocket_review_available(None)
    with pytest.raises(AppError, match="incomplete"):
        load_pocket_review(root)


def test_review_tables_and_paths_cover_defensive_failures(tmp_path: Path) -> None:
    """Unreadable tables, unsafe links and malformed ranks fail closed."""
    with pytest.raises(AppError, match="not found"):
        _read_tsv(tmp_path / "missing.tsv", ("value",))

    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    root = tmp_path / "safe_root"
    root.mkdir()
    (root / "linked.html").symlink_to(outside)
    with pytest.raises(AppError, match="Unsafe"):
        _safe_group_page(root, "linked.html")
    with pytest.raises(AppError, match="not found"):
        _safe_group_page(root, "missing.html")

    empty = make_pocket_review(tmp_path, "pocket_review_empty")
    pd.read_csv(
        empty / "tables" / "review_report_index.tsv", sep="\t"
    ).iloc[0:0].to_csv(
        empty / "tables" / "review_report_index.tsv", sep="\t", index=False
    )
    with pytest.raises(AppError, match="no group pages"):
        load_pocket_review(empty)

    fractional = make_pocket_review(tmp_path, "pocket_review_fractional")
    index_path = fractional / "tables" / "review_report_index.tsv"
    index = pd.read_csv(index_path, sep="\t")
    index["review_rank"] = index["review_rank"].astype(float)
    index.loc[0, "review_rank"] = 1.5
    index.to_csv(index_path, sep="\t", index=False)
    with pytest.raises(AppError, match="unique integers"):
        load_pocket_review(fractional)

    invalid_member = make_pocket_review(tmp_path, "pocket_review_invalid_member")
    sequence_path = invalid_member / "tables" / "prioritised_group_sequences.tsv"
    sequences = pd.read_csv(sequence_path, sep="\t")
    sequences["review_rank"] = sequences["review_rank"].astype("object")
    sequences.loc[0, "review_rank"] = "not_an_integer"
    sequences.to_csv(sequence_path, sep="\t", index=False)
    with pytest.raises(AppError, match="member ranks"):
        load_pocket_review(invalid_member)

    bad_encoding = make_pocket_review(tmp_path, "pocket_review_bad_encoding")
    bundle = load_pocket_review(bad_encoding)
    page = str(bundle.index.loc[0, "group_review_html"])
    (bad_encoding / page).write_bytes(b"\xff\xfe")
    with pytest.raises(AppError, match="Could not read"):
        read_group_html(bundle, page, "alignment")
