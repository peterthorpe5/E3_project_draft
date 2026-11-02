"""Worker-side comparison artifacts for complete, explicitly selected cluster/alignment rows."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .common import ResearchConfig, ResearchError, atomic_json, iter_fasta
from .comparisons import alignment_comparison, species_comparison, venn_regions
from .jobs import artifact_path


def compare_job(*, config: ResearchConfig, parameters: dict, output: Path) -> dict[str, Path]:
    """Create bounded comparison matrices and display hierarchies on the analysis worker.

    Args:
        config: Worker profile.
        parameters: Exact source_job plus kind and explicit sequence_ids/cluster_ids.
        output: Owned result directory.

    Returns:
        Full selected matrices, denominators, hierarchy and scientific interpretation.

    Raises:
        ResearchError: If a selected source or ID is unavailable or invalid.
    """
    kind = parameters.get("kind")
    source_job = str(parameters.get("source_job", ""))
    selected = parameters.get("sequence_ids" if kind == "alignment" else "cluster_ids")
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 1000
            or any(not isinstance(value, str) or not value.strip() for value in selected)
            or len(set(selected)) != len(selected)):
        raise ResearchError("Comparison requires an explicit, unique non-empty ID selection")
    frames, extra = {}, {}
    if kind == "alignment":
        path = artifact_path(workspace=config.workspace,
                             job_id=source_job, artifact="alignment.fasta")
        records = {
            identifier: sequence
            for identifier, sequence in iter_fasta(path=path, aligned=True)
            if identifier in set(selected)
        }
        if set(records) != set(selected):
            raise ResearchError("Some comparison proteins are absent from the selected alignment")
        matrix = alignment_comparison(records=records)
        interpretation = (
            "Identity over comparable canonical aligned residues; gaps/unknowns excluded. "
            "Average linkage of 1-identity is a display hierarchy, not an inferred species tree."
        )
    elif kind == "species":
        path = artifact_path(workspace=config.workspace, job_id=source_job,
                             artifact="cluster_species.tsv")
        connection = duckdb.connect(config={"memory_limit": f"{config.memory_gb}GB"})
        try:
            connection.read_csv(str(path), delimiter="\t", header=True, all_varchar=True
                                ).create_view(view_name="species")
            rows = connection.execute(
                "SELECT * FROM species WHERE cluster_id IN (SELECT unnest(?))",
                [selected],
            ).fetchdf()
        finally:
            connection.close()
        if set(rows["cluster_id"]) != set(selected):
            raise ResearchError("Some selected clusters have no complete species-count records")
        matrix, coverage = species_comparison(rows=rows)
        frames.update({"classification_coverage.tsv": coverage, "species_counts.tsv": rows})
        if len(selected) in {2, 3} and coverage["reviewed_taxon_count"].gt(0).all():
            extra["venn_cluster_order"] = selected
            extra["venn_regions"] = venn_regions(rows=rows, cluster_ids=selected)
        interpretation = (
            "Unique reviewed taxon-set Jaccard similarity; unclassified members are excluded "
            "from species sets and reported separately. The hierarchy is not a species phylogeny."
        )
    else:
        raise ResearchError("Comparison kind must be alignment or species")
    frames["hierarchy.tsv"] = pd.DataFrame(
        data=matrix.linkage_matrix, columns=("left_node", "right_node", "distance", "leaf_count"),
    )
    frames["display_order.tsv"] = pd.DataFrame(data={"identifier": matrix.order})
    artifacts = {}
    for name, frame in frames.items():
        frame.to_csv(path_or_buf=output / name, sep="\t", index=False)
        artifacts[name] = output / name
    for name, frame in (("similarity.tsv", matrix.similarity),
                        ("denominators.tsv", matrix.denominators)):
        frame.rename_axis(index="identifier").to_csv(
            path_or_buf=output / name, sep="\t", index=True)
        artifacts[name] = output / name
    summary = output / "comparison_summary.json"
    atomic_json(path=summary, value={
        "kind": kind, "source_job": source_job, "selected_ids": selected,
        "hierarchy_status": matrix.hierarchy_status,
        "interpretation": interpretation, **extra,
    })
    artifacts[summary.name] = summary
    return artifacts
