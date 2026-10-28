"""Region fitting must not produce matches for pockets outside that region."""

from pocket_workbench import cli
from pocket_workbench.comparison import compare_pair
from pocket_workbench.core import ComparisonSettings, load_project


def test_domain_fit_only_compares_lining_residues_inside_the_domain(project):
    """A good local fit cannot imply pocket correspondence in another domain."""
    result = compare_pair(
        root=project,
        data=load_project(root=project),
        reference="synthetic_reference",
        mobile="synthetic_mobile",
        settings=ComparisonSettings(engine="sequence_kabsch", start=1, end=15),
    )
    assert result["scope"] == "domain"
    assert len(result["pocket_matches"]) == 1
    assert result["pocket_matches"][0]["reference_pocket"] == 1
    assert result["pocket_matches"][0]["mobile_pocket"] == 1


def test_all_pairs_cannot_reinterpret_a_fixed_reference_domain(project):
    """Do not silently apply one reference range to other reference sequences."""
    assert (
        cli.main(
            [
                "compare",
                "--resource",
                str(project),
                "--all-pairs",
                "--start",
                "1",
                "--end",
                "15",
            ]
        )
        == 1
    )
