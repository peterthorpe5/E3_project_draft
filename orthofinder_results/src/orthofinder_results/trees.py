"""Tree inventory and normalisation for OrthoFinder phylogenies."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .io_utils import file_record
from .models import ResultLayout

TREE_INVENTORY_FIELDS = (
    "run_id",
    "tree_type",
    "tree_id",
    "group_id",
    "path",
    "size_bytes",
    "sha256",
)
TREE_NODE_FIELDS = (
    "run_id",
    "tree_type",
    "tree_id",
    "node_id",
    "parent_node_id",
    "node_name",
    "is_leaf",
    "branch_length",
    "confidence",
    "descendant_leaf_count",
)
TREE_EDGE_FIELDS = (
    "run_id",
    "tree_type",
    "tree_id",
    "parent_node_id",
    "child_node_id",
    "branch_length",
)


def iter_tree_inventory(*, layout: ResultLayout, run_id: str) -> Iterator[dict[str, Any]]:
    """Yield checksum-bound records for all available tree files.

    Args:
        layout: Discovered OrthoFinder result layout.
        run_id: Immutable run identifier.

    Yields:
        Species, gene and resolved-gene tree file records.
    """

    sources: list[tuple[str, Path]] = []
    if layout.species_tree_path is not None:
        sources.append(("SPECIES_TREE", layout.species_tree_path))
    for tree_type, directory in (
        ("GENE_TREE", layout.gene_trees_dir),
        ("RESOLVED_GENE_TREE", layout.resolved_gene_trees_dir),
    ):
        if directory is None:
            continue
        sources.extend(
            (tree_type, path)
            for path in sorted(directory.iterdir())
            if path.is_file() and not path.name.startswith("._")
        )
    for tree_type, path in sources:
        inventory = file_record(path=path, relative_to=layout.results_dir)
        tree_id = tree_id_from_path(path=path, tree_type=tree_type)
        yield {
            "run_id": run_id,
            "tree_type": tree_type,
            "tree_id": tree_id,
            "group_id": "" if tree_type == "SPECIES_TREE" else tree_id,
            **inventory,
        }


def tree_id_from_path(*, path: Path, tree_type: str) -> str:
    """Derive a run-scoped tree identifier from an OrthoFinder filename.

    Args:
        path: Tree file path.
        tree_type: Declared tree type.

    Returns:
        ``SPECIES_TREE`` or the filename-derived group identifier.

    Raises:
        ValueError: If the tree type is unsupported.
    """

    if tree_type == "SPECIES_TREE":
        return "SPECIES_TREE"
    if tree_type not in {"GENE_TREE", "RESOLVED_GENE_TREE"}:
        raise ValueError(f"Unsupported tree_type: {tree_type!r}")
    name = path.name
    for suffix in (".txt", ".tree", ".nwk", ".newick"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = re.sub(r"_tree(?:_id)?$", "", name, flags=re.IGNORECASE)
    if not name:
        raise InputValidationError(f"Could not derive a tree identifier from {path}.")
    return name


def normalise_newick_tree(
    *, path: Path, run_id: str, tree_type: str, tree_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert one Newick tree into stable node and edge records.

    Args:
        path: Newick tree file.
        run_id: Immutable run identifier.
        tree_type: Species, gene or resolved-gene tree type.
        tree_id: Run-scoped tree identifier.

    Returns:
        Node records and directed parent-to-child edge records.

    Raises:
        InputValidationError: If Biopython cannot parse exactly one tree.
    """

    from Bio import Phylo
    from Bio.Phylo.NewickIO import NewickError

    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise InputValidationError(f"Missing or empty Newick tree: {source}")
    try:
        tree = Phylo.read(str(source), "newick")
    except (NewickError, ValueError, OSError) as error:
        raise InputValidationError(f"Could not parse Newick tree {source}: {error}") from error

    clades = list(tree.find_clades(order="preorder"))
    node_ids = {id(clade): f"{tree_id}:n{index}" for index, clade in enumerate(clades)}
    parents: dict[int, str] = {}
    for parent in clades:
        for child in parent.clades:
            parents[id(child)] = node_ids[id(parent)]
    descendant_counts: dict[int, int] = {}
    for clade in tree.find_clades(order="postorder"):
        descendant_counts[id(clade)] = (
            1
            if clade.is_terminal()
            else sum(descendant_counts[id(child)] for child in clade.clades)
        )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for clade in clades:
        node_id = node_ids[id(clade)]
        parent_id = parents.get(id(clade), "")
        branch_length = clade.branch_length
        confidence = clade.confidence
        nodes.append(
            {
                "run_id": run_id,
                "tree_type": tree_type,
                "tree_id": tree_id,
                "node_id": node_id,
                "parent_node_id": parent_id,
                "node_name": clade.name or "",
                "is_leaf": clade.is_terminal(),
                "branch_length": "" if branch_length is None else float(branch_length),
                "confidence": "" if confidence is None else float(confidence),
                "descendant_leaf_count": descendant_counts[id(clade)],
            }
        )
        if parent_id:
            edges.append(
                {
                    "run_id": run_id,
                    "tree_type": tree_type,
                    "tree_id": tree_id,
                    "parent_node_id": parent_id,
                    "child_node_id": node_id,
                    "branch_length": "" if branch_length is None else float(branch_length),
                }
            )
    return nodes, edges
