"""Tests for cluster statistics and explicit distance semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from orthofinder_results.distances import (
    calculate_alignment_distances,
    calculate_patristic_distances,
    deterministic_member_sample,
    pairwise_p_distance,
    read_fasta,
    summarise_distances,
)
from orthofinder_results.errors import DistanceCalculationError, InputValidationError
from orthofinder_results.statistics import (
    GroupAccumulator,
    finalise_accumulators,
    update_accumulators,
)


def test_group_statistics_capture_size_copy_number_and_species() -> None:
    """A group summary records the future-facing copy-number dimensions."""

    accumulator = GroupAccumulator("r", "HOG", "N0", "H1", "OG1", "N0", "source")
    accumulator.add_member(species_label="A")
    accumulator.add_member(species_label="A")
    accumulator.add_member(species_label="B")
    record = accumulator.to_record()
    assert record["member_count"] == 3
    assert record["species_count"] == 2
    assert record["single_copy_species_count"] == 1
    assert record["max_copies_per_species"] == 2
    assert record["mean_copies_per_species"] == 1.5
    assert record["species_labels"] == "A;B"
    with pytest.raises(ValueError, match="empty"):
        accumulator.add_member(species_label="")


def test_accumulator_helpers_detect_inconsistent_metadata() -> None:
    """Repeated group labels cannot merge records from inconsistent sources."""

    row = {
        "run_id": "r",
        "group_type": "HOG",
        "hierarchy_node": "N0",
        "group_id": "H1",
        "legacy_orthogroup_id": "OG1",
        "gene_tree_parent_clade": "N0",
        "source_file": "one",
        "species_label": "A",
    }
    accumulators = {}
    update_accumulators(accumulators=accumulators, membership=row)
    assert finalise_accumulators(accumulators=accumulators)[0]["member_count"] == 1
    with pytest.raises(ValueError, match="Inconsistent metadata"):
        update_accumulators(
            accumulators=accumulators,
            membership={**row, "source_file": "two"},
        )


def test_fasta_and_alignment_distance_exact_and_sampled(tmp_path: Path) -> None:
    """Alignment distances are exact below, and explicit samples above, the limit."""

    fasta = tmp_path / "H1.fa"
    fasta.write_text(">a note\nAAAA\n>b\nAATA\n>c\nTTTT\n", encoding="utf-8")
    sequences = read_fasta(path=fasta)
    rows, summary = calculate_alignment_distances(
        sequences=sequences,
        run_id="r",
        group_type="HOG",
        hierarchy_node="N0",
        group_id="H1",
        max_members=3,
    )
    assert len(rows) == 3
    assert summary["computation_status"] == "EXACT"
    assert summary["distance_pair_count"] == 3
    sampled_rows, sampled_summary = calculate_alignment_distances(
        sequences=sequences,
        run_id="r",
        group_type="HOG",
        hierarchy_node="N0",
        group_id="H1",
        max_members=2,
    )
    assert len(sampled_rows) == 1
    assert sampled_summary["computation_status"] == "DETERMINISTIC_MEMBER_SAMPLE"


def test_p_distance_pairwise_deletes_ambiguous_sites() -> None:
    """Gaps and ambiguous residues are excluded from the denominator."""

    distance, comparable, mismatches = pairwise_p_distance(sequence_a="AA-X", sequence_b="ATGX")
    assert distance == 0.5
    assert comparable == 2
    assert mismatches == 1
    assert pairwise_p_distance(sequence_a="--", sequence_b="XX") == (None, 0, 0)
    with pytest.raises(DistanceCalculationError, match="equal alignment lengths"):
        pairwise_p_distance(sequence_a="A", sequence_b="AA")


def test_sampling_is_deterministic_and_validated() -> None:
    """Sampling does not depend on input order and rejects ambiguous IDs."""

    first = deterministic_member_sample(
        member_ids=("c", "a", "b"), run_id="r", group_id="g", max_members=2
    )
    second = deterministic_member_sample(
        member_ids=("a", "b", "c"), run_id="r", group_id="g", max_members=2
    )
    assert first == second
    with pytest.raises(ValueError, match="unique"):
        deterministic_member_sample(member_ids=("a", "a"), run_id="r", group_id="g", max_members=2)
    with pytest.raises(ValueError, match="at least two"):
        deterministic_member_sample(member_ids=("a",), run_id="r", group_id="g", max_members=1)


def test_patristic_distances_and_failure_modes(tmp_path: Path) -> None:
    """Tree distances retain branch-length semantics and validate leaf subsets."""

    tree = tmp_path / "tree.txt"
    tree.write_text("((a:0.1,b:0.2):0.3,c:0.4);\n", encoding="utf-8")
    rows, summary = calculate_patristic_distances(
        tree_path=tree,
        run_id="r",
        group_type="HOG",
        hierarchy_node="N0",
        group_id="H1",
        max_members=3,
    )
    assert len(rows) == 3
    assert rows[0]["distance_method"] == "patristic_branch_length"
    assert summary["maximum_distance"] == pytest.approx(0.9)
    with pytest.raises(DistanceCalculationError, match="lacks 1 requested"):
        calculate_patristic_distances(
            tree_path=tree,
            run_id="r",
            group_type="HOG",
            hierarchy_node="N0",
            group_id="H1",
            max_members=3,
            member_ids=("a", "missing"),
        )


def test_distance_summary_counts_unresolved_pairs() -> None:
    """Missing comparable sites remain visible in summary coverage."""

    summary = summarise_distances(
        rows=[
            {"distance": 0.1, "comparable_sites": 10},
            {"distance": "", "comparable_sites": 0},
        ],
        run_id="r",
        group_type="HOG",
        hierarchy_node="N0",
        group_id="H1",
        method="test",
        status="EXACT",
        total_member_count=2,
        sampled_member_count=2,
    )
    assert summary["distance_pair_count"] == 1
    assert summary["unresolved_pair_count"] == 1
    assert summary["median_distance"] == 0.1


def test_fasta_validation_rejects_malformed_records(tmp_path: Path) -> None:
    """FASTA records cannot be empty, duplicated or unheaded."""

    bad = tmp_path / "bad.fa"
    bad.write_text("AAAA\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="precedes"):
        read_fasta(path=bad)
    bad.write_text(">a\nAA\n>a\nAA\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Duplicate"):
        read_fasta(path=bad)
    with pytest.raises(DistanceCalculationError, match="unequal"):
        calculate_alignment_distances(
            sequences={"a": "AA", "b": "A"},
            run_id="r",
            group_type="HOG",
            hierarchy_node="N0",
            group_id="H1",
            max_members=2,
        )
