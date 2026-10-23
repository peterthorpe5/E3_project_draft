"""Scientific invariants, coordinate transforms and sequence/tree validation."""

import io

import numpy as np
import pytest
from Bio import Phylo

from pocket_workbench.comparison import (
    compare_batch,
    compare_pair,
    kabsch,
    parse_usalign,
    pocket_geometry,
    sequence_pairs,
)
from pocket_workbench.core import (
    ComparisonSettings,
    WorkbenchError,
    load_project,
)
from pocket_workbench.sequences import analyse_sequences, infer_tree, validate_tree


def test_known_rigid_transform_is_recovered():
    """A translation and proper rotation preserve geometry and fit to zero."""
    ref = np.asarray([[0, 0, 0], [1, 2, 0], [0, 1, 3], [3, -1, 2]])
    rotation = np.asarray([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    mobile = ref @ rotation.T + [10, 20, -15]
    fitted, translation, rmsd = kabsch(reference=ref, mobile=mobile)
    assert np.allclose(mobile @ fitted.T + translation, ref)
    assert np.isclose(np.linalg.det(fitted), 1)
    assert rmsd < 1e-10


def test_reflections_cannot_be_fitted_as_a_proper_rotation():
    """Mirror reflection cannot silently appear as a zero-error rigid fit."""
    ref = np.asarray([[0, 0, 0], [1, 2, 0], [0, 1, 3], [3, -1, 2]])
    rotation, _, rmsd = kabsch(reference=ref, mobile=ref * [-1, 1, 1])
    assert np.isclose(np.linalg.det(rotation), 1)
    assert rmsd > 0.1


@pytest.mark.parametrize(
    "points",
    [
        [[0, 0, 0]],
        [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        [[0, 0, 0], [1, 2, 0], [np.nan, 1, 0]],
    ],
)
def test_invalid_fit_coordinates_fail(points):
    """Insufficient, collinear and non-finite selections fail explicitly."""
    with pytest.raises(WorkbenchError):
        kabsch(reference=np.asarray(points), mobile=np.asarray(points))


def test_pocket_geometry_distinguishes_overlap_from_matching_residues():
    """Dense many-to-one proximity does not inflate the mutual-nearest fraction."""
    reference = np.asarray([[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0]])
    mobile = np.asarray([[0, 0, 0]])
    result = pocket_geometry(reference=reference, mobile=mobile, radius=4)
    assert result["symmetric_overlap"] == 1
    assert result["mutual_match_fraction"] == 0.5
    distant = pocket_geometry(reference=reference, mobile=mobile + 100, radius=4)
    assert distant["symmetric_overlap"] == 0
    assert distant["mutual_match_fraction"] == 0


def test_global_sequence_mapping_keeps_insertions_separate():
    """An insertion does not become a shifted sequence-position match."""
    pairs = sequence_pairs(reference="ACDEFGHIKLMN", mobile="ACDEFGWWWHIKLMN")
    assert (6, 9) in pairs
    assert len(pairs) == 12


def test_full_synthetic_comparison_has_correct_transform_and_no_fake_tm(project):
    """Pockets coincide after a known rigid transform, with TM-score unavailable."""
    result = compare_pair(
        root=project,
        data=load_project(root=project),
        reference="synthetic_reference",
        mobile="synthetic_mobile",
        settings=ComparisonSettings(engine="sequence_kabsch", top_pockets=2),
    )
    assert result["status"] == "complete"
    assert result["rmsd"] < 0.002
    assert result["tm_reference"] is None
    match = result["pocket_matches"][0]
    assert match["position_supported"] is True
    assert match["fold_supported"] is None
    assert match["centroid_distance"] < 0.002
    assert match["symmetric_overlap"] == 1
    assert (project / result["mobile_aligned"]).is_file()


def test_domain_and_minimum_atoms_are_enforced(project):
    """A small or unsupported domain cannot be reported as a valid fit."""
    with pytest.raises(WorkbenchError, match="Only"):
        compare_pair(
            root=project,
            data=load_project(root=project),
            reference="synthetic_reference",
            mobile="synthetic_mobile",
            settings=ComparisonSettings(engine="sequence_kabsch", start=1, end=5),
        )


def test_pocket_mapping_must_be_complete_for_positional_support(project):
    """A spatially matching subset cannot hide missing lining residues."""
    data = load_project(root=project)
    for row in data["pockets"]:
        if row["sample_id"] == "synthetic_reference":
            row["residues"].append("A_9999")
    result = compare_pair(
        root=project,
        data=data,
        reference="synthetic_reference",
        mobile="synthetic_mobile",
        settings=ComparisonSettings(engine="sequence_kabsch", top_pockets=2),
    )
    assert all(
        not row["complete_mapping"] and not row["position_supported"]
        for row in result["pocket_matches"]
    )


def test_batch_preserves_failures_and_builds_queryable_results(project):
    """One missing model does not erase a successful pair in the same batch."""
    result = compare_batch(
        root=project,
        pairs=[
            ("synthetic_reference", "synthetic_variant"),
            ("synthetic_reference", "absent"),
        ],
        settings=ComparisonSettings(engine="sequence_kabsch"),
    )
    assert [row["status"] for row in result] == ["complete", "failed"]
    assert "absent" in load_project(root=project)["comparisons"][-1]["mobile"]


def test_usalign_matrix_convention_and_rigidity():
    """The external transform maps mobile coordinates into the reference frame."""
    text = (
        "Aligned length= 30, RMSD= 0.25, Seq_ID=n_identical/n_aligned= 0.9\nTM-score="
        " 0.8\nTM-score= 0.9\n"
    )
    parsed = parse_usalign(text=text, matrix="0 10 0 -1 0\n1 20 1 0 0\n2 30 0 0 1\n")
    assert parsed["tm_mobile"] == 0.8
    assert parsed["tm_reference"] == 0.9
    assert np.allclose(
        np.asarray([1, 2, 3]) @ np.asarray(parsed["rotation"]).T
        + parsed["translation"],
        [8, 21, 33],
    )
    with pytest.raises(WorkbenchError):
        parse_usalign(text=text, matrix="0 0 2 0 0\n1 0 0 2 0\n2 0 0 0 2\n")


@pytest.mark.parametrize(
    "options",
    [
        {"min_plddt": 101},
        {"min_plddt": float("nan")},
        {"radius": 0},
        {"min_overlap": 2},
        {"min_atoms": 2},
        {"top_pockets": 101},
        {"timeout": 0},
        {"engine": "other"},
        {"start": 10},
        {"start": 10, "end": 2},
    ],
)
def test_invalid_comparison_settings_are_rejected(options):
    """Numerical and scope settings are validated before any computation."""
    with pytest.raises(WorkbenchError):
        ComparisonSettings(**options)


def test_bootstrap_is_reproducible_and_tree_preserves_tip_ids():
    """Column resampling is seeded and retains the original sequence IDs."""
    records = {
        "a": "ACDEFGHIKLMNPQRSTVWY",
        "b": "ACDEFGHIKLMNPQASTVWY",
        "c": "ACDEFGHIKLMNPRASTVWY",
        "d": "ACDEFGHIKLMNAAASTVWY",
    }
    first = infer_tree(records=records, max_gap=0.5, bootstrap=10, seed=7)
    second = infer_tree(records=records, max_gap=0.5, bootstrap=10, seed=7)
    assert first == second
    assert first[2]["retained_columns"] == 20
    assert set(
        tip.name for tip in Phylo.read(io.StringIO(first[0]), "newick").get_terminals()
    ) == set(records)


def test_external_tree_requires_exact_identifiers():
    """Missing, extra and repeated tree leaves are not guessed or renamed."""
    assert validate_tree(text="(a:0.1,b:0.2,c:0.3);", sequence_ids={"a", "b", "c"})
    for tree in ["(a,b,x);", "(a,a,c);", "(a,b);"]:
        with pytest.raises(WorkbenchError):
            validate_tree(text=tree, sequence_ids={"a", "b", "c"})


def test_famsa_alignment_and_sequence_mapping_are_materialised(project):
    """Real local FAMSA produces equal-length rows and reproducible artifacts."""
    result = analyse_sequences(root=project, threads=1, bootstrap=5)
    assert result["sequence_count"] == 3
    assert result["bootstrap_replicates"] == 5
    assert (project / result["alignment_path"]).is_file()
    assert (project / result["tree_path"]).is_file()


def test_imported_alignment_cannot_change_a_sequence(project, tmp_path):
    """An externally edited MSA must still correspond to the selected proteins."""
    path = tmp_path / "bad.fasta"
    path.write_text(">synthetic_reference\nAAAA\n")
    with pytest.raises(WorkbenchError, match="preserve"):
        analyse_sequences(root=project, aligned_fasta=path)
