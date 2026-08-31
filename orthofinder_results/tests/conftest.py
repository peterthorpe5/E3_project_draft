"""Shared synthetic OrthoFinder result fixtures."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def persistent_test_root() -> Path:
    """Provide a non-system-temporary root for publication policy tests."""

    root = Path.cwd() / ".pytest_work" / uuid.uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def make_results(
    root: Path,
    *,
    version: str = "2.5.5",
    include_legacy: bool = True,
    include_alignments: bool = True,
) -> Path:
    """Create a minimal completed OrthoFinder result directory."""

    result = root / f"Results_{version.replace('.', '_')}"
    working = result / "WorkingDirectory"
    hogs = result / "Phylogenetic_Hierarchical_Orthogroups"
    species_trees = result / "Species_Tree"
    gene_trees = result / "Gene_Trees"
    resolved_trees = result / "Resolved_Gene_Trees"
    sequences = result / "Orthogroup_Sequences"
    for directory in (
        working,
        hogs,
        species_trees,
        gene_trees,
        resolved_trees,
        sequences,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (result / "Log.txt").write_text(
        f"OrthoFinder version {version}\nCommand Line: orthofinder -f Example\n",
        encoding="utf-8",
    )
    (working / "SpeciesIDs.txt").write_text("0: Species_A.fa\n1: Species_B.faa\n", encoding="utf-8")
    (working / "SequenceIDs.txt").write_text(
        "0_0: protA first protein\n0_1: protA2 second protein\n1_0: protB\n",
        encoding="utf-8",
    )
    if include_legacy:
        orthogroups = result / "Orthogroups"
        orthogroups.mkdir()
        (orthogroups / "Orthogroups.tsv").write_text(
            "Orthogroup\tSpecies_A\tSpecies_B\nOG0000001\tprotA, protA2\tprotB\n",
            encoding="utf-8",
        )
    if version.startswith("3"):
        hog_header = "HOG\tGene Tree Parent Clade\tSpecies_A\tSpecies_B\n"
        hog_row = "N0.HOG0000001\tN0\tprotA, protA2\tprotB\n"
    else:
        hog_header = "HOG\tOG\tGene Tree Parent Clade\tSpecies_A\tSpecies_B\n"
        hog_row = "N0.HOG0000001\tOG0000001\tN0\tprotA, protA2\tprotB\n"
    (hogs / "N0.tsv").write_text(hog_header + hog_row, encoding="utf-8")
    (hogs / "N1.tsv").write_text(
        hog_header.replace("N0", "N1")
        + hog_row.replace("N0.HOG", "N1.HOG").replace("\tN0\t", "\tN1\t"),
        encoding="utf-8",
    )
    (species_trees / "SpeciesTree_rooted_node_labels.txt").write_text(
        "(Species_A:0.1,Species_B:0.2)N0:0.0;\n", encoding="utf-8"
    )
    tree = "((protA:0.1,protA2:0.2):0.1,protB:0.3)N0:0.0;\n"
    (gene_trees / "OG0000001_tree.txt").write_text(tree, encoding="utf-8")
    (resolved_trees / "OG0000001_tree.txt").write_text(tree, encoding="utf-8")
    (sequences / "OG0000001.fa").write_text(
        ">protA\nAAAA\n>protA2\nAATA\n>protB\nTTTT\n", encoding="utf-8"
    )
    if include_alignments:
        alignments = result / "MultipleSequenceAlignments"
        alignments.mkdir()
        (alignments / "N0.HOG0000001.fa").write_text(
            ">protA\nAAAA\n>protA2\nAATA\n>protB\nTTTT\n", encoding="utf-8"
        )
    return result


@pytest.fixture
def orthofinder2_results(tmp_path: Path) -> Path:
    """Return a compact OrthoFinder 2 fixture."""

    return make_results(tmp_path)


@pytest.fixture
def orthofinder3_results(tmp_path: Path) -> Path:
    """Return a compact HOG-only OrthoFinder 3 fixture."""

    return make_results(tmp_path, version="3.1.0", include_legacy=False)
