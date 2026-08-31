"""Tests for version adapters and loss-aware source parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from orthofinder_results.errors import InputValidationError
from orthofinder_results.layout import detect_version, discover_layout
from orthofinder_results.parsers import (
    iter_memberships,
    iter_sequence_ids,
    read_species_ids,
    species_label_from_fasta,
)


def test_discovers_orthofinder_2_and_all_hog_levels(orthofinder2_results: Path) -> None:
    """OrthoFinder 2 retains both legacy and all HOG authorities."""

    layout = discover_layout(results_dir=orthofinder2_results)
    assert layout.adapter_name == "orthofinder_2"
    assert layout.primary_group_authority == "HOG"
    assert [path.name for path in layout.hog_paths] == ["N0.tsv", "N1.tsv"]
    assert layout.capabilities.has_legacy_orthogroups
    assert layout.to_record()["orthofinder_version"] == "2.5.5"


def test_discovers_hog_primary_orthofinder_3_without_legacy_table(
    orthofinder3_results: Path,
) -> None:
    """The OrthoFinder 3 adapter does not require deprecated OG output."""

    layout = discover_layout(results_dir=orthofinder3_results)
    assert layout.adapter_name == "orthofinder_3"
    assert layout.primary_group_authority == "HOG"
    assert layout.orthogroups_path is None
    assert not layout.capabilities.has_legacy_orthogroups


def test_layout_and_version_failures_are_explicit(tmp_path: Path) -> None:
    """Missing, unversioned and unsupported results fail with context."""

    with pytest.raises(InputValidationError, match="does not exist"):
        discover_layout(results_dir=tmp_path / "absent")
    (tmp_path / "Log.txt").write_text("no version\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Could not detect"):
        detect_version(log_path=tmp_path / "Log.txt")
    (tmp_path / "Log.txt").write_text("Version: 4.0.0\n", encoding="utf-8")
    hogs = tmp_path / "Phylogenetic_Hierarchical_Orthogroups"
    hogs.mkdir()
    (hogs / "N0.tsv").write_text("HOG\tSpecies\nH1\tp1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Unsupported OrthoFinder major"):
        discover_layout(results_dir=tmp_path)


def test_species_and_sequence_parsers_preserve_source_values(
    orthofinder2_results: Path,
) -> None:
    """Identifier parsers retain raw headers and source species labels."""

    working = orthofinder2_results / "WorkingDirectory"
    lookup, species = read_species_ids(path=working / "SpeciesIDs.txt", run_id="run-a")
    sequences = list(
        iter_sequence_ids(
            path=working / "SequenceIDs.txt",
            run_id="run-a",
            species_by_index=lookup,
        )
    )
    assert [row["species_label"] for row in species] == ["Species_A", "Species_B"]
    assert sequences[0]["raw_header"] == "protA first protein"
    assert sequences[0]["member_id"] == "protA"
    assert species_label_from_fasta(fasta_name="path/Plant.pep.gz") == "Plant"


def test_membership_parser_supports_v2_and_v3_headers(
    orthofinder2_results: Path,
    orthofinder3_results: Path,
) -> None:
    """HOG parsing accepts optional legacy OG metadata across versions."""

    v2_rows = list(
        iter_memberships(
            path=orthofinder2_results / "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
            run_id="v2",
            group_type="HOG",
            hierarchy_node="N0",
        )
    )
    v3_rows = list(
        iter_memberships(
            path=orthofinder3_results / "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
            run_id="v3",
            group_type="HOG",
            hierarchy_node="N0",
        )
    )
    assert len(v2_rows) == len(v3_rows) == 3
    assert v2_rows[0]["legacy_orthogroup_id"] == "OG0000001"
    assert v3_rows[0]["legacy_orthogroup_id"] == ""
    assert {row["species_label"] for row in v3_rows} == {"Species_A", "Species_B"}


def test_parser_rejects_malformed_and_ambiguous_inputs(tmp_path: Path) -> None:
    """Malformed identifiers, tables and unsupported group types are rejected."""

    species = tmp_path / "SpeciesIDs.txt"
    species.write_text("broken\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Malformed"):
        read_species_ids(path=species, run_id="x")
    sequences = tmp_path / "SequenceIDs.txt"
    sequences.write_text("9_0: protein\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="unknown species"):
        list(iter_sequence_ids(path=sequences, run_id="x", species_by_index={"0": "a.fa"}))
    group = tmp_path / "groups.tsv"
    group.write_text("Wrong\tSpecies\nG1\tp1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="identifier column"):
        list(iter_memberships(path=group, run_id="x", group_type="HOG"))
    with pytest.raises(ValueError, match="Unsupported"):
        list(iter_memberships(path=group, run_id="x", group_type="BAD"))
    with pytest.raises(InputValidationError, match="empty species FASTA"):
        species_label_from_fasta(fasta_name="")
