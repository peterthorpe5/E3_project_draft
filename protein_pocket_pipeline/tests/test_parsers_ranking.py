"""Native output parsing, confidence denominators and transparent rankings."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import emulate_command

from protein_pockets.models import Sample, Settings
from protein_pockets.parsers import (
    annotate_pockets,
    convert_native_tables,
    export_raw_pockets,
    finite_number,
    match_pockets,
    parse_fpocket,
    parse_p2rank,
    read_tool_table,
)
from protein_pockets.ranking import rank_cavities
from protein_pockets.structure import prepare_structure


def prediction_file(
    *,
    path: Path,
    name: str = "pocket1",
    rank: str = "1",
    score: str = "10",
    probability: str = "0.8",
    residues: str = "A_1 A_3",
) -> Path:
    """Write one native prediction row for parser boundary tests.

    Args:
        path: Destination.
        name: Pocket name.
        rank: Rank text.
        score: Score text.
        probability: Probability text.
        residues: Space-separated lining residue identifiers.

    Returns:
        Written path.
    """
    path.write_text(
        data="name,rank,score,probability,residue_ids,center_x\n"
        f"{name},{rank},{score},{probability},{residues},1.5\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "", "missing"])
def test_nonfinite_metrics_are_errors(*, value: str) -> None:
    """Missing/non-finite metrics cannot appear as plausible measured values."""
    with pytest.raises(expected_exception=ValueError):
        finite_number(value=value, field="score")


def test_realistic_fpocket_output(*, tmp_path: Path, model_path: Path) -> None:
    """All fpocket descriptors and lining residue identities survive parsing."""
    prepared = tmp_path / "model.pdb"
    prepare_structure(
        sample=Sample(sample_id="model", model_path=model_path),
        settings=Settings(),
        destination=prepared,
    )
    emulate_command(
        command=["fixture-fpocket"],
        cwd=tmp_path,
        log_prefix=tmp_path / "log",
        timeout=1,
    )
    rows = parse_fpocket(directory=tmp_path / "model_out", sample_id="model")
    assert len(rows) == 2
    assert rows[0]["metrics"]["total_sasa"] == 123.4
    assert rows[0]["residues"] == ["A_1", "A_2", "A_3"]
    export_raw_pockets(path=tmp_path / "descriptors.tsv", pockets=rows)
    assert "total_sasa" in (tmp_path / "descriptors.tsv").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        "Pocket 1 :\n Score : 1\n",
        "Pocket 1 :\n Score : 1\n Score : 2\n",
        "Pocket 1 :\nPocket 1 :\n",
        "Pocket 1 :\n Score : 1\n Druggability Score : 1.1\n Volume : 200\n",
        "Pocket 1 :\n Score : 1\n Druggability Score : 0.5\n Volume : -1\n",
        "Pocket 1 :\n Score : NaN\n",
    ],
)
def test_invalid_fpocket_descriptors(*, tmp_path: Path, content: str) -> None:
    """Malformed or duplicate descriptors fail visibly rather than being skipped."""
    (tmp_path / "model_info.txt").write_text(data=content, encoding="utf-8")
    with pytest.raises(expected_exception=ValueError):
        parse_fpocket(directory=tmp_path, sample_id="model")


def test_fpocket_missing_info_and_atoms(*, tmp_path: Path) -> None:
    """A successful process without required native outputs is not success."""
    with pytest.raises(expected_exception=ValueError):
        parse_fpocket(directory=tmp_path, sample_id="model")
    (tmp_path / "model_info.txt").write_text(
        data="Pocket 1 :\nScore : 1\nDruggability Score : 0.5\nVolume : 200\n",
        encoding="utf-8",
    )
    with pytest.raises(
        expected_exception=ValueError, match="Missing fpocket pocket atoms"
    ):
        parse_fpocket(directory=tmp_path, sample_id="model")
    (tmp_path / "pockets").mkdir()
    (tmp_path / "pockets/pocket1_atm.pdb").write_text(data="END\n", encoding="utf-8")
    with pytest.raises(expected_exception=ValueError, match="no protein lining"):
        parse_fpocket(directory=tmp_path, sample_id="model")
    (tmp_path / "pockets/pocket1_atm.pdb").write_text(
        data="ATOM  short\n", encoding="utf-8"
    )
    with pytest.raises(expected_exception=ValueError, match="Unexpected"):
        parse_fpocket(directory=tmp_path, sample_id="model")


@pytest.mark.parametrize(
    "options",
    [
        {"rank": "0"},
        {"rank": "1.5"},
        {"score": "NaN"},
        {"probability": "1.01"},
        {"probability": "-0.01"},
        {"residues": ""},
        {"residues": "bad-number"},
    ],
)
def test_invalid_p2rank_output(*, tmp_path: Path, options: dict) -> None:
    """Ranks, probabilities and residue IDs are validated at the tool boundary."""
    path = prediction_file(path=tmp_path / "prediction.csv", **options)
    with pytest.raises(expected_exception=ValueError):
        parse_p2rank(
            path=path, sample_id="model", method="p2rank", valid_fpocket_ids=set()
        )


def test_rescoring_preserves_original_cavity_id(*, tmp_path: Path) -> None:
    """A native pocket.4 ranked first still joins to fpocket cavity four."""
    path = prediction_file(path=tmp_path / "prediction.csv", name="pocket.4")
    rows = parse_p2rank(
        path=path, sample_id="model", method="p2rank_rescore", valid_fpocket_ids={4}
    )
    assert rows[0]["fpocket_pocket_id"] == 4
    assert rows[0]["rank"] == 1
    assert rows[0]["centre_x"] == 1.5
    assert rows[0]["centre_y"] is None
    for name, valid in (("pocket-wrong", {4}), ("pocket.4", {1})):
        prediction_file(path=path, name=name)
        with pytest.raises(expected_exception=ValueError):
            parse_p2rank(
                path=path,
                sample_id="model",
                method="p2rank_rescore",
                valid_fpocket_ids=valid,
            )


def test_duplicate_ranks_and_rescore_ids(*, tmp_path: Path) -> None:
    """Duplicate native ranks and ambiguous rescoring joins cannot duplicate rows."""
    path = prediction_file(path=tmp_path / "prediction.csv", name="pocket1")
    with path.open(mode="a", encoding="utf-8") as handle:
        handle.write("pocket2,1,5,0.5,A_2,2\n")
    with pytest.raises(expected_exception=ValueError):
        parse_p2rank(
            path=path, sample_id="model", method="p2rank", valid_fpocket_ids=set()
        )
    prediction_file(path=path, name="pocket1")
    with path.open(mode="a", encoding="utf-8") as handle:
        handle.write("pocket1,2,5,0.5,A_2,2\n")
    with pytest.raises(expected_exception=ValueError, match="Duplicate original"):
        parse_p2rank(
            path=path, sample_id="model", method="p2rank_rescore", valid_fpocket_ids={1}
        )


def test_headers_empty_results_and_native_tsv_conversion(*, tmp_path: Path) -> None:
    """Header-only predictions are legitimate; malformed tables are not."""
    path = tmp_path / "prediction.csv"
    path.write_text(data="name,rank,score,probability,residue_ids\n", encoding="utf-8")
    assert (
        parse_p2rank(
            path=path, sample_id="model", method="p2rank", valid_fpocket_ids=set()
        )
        == []
    )
    (tmp_path / "empty.csv").write_text(data="", encoding="utf-8")
    convert_native_tables(directory=tmp_path)
    assert not list(tmp_path.glob("*.csv"))
    assert (tmp_path / "empty.tsv").exists()
    assert (
        parse_p2rank(
            path=path.with_suffix(".tsv"),
            sample_id="model",
            method="p2rank",
            valid_fpocket_ids=set(),
        )
        == []
    )
    for content in ("", "name,name\n", "a,b\none\n", "a,b\none,two,three\n"):
        path.write_text(data=content, encoding="utf-8")
        with pytest.raises(expected_exception=ValueError):
            read_tool_table(path=path)
    path.write_text(data="other,columns\n", encoding="utf-8")
    with pytest.raises(expected_exception=ValueError, match="required columns"):
        parse_p2rank(
            path=path, sample_id="model", method="p2rank", valid_fpocket_ids=set()
        )
    with pytest.raises(expected_exception=ValueError, match="Unknown"):
        parse_p2rank(
            path=path, sample_id="model", method="unknown", valid_fpocket_ids=set()
        )


def test_unmapped_residues_reduce_confidence_denominator(*, tmp_path: Path) -> None:
    """A missing low-confidence mapping cannot silently inflate confidence."""
    path = prediction_file(path=tmp_path / "prediction.csv", residues="A_1 A_2 A_99")
    pockets = parse_p2rank(
        path=path, sample_id="model", method="p2rank", valid_fpocket_ids=set()
    )
    residues = [
        {"residue_key": "A_1", "plddt": 90},
        {"residue_key": "A_2", "plddt": 90},
    ]
    annotated, membership = annotate_pockets(
        pockets=pockets, residues=residues, settings=Settings()
    )
    pocket = annotated[0]
    assert pocket["fraction_ge_threshold"] == pytest.approx(expected=2 / 3)
    assert pocket["mean_plddt"] == 90
    assert pocket["unmapped_residue_count"] == 1
    assert pocket["confidence_status"] == "unmapped_residues"
    assert sum(row["mapped"] for row in membership) == 2
    assert membership[-1]["author_chain"] is None


@pytest.mark.parametrize(
    "confidence,values,status",
    [
        ("plddt", (90, 90), "meets_local_confidence_rule"),
        ("plddt", (90, 50), "low_local_confidence"),
        ("none", (None, None), "not_assessed"),
    ],
)
def test_confidence_states(
    *, tmp_path: Path, confidence: str, values: tuple, status: str
) -> None:
    """Missing confidence remains NULL and an explicit unassessed state."""
    path = prediction_file(path=tmp_path / "prediction.csv", residues="A_1 A_2")
    pockets = parse_p2rank(
        path=path, sample_id="model", method="p2rank", valid_fpocket_ids=set()
    )
    residues = [
        {"residue_key": f"A_{index}", "plddt": value}
        for index, value in enumerate(values, start=1)
    ]
    rows, _ = annotate_pockets(
        pockets=pockets, residues=residues, settings=Settings(confidence=confidence)
    )
    assert rows[0]["confidence_status"] == status
    if confidence == "none":
        assert rows[0]["mean_plddt"] is None
        assert rows[0]["fraction_ge_threshold"] is None


def test_overlap_and_ranking_without_blended_scores() -> None:
    """Rescoring reorders cavities, whereas disabled rescoring has a clear fallback."""
    first = {
        "sample_id": "model",
        "method": "fpocket",
        "pocket_id": 1,
        "residues": ["A_1", "A_2"],
        "druggability_score": 0.8,
    }
    second = {
        "sample_id": "model",
        "method": "fpocket",
        "pocket_id": 2,
        "residues": ["A_2", "A_3"],
        "druggability_score": 0.2,
    }
    prediction = {
        "sample_id": "model",
        "method": "p2rank",
        "pocket_id": 1,
        "residues": ["A_2", "A_3"],
    }
    pockets = [first, second, prediction]
    matches = match_pockets(pockets=pockets, threshold=0.25)
    assert len(matches) == 2
    assert matches[0]["fpocket_pocket_id"] == 2
    assert matches[0]["jaccard"] == 1
    ranked = rank_cavities(pockets=pockets, matches=matches)
    assert ranked[0]["pocket_id"] == 1
    assert ranked[0]["ranking_basis"] == "fpocket_druggability"
    pockets += [
        {
            "method": "p2rank_rescore",
            "fpocket_pocket_id": 2,
            "rank": 1,
            "score": 20,
            "probability": 0.8,
        },
        {
            "method": "p2rank_rescore",
            "fpocket_pocket_id": 1,
            "rank": 2,
            "score": 10,
            "probability": 0.4,
        },
    ]
    ranked = rank_cavities(pockets=pockets, matches=matches)
    assert [row["pocket_id"] for row in ranked] == [2, 1]
    assert ranked[0]["ranking_basis"] == "p2rank_rescore"
    assert ranked[0]["review_rank"] == 1
    assert ranked[0]["match_jaccard"] == 1
    assert (
        match_pockets(pockets=[first, {**prediction, "residues": []}], threshold=0.25)
        == []
    )


def test_raw_descriptor_union_and_empty_export(*, tmp_path: Path) -> None:
    """Variable descriptor sets remain available in an explicit wide TSV."""
    path = tmp_path / "raw.tsv"
    export_raw_pockets(
        path=path,
        pockets=[
            {"pocket_id": 1, "metrics": {"a": 1}},
            {"pocket_id": 2, "metrics": {"b": 2}},
        ],
    )
    with path.open(mode="r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(f=handle, delimiter="\t"))
    assert rows[0]["a"] == "1"
    assert rows[0]["b"] == ""
    export_raw_pockets(path=path, pockets=[])
    assert path.read_text(encoding="utf-8").strip() == "pocket_id"


def test_native_conversion_survives_directory_mutation(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Converting one native table cannot hide the next from a live file listing."""
    first = tmp_path / "predictions.csv"
    second = tmp_path / "residues.csv"
    for path in (first, second):
        path.write_text(data="key,value\nA_1,0.8\n", encoding="utf-8")

    def directory_listing():
        """Model a listing invalidated by deletion while it is being consumed."""
        yield first
        if first.exists():
            yield second

    monkeypatch.setattr(Path, "rglob", Mock(return_value=directory_listing()))
    convert_native_tables(directory=tmp_path)
    assert first.with_suffix(".tsv").exists()
    assert second.with_suffix(".tsv").exists()
    assert not first.exists()
    assert not second.exists()
