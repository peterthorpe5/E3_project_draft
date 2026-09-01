"""Atomic production pipeline for generic OrthoFinder result resources."""

from __future__ import annotations

import csv
import hashlib
import heapq
import json
import logging
import os
import re
import shutil
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import __schema_version__, __version__
from .distances import (
    DISTANCE_FIELDS,
    DISTANCE_STATISTIC_FIELDS,
    calculate_alignment_distances,
    calculate_patristic_distances,
    read_fasta,
    summarise_distances,
)
from .errors import DistanceCalculationError, InputValidationError, PublicationError
from .io_utils import (
    atomic_write_json,
    configure_logging,
    create_duckdb,
    file_record,
    open_text,
    read_tsv,
    sha256_file,
    tsv_to_parquet,
    utc_now_iso,
    validate_persistent_path,
    write_tsv,
)
from .layout import discover_layout
from .models import ResultLayout
from .parsers import (
    MEMBERSHIP_FIELDS,
    SEQUENCE_FIELDS,
    SPECIES_FIELDS,
    iter_memberships,
    iter_sequence_ids,
    read_species_ids,
)
from .report import build_interactive_report
from .statistics import (
    GROUP_SPECIES_STATISTIC_FIELDS,
    GROUP_STATISTIC_FIELDS,
    GroupAccumulator,
)
from .trees import (
    TREE_EDGE_FIELDS,
    TREE_INVENTORY_FIELDS,
    TREE_NODE_FIELDS,
    iter_tree_inventory,
    normalise_newick_tree,
    tree_id_from_path,
)

_LOGGER = logging.getLogger("orthofinder_results.pipeline")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ALIGNMENT_SUFFIXES = (".fa", ".faa", ".fasta", ".fas", ".aln")

GROUP_TYPES = {
    "group_statistics": {
        "member_count": "int64",
        "species_count": "int64",
        "single_copy_species_count": "int64",
        "max_copies_per_species": "int64",
        "mean_copies_per_species": "float64",
        "is_singleton": "bool",
    },
    "group_species_statistics": {
        "species_member_count": "int64",
        "member_fraction": "float64",
    },
    "species": {"source_line": "int64"},
    "sequences": {"source_line": "int64"},
    "legacy_orthogroup_memberships": {"source_row": "int64"},
    "hog_memberships": {"source_row": "int64"},
    "tree_inventory": {"size_bytes": "int64"},
    "tree_nodes": {
        "is_leaf": "bool",
        "branch_length": "float64",
        "confidence": "float64",
        "descendant_leaf_count": "int64",
    },
    "tree_edges": {"branch_length": "float64"},
    "pairwise_distances": {
        "distance": "float64",
        "comparable_sites": "int64",
        "mismatch_sites": "int64",
    },
    "distance_statistics": {
        "total_member_count": "int64",
        "sampled_member_count": "int64",
        "distance_pair_count": "int64",
        "unresolved_pair_count": "int64",
        "minimum_distance": "float64",
        "q05_distance": "float64",
        "q25_distance": "float64",
        "median_distance": "float64",
        "mean_distance": "float64",
        "q75_distance": "float64",
        "q95_distance": "float64",
        "maximum_distance": "float64",
        "population_stddev_distance": "float64",
        "mean_comparable_sites": "float64",
    },
}


def run_pipeline(
    *,
    results_dir: Path,
    output_dir: Path,
    run_id: str,
    work_dir: Path | None,
    alignment_dir: Path | None,
    distance_source: str,
    distance_group_type: str,
    distance_hierarchy_node: str,
    distance_max_groups: int,
    distance_max_members: int,
    parse_gene_trees: bool,
    report_max_statistic_rows: int,
    report_max_groups: int,
    report_max_members: int,
    report_nearest_neighbours: int,
    resume: bool,
    force: bool,
    verbose: bool,
    keep_failed_work: bool = False,
) -> dict[str, Any]:
    """Build a complete versioned result resource without mutating its authority.

    Args:
        results_dir: Read-only completed OrthoFinder result directory.
        output_dir: New formal run directory.
        run_id: Stable identifier unique to this OrthoFinder run.
        work_dir: Optional staging root. Slurm jobs should use node-local scratch;
            other runs default beside ``output_dir``.
        alignment_dir: Optional aligned FASTA directory for distance calculation.
        distance_source: ``AUTO``, aligned sequence, resolved tree or disabled.
        distance_group_type: ``AUTO``, ``HOG`` or ``LEGACY_ORTHOGROUP``.
        distance_hierarchy_node: HOG node assigned to aligned FASTA filenames.
        distance_max_groups: Maximum alignment groups; zero means unlimited.
        distance_max_members: Exact/sample distance member limit per group.
        parse_gene_trees: Normalise all available gene-tree nodes and edges.
        report_max_statistic_rows: Maximum embedded summary rows; zero means unlimited.
        report_max_groups: Maximum interactive report networks.
        report_max_members: Maximum rendered protein nodes per network.
        report_nearest_neighbours: Nearest-neighbour edges retained per node.
        resume: Reuse an exactly matching completed formal output.
        force: Supersede an existing non-matching output.
        verbose: Enable debug logging.
        keep_failed_work: Retain partial staging/copy directories after a failure.

    Returns:
        Completed run manifest.

    Raises:
        InputValidationError: If inputs or named controls are invalid.
        PublicationError: If verified publication cannot be completed.
    """

    _validate_controls(
        run_id=run_id,
        distance_source=distance_source,
        distance_group_type=distance_group_type,
        distance_max_groups=distance_max_groups,
        distance_max_members=distance_max_members,
        report_max_statistic_rows=report_max_statistic_rows,
        report_max_groups=report_max_groups,
        report_max_members=report_max_members,
        report_nearest_neighbours=report_nearest_neighbours,
        resume=resume,
        force=force,
    )
    layout = discover_layout(results_dir=results_dir)
    output = validate_persistent_path(path=output_dir, role="output_dir")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        work_dir if work_dir is not None else output.parent / ".orthofinder_results_work"
    ).expanduser().resolve()
    if staging_root == output:
        raise InputValidationError("work_dir must not be the formal output directory.")
    staging_root.mkdir(parents=True, exist_ok=True)
    publication_method = (
        "ATOMIC_RENAME"
        if _same_filesystem(first=staging_root, second=output.parent)
        else "VERIFIED_COPY_THEN_ATOMIC_RENAME"
    )
    resolved_alignment_dir = _resolve_pipeline_alignment_dir(
        requested=alignment_dir,
        discovered=layout.alignments_dir,
        distance_source=distance_source,
    )
    source_inventory = _build_source_inventory(
        layout=layout,
        alignment_dir=resolved_alignment_dir,
    )
    input_digest = _inventory_digest(records=source_inventory)
    reusable = _resolve_existing_output(
        output_dir=output,
        run_id=run_id,
        input_digest=input_digest,
        resume=resume,
        force=force,
    )
    if reusable is not None:
        return reusable

    staging = staging_root / f"{output.name}.staging.{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    configure_logging(log_path=staging / "logs" / "run.log", verbose=verbose)
    _LOGGER.info("Starting orthofinder-results %s for run %s", __version__, run_id)
    _LOGGER.info("Read-only authority: %s", layout.results_dir)
    _LOGGER.info("Formal output: %s", output)
    _LOGGER.info("Staging root: %s", staging_root)
    _LOGGER.info("Publication method: %s", publication_method)
    started_at = utc_now_iso()
    try:
        manifest = _build_resource(
            staging=staging,
            layout=layout,
            run_id=run_id,
            source_inventory=source_inventory,
            input_digest=input_digest,
            alignment_dir=resolved_alignment_dir,
            distance_source=distance_source,
            distance_group_type=distance_group_type,
            distance_hierarchy_node=distance_hierarchy_node,
            distance_max_groups=distance_max_groups,
            distance_max_members=distance_max_members,
            parse_gene_trees=parse_gene_trees,
            report_max_statistic_rows=report_max_statistic_rows,
            report_max_groups=report_max_groups,
            report_max_members=report_max_members,
            report_nearest_neighbours=report_nearest_neighbours,
            started_at=started_at,
            staging_root=staging_root,
            publication_method=publication_method,
        )
        # Close the staging file handler before checksums are verified or files
        # cross filesystems. Subsequent CLI messages remain console-only.
        configure_logging(verbose=verbose)
        _publish_completed_resource(
            staging=staging,
            output=output,
            keep_failed_work=keep_failed_work,
        )
        _LOGGER.info("Published completed resource: %s", output)
        return manifest
    except Exception:
        _LOGGER.exception("Run failed before formal publication.")
        configure_logging(verbose=verbose)
        if staging.exists():
            if keep_failed_work:
                failed = staging.with_name(staging.name.replace(".staging.", ".failed."))
                os.replace(staging, failed)
                _LOGGER.error("Retained diagnostic staging directory: %s", failed)
            else:
                shutil.rmtree(staging)
                _LOGGER.info("Removed partial staging directory: %s", staging)
        raise


def _same_filesystem(*, first: Path, second: Path) -> bool:
    """Return whether two existing paths use the same filesystem.

    Args:
        first: First existing path.
        second: Second existing path.

    Returns:
        ``True`` when both device identifiers match.
    """

    return first.stat().st_dev == second.stat().st_dev


def _publish_completed_resource(
    *, staging: Path, output: Path, keep_failed_work: bool
) -> None:
    """Publish a validated staging tree to persistent storage.

    Same-filesystem runs use a direct atomic rename. Cross-filesystem runs copy
    into a hidden directory beside the formal output, verify every manifested
    file, and then atomically rename that verified copy.

    Args:
        staging: Completed resource staging directory.
        output: Formal persistent output directory.
        keep_failed_work: Retain an incomplete cross-filesystem copy for diagnosis.

    Raises:
        PublicationError: If copying, validation or final publication fails.
    """

    if _same_filesystem(first=staging, second=output.parent):
        os.replace(staging, output)
        return

    token = uuid.uuid4().hex
    incoming = output.parent / f".{output.name}.incoming.{token}"
    try:
        shutil.copytree(staging, incoming, copy_function=shutil.copy2)
        _validate_published_copy(source=staging, destination=incoming)
        os.replace(incoming, output)
    except Exception as error:
        if incoming.exists():
            if keep_failed_work:
                failed_copy = output.parent / f".{output.name}.copy_failed.{token}"
                os.replace(incoming, failed_copy)
                _LOGGER.error("Retained incomplete persistent copy for diagnosis: %s", failed_copy)
            else:
                shutil.rmtree(incoming)
                _LOGGER.info("Removed incomplete persistent copy: %s", incoming)
        if isinstance(error, PublicationError):
            raise
        raise PublicationError(
            f"Could not publish verified resource to {output}: {error}"
        ) from error

    try:
        shutil.rmtree(staging)
    except OSError as error:
        _LOGGER.warning(
            "Published output but could not remove scratch staging %s: %s", staging, error
        )


def _validate_published_copy(*, source: Path, destination: Path) -> None:
    """Verify a cross-filesystem copy against its completed manifest.

    Args:
        source: Completed scratch resource.
        destination: Persistent incoming copy.

    Raises:
        PublicationError: If manifests, file sets, sizes or checksums differ.
    """

    source_manifest = source / "run_manifest.json"
    destination_manifest = destination / "run_manifest.json"
    if not source_manifest.is_file() or not destination_manifest.is_file():
        raise PublicationError("Completed resource copy is missing run_manifest.json.")
    if sha256_file(path=source_manifest) != sha256_file(path=destination_manifest):
        raise PublicationError(
            "Copied run_manifest.json checksum does not match scratch authority."
        )

    try:
        manifest = json.loads(destination_manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise PublicationError(f"Copied run manifest is unreadable: {error}") from error
    if manifest.get("status") != "complete":
        raise PublicationError("Copied run manifest is not marked complete.")

    expected_paths: set[Path] = set()
    for record in manifest.get("outputs", []):
        relative_path = Path(str(record.get("path", "")))
        if (
            not relative_path.parts
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise PublicationError(f"Unsafe output path in run manifest: {relative_path}")
        expected_paths.add(relative_path)
        copied_path = destination / relative_path
        if not copied_path.is_file():
            raise PublicationError(f"Copied resource is missing manifested file: {relative_path}")
        if copied_path.stat().st_size != int(record["size_bytes"]):
            raise PublicationError(f"Copied file size differs for: {relative_path}")
        if sha256_file(path=copied_path) != record["sha256"]:
            raise PublicationError(f"Copied file checksum differs for: {relative_path}")

    actual_paths = {
        path.relative_to(destination)
        for path in destination.rglob("*")
        if path.is_file() and path.name != "run_manifest.json"
    }
    if actual_paths != expected_paths:
        missing = sorted(str(path) for path in expected_paths - actual_paths)
        unexpected = sorted(str(path) for path in actual_paths - expected_paths)
        raise PublicationError(
            "Copied resource file set differs from its manifest; "
            f"missing={missing}, unexpected={unexpected}."
        )


def inspect_results(*, results_dir: Path) -> dict[str, Any]:
    """Return a read-only version and capability inspection.

    Args:
        results_dir: Completed OrthoFinder results directory.

    Returns:
        JSON-safe layout record.
    """

    return discover_layout(results_dir=results_dir).to_record()


def _build_resource(
    *,
    staging: Path,
    layout: ResultLayout,
    run_id: str,
    source_inventory: Sequence[Mapping[str, Any]],
    input_digest: str,
    alignment_dir: Path | None,
    distance_source: str,
    distance_group_type: str,
    distance_hierarchy_node: str,
    distance_max_groups: int,
    distance_max_members: int,
    parse_gene_trees: bool,
    report_max_statistic_rows: int,
    report_max_groups: int,
    report_max_members: int,
    report_nearest_neighbours: int,
    started_at: str,
    staging_root: Path,
    publication_method: str,
) -> dict[str, Any]:
    """Populate one staging directory and return its complete manifest."""

    tables = staging / "tables"
    provenance = staging / "provenance"
    qc_dir = staging / "qc"
    report_dir = staging / "report"
    database_dir = staging / "duckdb"
    for directory in (tables, provenance, qc_dir, report_dir, database_dir):
        directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path=provenance / "resolved_layout.json", record=layout.to_record())
    write_tsv(
        path=provenance / "input_inventory.tsv",
        fieldnames=("role", "path", "size_bytes", "sha256"),
        records=source_inventory,
    )

    (
        membership_counts,
        group_count,
        group_species_statistic_count,
        species_from_groups,
    ) = _publish_memberships(
        tables_dir=tables,
        layout=layout,
        run_id=run_id,
    )
    species_count, sequence_count = _publish_identifiers(
        tables_dir=tables,
        layout=layout,
        run_id=run_id,
        species_from_groups=species_from_groups,
    )
    tree_inventory, tree_node_count, tree_edge_count = _publish_trees(
        tables_dir=tables,
        layout=layout,
        run_id=run_id,
        parse_gene_trees=parse_gene_trees,
    )
    distance_count, distance_summaries = _publish_distances(
        tables_dir=tables,
        layout=layout,
        run_id=run_id,
        alignment_dir=alignment_dir,
        distance_source=distance_source,
        distance_group_type=distance_group_type,
        distance_hierarchy_node=distance_hierarchy_node,
        distance_max_groups=distance_max_groups,
        distance_max_members=distance_max_members,
    )

    parquet_tables = _publish_parquet(tables_dir=tables)
    create_duckdb(
        database_path=database_dir / "orthofinder_results.duckdb",
        parquet_tables=parquet_tables,
    )
    group_rows = _load_report_group_statistics(
        path=_table_path(tables_dir=tables, relation="group_statistics"),
        maximum=report_max_statistic_rows,
    )
    network_group_rows, report_memberships, report_distances = _load_report_network_data(
        tables_dir=tables,
        group_statistics_path=_table_path(
            tables_dir=tables,
            relation="group_statistics",
        ),
        distance_summaries=distance_summaries,
        maximum_groups=report_max_groups,
        maximum_members=report_max_members,
    )
    report_group_species = _load_report_group_species_data(
        tables_dir=tables,
        memberships=report_memberships,
    )
    run_metadata = {
        "run_id": run_id,
        "orthofinder_version": layout.orthofinder_version,
        "adapter_name": layout.adapter_name,
        "primary_group_authority": layout.primary_group_authority,
        "package_version": __version__,
        "schema_version": __schema_version__,
        "distance_source_requested": distance_source,
        "capabilities": layout.capabilities.to_record(),
        "publication": {
            "method": publication_method,
            "staging_root": str(staging_root),
            "copy_verified": publication_method == "VERIFIED_COPY_THEN_ATOMIC_RENAME",
        },
    }
    build_interactive_report(
        output_path=report_dir / "orthofinder_results_summary.html",
        run_metadata=run_metadata,
        group_statistics=group_rows,
        network_group_statistics=network_group_rows,
        memberships=report_memberships,
        group_species_statistics=report_group_species,
        distances=report_distances,
        distance_statistics=distance_summaries,
        total_group_statistic_count=group_count,
        total_membership_count=sum(membership_counts.values()),
        max_network_groups=report_max_groups,
        max_network_members=report_max_members,
        nearest_neighbours=report_nearest_neighbours,
    )
    report_text = (report_dir / "orthofinder_results_summary.html").read_text(encoding="utf-8")
    offline_report = not re.search(r"(?:src|href)=[\"']https?://", report_text, re.IGNORECASE)
    qc_rows = _qc_rows(
        layout=layout,
        membership_counts=membership_counts,
        group_count=group_count,
        species_count=species_count,
        sequence_count=sequence_count,
        tree_inventory_count=len(tree_inventory),
        tree_node_count=tree_node_count,
        distance_count=distance_count,
        offline_report=offline_report,
    )
    write_tsv(
        path=qc_dir / "validation_checks.tsv",
        fieldnames=("check_name", "status", "observed_value", "expected_value", "details"),
        records=qc_rows,
    )
    if any(row["status"] == "FAIL" for row in qc_rows):
        raise PublicationError("One or more required validation checks failed.")

    output_inventory = [
        file_record(path=path, relative_to=staging)
        for path in sorted(staging.rglob("*"))
        if path.is_file() and path.name != "run_manifest.json"
    ]
    manifest: dict[str, Any] = {
        **run_metadata,
        "status": "complete",
        "started_at_utc": started_at,
        "finished_at_utc": utc_now_iso(),
        "input_digest": input_digest,
        "source_results_dir": str(layout.results_dir),
        "counts": {
            **membership_counts,
            "group_count": group_count,
            "group_species_statistic_count": group_species_statistic_count,
            "species_count": species_count,
            "sequence_count": sequence_count,
            "tree_file_count": len(tree_inventory),
            "tree_node_count": tree_node_count,
            "tree_edge_count": tree_edge_count,
            "distance_pair_count": distance_count,
            "distance_group_count": len(distance_summaries),
        },
        "report_limits": {
            "maximum_statistic_rows": report_max_statistic_rows,
            "maximum_network_groups": report_max_groups,
            "maximum_network_members": report_max_members,
            "nearest_neighbours": report_nearest_neighbours,
        },
        "outputs": output_inventory,
        "scientific_limitations": [
            "Group membership does not by itself prove orthology or biological function.",
            "Distance method and exact-versus-sampled status must accompany every interpretation.",
            (
                "Interactive networks are bounded exploratory views; analytical tables "
                "are authoritative."
            ),
            (
                "OrthoFinder group identifiers are scoped to this run and must not be "
                "joined across runs by label alone."
            ),
        ],
    }
    atomic_write_json(path=staging / "run_manifest.json", record=manifest)
    return manifest


def _publish_memberships(
    *, tables_dir: Path, layout: ResultLayout, run_id: str
) -> tuple[dict[str, int], int, int, set[str]]:
    """Publish long-form membership tables and streaming group statistics."""

    statistics_path = _table_path(tables_dir=tables_dir, relation="group_statistics")
    counts = {"legacy_orthogroup_membership_count": 0, "hog_membership_count": 0}
    group_count = 0
    group_species_count = 0
    species: set[str] = set()
    species_statistics_path = _table_path(
        tables_dir=tables_dir,
        relation="group_species_statistics",
    )
    with (
        open_text(path=statistics_path, mode="w") as stats_handle,
        open_text(path=species_statistics_path, mode="w") as species_stats_handle,
    ):
        stats_writer = csv.DictWriter(
            stats_handle,
            fieldnames=GROUP_STATISTIC_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        stats_writer.writeheader()
        species_stats_writer = csv.DictWriter(
            species_stats_handle,
            fieldnames=GROUP_SPECIES_STATISTIC_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        species_stats_writer.writeheader()
        legacy_sources = (
            []
            if layout.orthogroups_path is None
            else [(layout.orthogroups_path, "LEGACY_ORTHOGROUP", "")]
        )
        count, groups, group_species_rows = _write_membership_authority(
            path=_table_path(
                tables_dir=tables_dir,
                relation="legacy_orthogroup_memberships",
            ),
            sources=legacy_sources,
            run_id=run_id,
            statistics_writer=stats_writer,
            species_statistics_writer=species_stats_writer,
            species=species,
        )
        counts["legacy_orthogroup_membership_count"] = count
        group_count += groups
        group_species_count += group_species_rows
        hog_sources = [(path, "HOG", path.stem) for path in layout.hog_paths]
        count, groups, group_species_rows = _write_membership_authority(
            path=_table_path(tables_dir=tables_dir, relation="hog_memberships"),
            sources=hog_sources,
            run_id=run_id,
            statistics_writer=stats_writer,
            species_statistics_writer=species_stats_writer,
            species=species,
        )
        counts["hog_membership_count"] = count
        group_count += groups
        group_species_count += group_species_rows
    _LOGGER.info(
        "Published %s memberships across %s run-scoped groups.",
        f"{sum(counts.values()):,}",
        f"{group_count:,}",
    )
    return counts, group_count, group_species_count, species


def _write_membership_authority(
    *,
    path: Path,
    sources: Sequence[tuple[Path, str, str]],
    run_id: str,
    statistics_writer: csv.DictWriter,
    species_statistics_writer: csv.DictWriter,
    species: set[str],
) -> tuple[int, int, int]:
    """Stream related source tables to one membership authority and statistics sink."""

    member_count = 0
    group_count = 0
    group_species_count = 0
    with open_text(path=path, mode="w") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MEMBERSHIP_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for source, group_type, hierarchy_node in sources:
            current_key: tuple[str, str, str] | None = None
            accumulator: GroupAccumulator | None = None
            for row in iter_memberships(
                path=source,
                run_id=run_id,
                group_type=group_type,
                hierarchy_node=hierarchy_node,
            ):
                key = (group_type, hierarchy_node, str(row["group_id"]))
                if key != current_key:
                    if accumulator is not None:
                        _write_accumulator_statistics(
                            accumulator=accumulator,
                            statistics_writer=statistics_writer,
                            species_statistics_writer=species_statistics_writer,
                        )
                        group_count += 1
                        group_species_count += len(accumulator.species_counts)
                    accumulator = GroupAccumulator(
                        run_id=run_id,
                        group_type=group_type,
                        hierarchy_node=hierarchy_node,
                        group_id=str(row["group_id"]),
                        legacy_orthogroup_id=str(row["legacy_orthogroup_id"]),
                        gene_tree_parent_clade=str(row["gene_tree_parent_clade"]),
                        source_file=str(row["source_file"]),
                    )
                    current_key = key
                if accumulator is None:  # pragma: no cover - guarded by key transition
                    raise AssertionError("Membership accumulator was not initialised.")
                accumulator.add_member(species_label=str(row["species_label"]))
                species.add(str(row["species_label"]))
                writer.writerow(row)
                member_count += 1
            if accumulator is not None:
                _write_accumulator_statistics(
                    accumulator=accumulator,
                    statistics_writer=statistics_writer,
                    species_statistics_writer=species_statistics_writer,
                )
                group_count += 1
                group_species_count += len(accumulator.species_counts)
    return member_count, group_count, group_species_count


def _write_accumulator_statistics(
    *,
    accumulator: GroupAccumulator,
    statistics_writer: csv.DictWriter,
    species_statistics_writer: csv.DictWriter,
) -> None:
    """Write group-wide and per-species statistics for one completed group."""

    statistics_writer.writerow(accumulator.to_record())
    species_statistics_writer.writerows(accumulator.to_species_records())


def _publish_identifiers(
    *,
    tables_dir: Path,
    layout: ResultLayout,
    run_id: str,
    species_from_groups: set[str],
) -> tuple[int, int]:
    """Publish source species and optional sequence-identifier authorities."""

    species_lookup: dict[str, str] = {}
    if layout.species_ids_path is not None:
        species_lookup, species_rows = read_species_ids(path=layout.species_ids_path, run_id=run_id)
    else:
        species_rows = [
            {
                "run_id": run_id,
                "species_index": "",
                "species_label": label,
                "source_fasta": "",
                "source_file": "derived_from_group_table_headings",
                "source_line": index,
            }
            for index, label in enumerate(sorted(species_from_groups), start=1)
        ]
    write_tsv(
        path=_table_path(tables_dir=tables_dir, relation="species"),
        fieldnames=SPECIES_FIELDS,
        records=species_rows,
    )
    if layout.sequence_ids_path is not None and species_lookup:
        sequence_count = write_tsv(
            path=_table_path(tables_dir=tables_dir, relation="sequences"),
            fieldnames=SEQUENCE_FIELDS,
            records=iter_sequence_ids(
                path=layout.sequence_ids_path,
                run_id=run_id,
                species_by_index=species_lookup,
            ),
        )
    else:
        sequence_count = write_tsv(
            path=_table_path(tables_dir=tables_dir, relation="sequences"),
            fieldnames=SEQUENCE_FIELDS,
            records=(),
        )
    return len(species_rows), sequence_count


def _publish_trees(
    *, tables_dir: Path, layout: ResultLayout, run_id: str, parse_gene_trees: bool
) -> tuple[list[dict[str, Any]], int, int]:
    """Publish tree file provenance and optional normalised nodes and edges."""

    inventory = list(iter_tree_inventory(layout=layout, run_id=run_id))
    write_tsv(
        path=_table_path(tables_dir=tables_dir, relation="tree_inventory"),
        fieldnames=TREE_INVENTORY_FIELDS,
        records=inventory,
    )
    node_count = 0
    edge_count = 0
    with (
        open_text(
            path=_table_path(tables_dir=tables_dir, relation="tree_nodes"),
            mode="w",
        ) as node_handle,
        open_text(
            path=_table_path(tables_dir=tables_dir, relation="tree_edges"),
            mode="w",
        ) as edge_handle,
    ):
        node_writer = csv.DictWriter(
            node_handle, fieldnames=TREE_NODE_FIELDS, delimiter="\t", lineterminator="\n"
        )
        edge_writer = csv.DictWriter(
            edge_handle, fieldnames=TREE_EDGE_FIELDS, delimiter="\t", lineterminator="\n"
        )
        node_writer.writeheader()
        edge_writer.writeheader()
        for record in inventory:
            if record["tree_type"] != "SPECIES_TREE" and not parse_gene_trees:
                continue
            source = layout.results_dir / str(record["path"])
            nodes, edges = normalise_newick_tree(
                path=source,
                run_id=run_id,
                tree_type=str(record["tree_type"]),
                tree_id=str(record["tree_id"]),
            )
            node_writer.writerows(nodes)
            edge_writer.writerows(edges)
            node_count += len(nodes)
            edge_count += len(edges)
    return inventory, node_count, edge_count


def _publish_distances(
    *,
    tables_dir: Path,
    layout: ResultLayout,
    run_id: str,
    alignment_dir: Path | None,
    distance_source: str,
    distance_group_type: str,
    distance_hierarchy_node: str,
    distance_max_groups: int,
    distance_max_members: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Publish optional aligned-sequence or resolved-tree distances."""

    resolved_group_type = (
        ("HOG" if layout.primary_group_authority == "HOG" else "LEGACY_ORTHOGROUP")
        if distance_group_type == "AUTO"
        else distance_group_type
    )
    resolved_source = _resolve_distance_source(
        requested=distance_source,
        alignment_dir=alignment_dir,
        resolved_tree_dir=layout.resolved_gene_trees_dir,
    )
    summaries: list[dict[str, Any]] = []
    pair_count = 0
    with open_text(
        path=_table_path(tables_dir=tables_dir, relation="pairwise_distances"),
        mode="w",
    ) as distance_handle:
        writer = csv.DictWriter(
            distance_handle,
            fieldnames=DISTANCE_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        if resolved_source == "ALIGNED_SEQUENCE":
            pair_count = _write_alignment_distances(
                writer=writer,
                summaries=summaries,
                alignment_dir=alignment_dir,
                run_id=run_id,
                group_type=resolved_group_type,
                hierarchy_node=distance_hierarchy_node,
                maximum_groups=distance_max_groups,
                maximum_members=distance_max_members,
            )
        elif resolved_source == "RESOLVED_GENE_TREE":
            pair_count = _write_tree_distances(
                writer=writer,
                summaries=summaries,
                tables_dir=tables_dir,
                layout=layout,
                run_id=run_id,
                group_type=resolved_group_type,
                hierarchy_node=distance_hierarchy_node,
                maximum_groups=distance_max_groups,
                maximum_members=distance_max_members,
            )
    write_tsv(
        path=_table_path(tables_dir=tables_dir, relation="distance_statistics"),
        fieldnames=DISTANCE_STATISTIC_FIELDS,
        records=summaries,
    )
    return pair_count, summaries


def _write_alignment_distances(
    *,
    writer: csv.DictWriter,
    summaries: list[dict[str, Any]],
    alignment_dir: Path | None,
    run_id: str,
    group_type: str,
    hierarchy_node: str,
    maximum_groups: int,
    maximum_members: int,
) -> int:
    """Write selected aligned-sequence distances and return their pair count."""

    if alignment_dir is None:  # pragma: no cover - guarded by source resolution
        raise AssertionError("Aligned-sequence distance source lacks an alignment directory.")
    paths = _alignment_paths(directory=alignment_dir)
    if maximum_groups:
        paths = paths[:maximum_groups]
    pair_count = 0
    for index, path in enumerate(paths, start=1):
        group_id = _group_id_from_alignment(path=path)
        rows, summary = calculate_alignment_distances(
            sequences=read_fasta(path=path),
            run_id=run_id,
            group_type=group_type,
            hierarchy_node=hierarchy_node if group_type == "HOG" else "",
            group_id=group_id,
            max_members=maximum_members,
            source_file=str(path),
        )
        writer.writerows(rows)
        summaries.append(summary)
        pair_count += len(rows)
        if index % 100 == 0:
            _LOGGER.info("Calculated distances for %s alignment groups.", f"{index:,}")
    return pair_count


def _write_tree_distances(
    *,
    writer: csv.DictWriter,
    summaries: list[dict[str, Any]],
    tables_dir: Path,
    layout: ResultLayout,
    run_id: str,
    group_type: str,
    hierarchy_node: str,
    maximum_groups: int,
    maximum_members: int,
) -> int:
    """Write selected HOG/orthogroup patristic distances and summaries."""

    tree_dir = layout.resolved_gene_trees_dir
    if tree_dir is None:  # pragma: no cover - guarded by source resolution
        raise AssertionError("Resolved-tree distance source lacks a tree directory.")
    statistics = [
        row
        for row in read_tsv(
            path=_table_path(tables_dir=tables_dir, relation="group_statistics")
        )
        if row["group_type"] == group_type
        and (group_type != "HOG" or row["hierarchy_node"] == hierarchy_node)
        and int(row["member_count"]) >= 2
    ]
    statistics.sort(key=lambda row: (-int(row["member_count"]), row["group_id"]))
    if maximum_groups:
        statistics = statistics[:maximum_groups]
    selected_keys = {_group_key(row) for row in statistics}
    membership_path = _table_path(
        tables_dir=tables_dir,
        relation=(
            "hog_memberships" if group_type == "HOG" else "legacy_orthogroup_memberships"
        ),
    )
    species_by_member_by_key: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for row in read_tsv(path=membership_path):
        key = _group_key(row)
        if key in selected_keys:
            species_by_member_by_key[key][row["member_id"]].add(row["species_label"])
    selected_member_species = {
        (member_id, species)
        for by_member in species_by_member_by_key.values()
        for member_id, species_labels in by_member.items()
        for species in species_labels
    }
    internal_ids_by_member_species: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in read_tsv(path=_table_path(tables_dir=tables_dir, relation="sequences")):
        member_species = (row["member_id"], row["species_label"])
        if member_species in selected_member_species:
            internal_ids_by_member_species[member_species].add(row["internal_id"])
    tree_paths = {
        tree_id_from_path(path=path, tree_type="RESOLVED_GENE_TREE"): path.resolve()
        for path in sorted(tree_dir.iterdir())
        if path.is_file() and not path.name.startswith("._")
    }
    pair_count = 0
    for index, statistic in enumerate(statistics, start=1):
        key = _group_key(statistic)
        group_id = statistic["group_id"]
        species_by_member = species_by_member_by_key.get(key, {})
        members = tuple(sorted(species_by_member))
        tree_candidates = (
            statistic.get("legacy_orthogroup_id", ""),
            group_id,
        )
        tree_path = next(
            (tree_paths[candidate] for candidate in tree_candidates if candidate in tree_paths),
            None,
        )
        if tree_path is None:
            summaries.append(
                _unavailable_distance_summary(
                    run_id=run_id,
                    group_type=group_type,
                    hierarchy_node=hierarchy_node if group_type == "HOG" else "",
                    group_id=group_id,
                    member_count=len(members),
                    reason="No resolved gene tree matched the group or legacy orthogroup ID.",
                )
            )
            continue
        ambiguous_members = {
            member_id: species_labels
            for member_id, species_labels in species_by_member.items()
            if len(species_labels) != 1
        }
        if ambiguous_members:
            member_id, species_labels = sorted(ambiguous_members.items())[0]
            summaries.append(
                _unavailable_distance_summary(
                    run_id=run_id,
                    group_type=group_type,
                    hierarchy_node=hierarchy_node if group_type == "HOG" else "",
                    group_id=group_id,
                    member_count=len(members),
                    reason=(
                        f"Canonical member {member_id!r} occurs under multiple species: "
                        f"{';'.join(sorted(species_labels))}"
                    ),
                    source_file=str(tree_path),
                )
            )
            continue
        member_aliases: dict[str, dict[str, str]] = {}
        for member_id, species_labels in species_by_member.items():
            species_label = next(iter(species_labels))
            aliases = {
                f"{species_label}_{member_id}": "SPECIES_PREFIXED_MEMBER_ID",
            }
            aliases.update(
                {
                    internal_id: "ORTHOFINDER_INTERNAL_ID"
                    for internal_id in internal_ids_by_member_species.get(
                        (member_id, species_label), set()
                    )
                }
            )
            member_aliases[member_id] = aliases
        try:
            rows, summary = calculate_patristic_distances(
                tree_path=tree_path,
                run_id=run_id,
                group_type=group_type,
                hierarchy_node=hierarchy_node if group_type == "HOG" else "",
                group_id=group_id,
                max_members=maximum_members,
                member_ids=members,
                member_aliases=member_aliases,
                source_file=str(tree_path),
            )
        except DistanceCalculationError as error:
            _LOGGER.warning("Distance unavailable for %s: %s", group_id, error)
            summaries.append(
                _unavailable_distance_summary(
                    run_id=run_id,
                    group_type=group_type,
                    hierarchy_node=hierarchy_node if group_type == "HOG" else "",
                    group_id=group_id,
                    member_count=len(members),
                    reason=str(error),
                    source_file=str(tree_path),
                )
            )
            continue
        writer.writerows(rows)
        summaries.append(summary)
        pair_count += len(rows)
        if index % 100 == 0:
            _LOGGER.info("Calculated distances for %s tree-backed groups.", f"{index:,}")
    return pair_count


def _unavailable_distance_summary(
    *,
    run_id: str,
    group_type: str,
    hierarchy_node: str,
    group_id: str,
    member_count: int,
    reason: str,
    source_file: str = "",
) -> dict[str, Any]:
    """Return a schema-complete unavailable distance record."""

    return summarise_distances(
        rows=(),
        run_id=run_id,
        group_type=group_type,
        hierarchy_node=hierarchy_node,
        group_id=group_id,
        method="patristic_branch_length",
        status="UNAVAILABLE",
        total_member_count=member_count,
        sampled_member_count=0,
        source_file=source_file,
        failure_reason=reason,
    )


def _publish_parquet(*, tables_dir: Path) -> dict[str, Path]:
    """Convert every TSV analytical authority into typed Parquet."""

    parquet_tables: dict[str, Path] = {}
    for tsv_path in sorted(tables_dir.glob("*.tsv.gz")):
        relation = tsv_path.name.removesuffix(".tsv.gz")
        parquet_path = tables_dir / f"{relation}.parquet"
        row_count = tsv_to_parquet(
            tsv_path=tsv_path,
            parquet_path=parquet_path,
            column_types=GROUP_TYPES.get(relation),
        )
        _LOGGER.info("Published %s Parquet rows for %s.", f"{row_count:,}", relation)
        parquet_tables[relation] = parquet_path
    return parquet_tables


def _table_path(*, tables_dir: Path, relation: str) -> Path:
    """Return the compressed TSV authority path for an analytical relation.

    Args:
        tables_dir: Analytical table directory.
        relation: Safe relation/file stem.

    Returns:
        Path ending in ``.tsv.gz``.

    Raises:
        ValueError: If the relation cannot be used as a safe table name.
    """

    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", relation) is None:
        raise ValueError(f"Unsafe analytical relation name: {relation!r}")
    return tables_dir / f"{relation}.tsv.gz"


def _load_report_group_statistics(*, path: Path, maximum: int) -> list[dict[str, str]]:
    """Load an explicitly bounded group-summary subset for HTML embedding."""

    rows: list[dict[str, str]] = []
    for row in read_tsv(path=path):
        if maximum and len(rows) >= maximum:
            break
        rows.append(row)
    return rows


def _load_report_network_data(
    *,
    tables_dir: Path,
    group_statistics_path: Path,
    distance_summaries: Sequence[Mapping[str, Any]],
    maximum_groups: int,
    maximum_members: int,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """Load bounded network members and pair distances for the interactive report."""

    distance_keys = {_group_key(row) for row in distance_summaries}
    selected_statistics = heapq.nlargest(
        maximum_groups,
        read_tsv(path=group_statistics_path),
        key=lambda row: (
            _group_key(row) in distance_keys,
            int(row.get("member_count", 0)),
            _group_key(row),
        ),
    )
    selected_keys = {_group_key(row) for row in selected_statistics}
    report_distances = [
        row
        for row in read_tsv(
            path=_table_path(tables_dir=tables_dir, relation="pairwise_distances")
        )
        if _group_key(row) in selected_keys
    ]
    distance_members: dict[str, set[str]] = defaultdict(set)
    for row in report_distances:
        key = _group_key(row)
        distance_members[key].update((row["member_a"], row["member_b"]))

    samplers = {key: _HashRowSampler(maximum=maximum_members, salt=key) for key in selected_keys}
    found_ids: dict[str, set[str]] = defaultdict(set)
    for membership_path in (
        _table_path(tables_dir=tables_dir, relation="legacy_orthogroup_memberships"),
        _table_path(tables_dir=tables_dir, relation="hog_memberships"),
    ):
        for row in read_tsv(path=membership_path):
            key = _group_key(row)
            if key not in selected_keys:
                continue
            if row["member_id"] in distance_members.get(key, set()):
                found_ids[key].add(row["member_id"])
            samplers[key].add(row=row)
    report_members = []
    for key, sampler in samplers.items():
        selected = {row["member_id"]: row for row in sampler.rows()}
        required = distance_members.get(key, set())
        if required:
            # Distance member IDs may use an internal-ID naming scheme not present
            # in the published membership table. Preserve them visibly rather than
            # silently dropping network endpoints.
            for member_id in sorted(required - found_ids[key]):
                selected.setdefault(
                    member_id,
                    {
                        "run_id": "",
                        "group_type": key.split("|", maxsplit=2)[0],
                        "hierarchy_node": key.split("|", maxsplit=2)[1],
                        "group_id": key.split("|", maxsplit=2)[2],
                        "legacy_orthogroup_id": "",
                        "gene_tree_parent_clade": "",
                        "species_label": "unresolved_from_alignment_identifier",
                        "member_id": member_id,
                        "source_file": "distance_table",
                        "source_row": "",
                    },
                )
        report_members.extend(selected.values())
    return selected_statistics, report_members, report_distances


def _load_report_group_species_data(
    *,
    tables_dir: Path,
    memberships: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Load full species copy counts for the bounded network groups.

    Args:
        tables_dir: Analytical table directory.
        memberships: Bounded report memberships identifying selected groups.

    Returns:
        Species-level rows for the selected group keys.
    """

    selected_keys = {_group_key(row) for row in memberships}
    if not selected_keys:
        return []
    return [
        row
        for row in read_tsv(
            path=_table_path(tables_dir=tables_dir, relation="group_species_statistics")
        )
        if _group_key(row) in selected_keys
    ]


class _HashRowSampler:
    """Deterministic bounded row sampler independent of input order."""

    def __init__(self, *, maximum: int, salt: str) -> None:
        """Initialise a sampler.

        Args:
            maximum: Maximum retained unique member rows.
            salt: Stable group-specific hash salt.
        """

        self.maximum = maximum
        self.salt = salt
        self._rows: dict[str, tuple[str, dict[str, str]]] = {}

    def add(self, *, row: Mapping[str, str]) -> None:
        """Consider one membership row for retention.

        Args:
            row: Membership row containing ``member_id``.
        """

        member_id = row["member_id"]
        if member_id in self._rows:
            return
        rank = hashlib.sha256(f"{self.salt}\0{member_id}".encode("utf-8")).hexdigest()
        self._rows[member_id] = (rank, dict(row))
        if len(self._rows) > self.maximum:
            worst = max(self._rows, key=lambda key: self._rows[key][0])
            del self._rows[worst]

    def rows(self) -> list[dict[str, str]]:
        """Return retained rows ordered by member identifier.

        Returns:
            Deterministically selected row mappings.
        """

        return [self._rows[key][1] for key in sorted(self._rows)]


def _build_source_inventory(
    *, layout: ResultLayout, alignment_dir: Path | None
) -> list[dict[str, Any]]:
    """Checksum every source that can alter the requested analytical result."""

    roles: list[tuple[str, Path]] = [("orthofinder_log", layout.log_path)]
    for role, path in (
        ("species_ids", layout.species_ids_path),
        ("sequence_ids", layout.sequence_ids_path),
        ("legacy_orthogroups", layout.orthogroups_path),
        ("species_tree", layout.species_tree_path),
    ):
        if path is not None:
            roles.append((role, path))
    roles.extend(("hog_table", path) for path in layout.hog_paths)
    for role, directory in (
        ("gene_tree", layout.gene_trees_dir),
        ("resolved_gene_tree", layout.resolved_gene_trees_dir),
    ):
        if directory is not None:
            roles.extend(
                (role, path)
                for path in sorted(directory.iterdir())
                if path.is_file() and not path.name.startswith("._")
            )
    if alignment_dir is not None:
        roles.extend(("alignment", path) for path in _alignment_paths(directory=alignment_dir))
    records = []
    for role, path in roles:
        record = file_record(path=path)
        records.append({"role": role, **record})
    return records


def _inventory_digest(*, records: Sequence[Mapping[str, Any]]) -> str:
    """Calculate a deterministic digest over an input inventory."""

    digest = hashlib.sha256()
    for record in sorted(records, key=lambda row: (str(row["role"]), str(row["path"]))):
        digest.update(
            json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _resolve_existing_output(
    *,
    output_dir: Path,
    run_id: str,
    input_digest: str,
    resume: bool,
    force: bool,
) -> dict[str, Any] | None:
    """Reuse, reject or supersede an existing formal output."""

    if not output_dir.exists():
        return None
    manifest_path = output_dir / "run_manifest.json"
    if resume and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("status") == "complete"
            and manifest.get("run_id") == run_id
            and manifest.get("input_digest") == input_digest
            and manifest.get("package_version") == __version__
        ):
            _LOGGER.info("Reusing checksum-matched completed output: %s", output_dir)
            return manifest
    if not force:
        raise PublicationError(
            f"Output directory already exists and was not reusable: {output_dir}. "
            "Use --force only after reviewing it."
        )
    timestamp = utc_now_iso().replace(":", "").replace("-", "")
    superseded = output_dir.with_name(f"{output_dir.name}.superseded.{timestamp}")
    os.replace(output_dir, superseded)
    _LOGGER.warning("Moved existing output to recoverable location: %s", superseded)
    return None


def _resolve_pipeline_alignment_dir(
    *,
    requested: Path | None,
    discovered: Path | None,
    distance_source: str,
) -> Path | None:
    """Resolve alignments only when the selected distance policy can use them."""

    if distance_source in {"NONE", "RESOLVED_GENE_TREE"}:
        return None
    return _resolve_alignment_dir(requested=requested, discovered=discovered)


def _resolve_distance_source(
    *,
    requested: str,
    alignment_dir: Path | None,
    resolved_tree_dir: Path | None,
) -> str:
    """Resolve an explicit or capability-driven distance authority."""

    has_resolved_trees = resolved_tree_dir is not None and any(
        path.is_file() and not path.name.startswith("._") for path in resolved_tree_dir.iterdir()
    )
    if requested == "AUTO":
        if alignment_dir is not None:
            return "ALIGNED_SEQUENCE"
        return "RESOLVED_GENE_TREE" if has_resolved_trees else "NONE"
    if requested == "ALIGNED_SEQUENCE" and alignment_dir is None:
        raise InputValidationError(
            "ALIGNED_SEQUENCE distance source requires a recognised alignment directory."
        )
    if requested == "RESOLVED_GENE_TREE" and not has_resolved_trees:
        raise InputValidationError(
            "RESOLVED_GENE_TREE distance source requires resolved gene-tree files."
        )
    return requested


def _resolve_alignment_dir(*, requested: Path | None, discovered: Path | None) -> Path | None:
    """Resolve an explicit or OrthoFinder-supplied alignment directory."""

    candidate = requested if requested is not None else discovered
    if candidate is None:
        return None
    resolved = Path(candidate).expanduser().resolve()
    if not resolved.is_dir():
        raise InputValidationError(f"Alignment directory does not exist: {resolved}")
    if not _alignment_paths(directory=resolved):
        raise InputValidationError(
            f"Alignment directory contains no recognised FASTA files: {resolved}"
        )
    return resolved


def _alignment_paths(*, directory: Path) -> list[Path]:
    """Return recognised non-sidecar alignment files in deterministic order."""

    return sorted(
        path.resolve()
        for path in directory.iterdir()
        if path.is_file()
        and not path.name.startswith("._")
        and path.suffix.lower() in _ALIGNMENT_SUFFIXES
    )


def _group_id_from_alignment(*, path: Path) -> str:
    """Return an exact filename-derived group identifier."""

    group_id = path.stem
    if not group_id:
        raise InputValidationError(f"Could not derive group identifier from alignment: {path}")
    return group_id


def _group_key(row: Mapping[str, Any]) -> str:
    """Return the report/database collision-safe group key."""

    return "|".join(
        (
            str(row.get("group_type", "")),
            str(row.get("hierarchy_node", "")),
            str(row.get("group_id", "")),
        )
    )


def _qc_rows(
    *,
    layout: ResultLayout,
    membership_counts: Mapping[str, int],
    group_count: int,
    species_count: int,
    sequence_count: int,
    tree_inventory_count: int,
    tree_node_count: int,
    distance_count: int,
    offline_report: bool,
) -> list[dict[str, Any]]:
    """Build explicit run validation checks."""

    return [
        _qc(
            "supported_adapter",
            layout.adapter_name in {"orthofinder_2", "orthofinder_3"},
            layout.adapter_name,
            "orthofinder_2|orthofinder_3",
            "Detected version-specific adapter.",
        ),
        _qc(
            "group_memberships_present",
            sum(membership_counts.values()) > 0,
            sum(membership_counts.values()),
            ">0",
            "At least one group membership is required.",
        ),
        _qc(
            "group_statistics_present",
            group_count > 0,
            group_count,
            ">0",
            "At least one run-scoped group is required.",
        ),
        _qc(
            "species_present",
            species_count > 0,
            species_count,
            ">0",
            "Species are sourced from SpeciesIDs or group headings.",
        ),
        _qc(
            "sequence_identifier_status",
            sequence_count > 0 or not layout.capabilities.has_sequence_ids,
            sequence_count,
            ">0 when SequenceIDs and SpeciesIDs are available",
            "SequenceIDs are optional in portable completed results.",
        ),
        _qc(
            "tree_inventory_status",
            tree_inventory_count > 0
            or not (layout.capabilities.has_species_tree or layout.capabilities.has_gene_trees),
            tree_inventory_count,
            ">0 when trees are available",
            "Every discovered tree is checksum inventoried.",
        ),
        _qc(
            "tree_normalisation_status",
            tree_node_count > 0 or not layout.capabilities.has_species_tree,
            tree_node_count,
            ">0 when a species tree is available",
            "Species tree nodes are always normalised; gene trees are optional.",
        ),
        _qc(
            "distance_status",
            True,
            distance_count,
            ">=0",
            "Distance absence is explicit when no alignment directory is supplied.",
        ),
        _qc(
            "offline_html_report",
            offline_report,
            str(offline_report).lower(),
            "true",
            "The HTML report must not depend on HTTP resources.",
        ),
    ]


def _qc(name: str, passed: bool, observed: Any, expected: Any, details: str) -> dict[str, Any]:
    """Return one standard validation row."""

    return {
        "check_name": name,
        "status": "PASS" if passed else "FAIL",
        "observed_value": observed,
        "expected_value": expected,
        "details": details,
    }


def _validate_controls(
    *,
    run_id: str,
    distance_source: str,
    distance_group_type: str,
    distance_max_groups: int,
    distance_max_members: int,
    report_max_statistic_rows: int,
    report_max_groups: int,
    report_max_members: int,
    report_nearest_neighbours: int,
    resume: bool,
    force: bool,
) -> None:
    """Validate named execution controls before filesystem mutation."""

    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise InputValidationError(
            "run_id must begin with an alphanumeric character and contain only "
            "letters, numbers, underscores, dots and hyphens."
        )
    if distance_source not in {
        "AUTO",
        "ALIGNED_SEQUENCE",
        "RESOLVED_GENE_TREE",
        "NONE",
    }:
        raise InputValidationError(f"Unsupported distance_source: {distance_source}")
    if distance_group_type not in {"AUTO", "HOG", "LEGACY_ORTHOGROUP"}:
        raise InputValidationError(f"Unsupported distance_group_type: {distance_group_type}")
    non_negative = {
        "distance_max_groups": distance_max_groups,
        "report_max_statistic_rows": report_max_statistic_rows,
    }
    for name, value in non_negative.items():
        if value < 0:
            raise InputValidationError(f"{name} must not be negative.")
    positive = {
        "distance_max_members": distance_max_members,
        "report_max_groups": report_max_groups,
        "report_max_members": report_max_members,
        "report_nearest_neighbours": report_nearest_neighbours,
    }
    for name, value in positive.items():
        if value <= 0:
            raise InputValidationError(f"{name} must be positive.")
    if distance_max_members < 2 or report_max_members < 2:
        raise InputValidationError("Distance and report member limits must be at least two.")
    if resume and force:
        raise InputValidationError("--resume and --force are mutually exclusive.")
