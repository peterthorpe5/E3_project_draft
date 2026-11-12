"""Statistics use complete audited membership and exact input lengths."""

import pandas as pd
import pytest

from e3app.research.common import ResearchError
from e3app.research.subcluster_statistics import subcluster_statistics


@pytest.fixture(params=["tsv", "parquet"])
def saved_subclusters(*, request, tmp_path):
    """Write a six-protein family with passing and failed exact assignments.

    Args:
        request: Membership artifact format.
        tmp_path: Private result directory.

    Returns:
        Complete membership, input FASTA and recorded taxonomy paths.
    """
    membership = tmp_path / f"membership.{request.param}"
    rows = pd.DataFrame({
        "sequence_id": list("abcdef"),
        "subcluster_id": ["sub_A", "sub_A", "sub_A", "sub_D", "sub_E", "sub_F"],
        "native_representative_id": ["a", "a", "a", "a", "a", "f"],
        "audited_representative_id": ["a", "a", "a", "d", "e", "f"],
        "alignment_status": [
            "CENTROID_SELF", "EXACT_THRESHOLDS_PASS", "EXACT_THRESHOLDS_PASS",
            "EXACT_THRESHOLDS_FAIL", "NO_REALIGNMENT", "CENTROID_SELF",
        ],
        "pident": [None, 95, 85, 65, None, None],
        "representative_coverage": [None, 100, 80, 70, None, None],
        "member_coverage": [None, 90, 100, 100, None, None],
        "evalue": [None, 1e-20, 1e-15, 1e-10, None, None],
        "bitscore": [None, 70, 60, 30, None, None],
    })
    if request.param == "parquet":
        rows.to_parquet(membership, index=False)
    else:
        rows.to_csv(membership, sep="\t", index=False)
    fasta = tmp_path / "sequences.fasta"
    fasta.write_text(
        ">a\nACDE\n>b\nACDEFG\n>c\nACDEFGHI\n>d\nACD\n>e\nACDEFGHIKL\n>f\nAC\n",
        encoding="utf-8",
    )
    taxonomy = tmp_path / "cluster_species.tsv"
    taxonomy.write_text(
        "cluster_id\tspecies\ttaxon_id\tmember_count\n"
        "sub_A\tSpecies_one\t123\t2\nsub_A\tUNCLASSIFIED\t\t1\n"
        "sub_D\tSpecies_two\t456\t1\nsub_E\tUNCLASSIFIED\t\t1\nsub_F\tSpecies_one\t123\t1\n",
        encoding="utf-8",
    )
    return membership, fasta, taxonomy


def test_selected_subcluster_compares_against_complete_input(*, saved_subclusters):
    """Distinguish original-family denominators, native clusters and passing alignments."""
    membership, fasta, taxonomy = saved_subclusters
    tables = subcluster_statistics(
        membership=membership, fasta=fasta, taxonomy=taxonomy, group="sub_A",
    )
    family = tables["input_family_comparison"]
    assert family["proteins"].tolist() == [6, 3]
    assert family["input_family_percent"].tolist() == [100, 50]
    assert family["median_length"].tolist() == [5, 6]
    assert family["reviewed_taxa"].tolist() == [2, 1]
    assert family["proteins_with_reviewed_taxonomy"].tolist() == [4, 2]
    partitions = tables["partition"]
    assert partitions["clusters"].tolist() == [2, 4]
    assert partitions["singletons"].tolist() == [1, 3]
    assert partitions["largest_cluster"].tolist() == [5, 3]
    audit = tables["audit_outcomes"].set_index("audit_outcome")
    assert audit.loc["Singleton after threshold failure", "input_family"] == 1
    assert audit.loc["Singleton after missing realignment", "selected_subcluster"] == 0
    metrics = tables["centroid_metrics"].set_index("metric")
    assert metrics.loc["Exact identity (%)"].to_dict() == {
        "passing_alignments": 2, "minimum": 85, "median": 90, "maximum": 95,
    }
    assert metrics.loc["E-value", "maximum"] == 1e-15
    species = tables["species_counts"].set_index("species")
    assert species.loc["Unclassified", "input_family"] == 2
    assert species.loc["Unclassified", "selected_subcluster"] == 1


def test_overview_singleton_and_missing_source_are_explicit(*, saved_subclusters):
    """Unavailable inputs leave their statistics absent and singletons have no passing links."""
    membership, _fasta, _taxonomy = saved_subclusters
    overview = subcluster_statistics(membership=membership, fasta=None)
    family = overview["input_family_comparison"]
    assert family["scope"].tolist() == ["Input family"]
    assert "median_length" not in family and "species_counts" not in overview
    assert "selected_subcluster" not in overview["audit_outcomes"]
    singleton = subcluster_statistics(membership=membership, fasta=None, group="sub_E")
    assert singleton["centroid_metrics"]["passing_alignments"].eq(0).all()
    assert singleton["centroid_metrics"]["median"].isna().all()
    with pytest.raises(ResearchError, match="absent from the saved audit"):
        subcluster_statistics(membership=membership, fasta=None, group="unknown")


def test_lengths_reject_another_family_with_the_same_size(*, saved_subclusters):
    """A matching protein count cannot substitute for matching exact FASTA IDs."""
    membership, fasta, _taxonomy = saved_subclusters
    fasta.write_text(fasta.read_text(encoding="utf-8").replace(">f\n", ">wrong\n"),
                     encoding="utf-8")
    with pytest.raises(ResearchError, match="different proteins"):
        subcluster_statistics(membership=membership, fasta=fasta, group="sub_A")
