"""Restartable Snakemake shard workers and aggregators for structural completion."""

from __future__ import annotations

import html
import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from e3workflow.config import WorkflowConfig
from e3workflow.errors import StageError
from e3workflow.io_utils import (
    atomic_write_json,
    read_tsv,
    sha256_file,
    utc_now,
    write_tsv,
)
from e3workflow.resources import (
    LIGANDABILITY_DATASETS,
    build_ligandability_manifest,
)
from e3workflow.tabular import quote_literal, write_records

LOGGER = logging.getLogger("e3workflow.distributed")

TASK_MARKER_FIELDS = (
    "task_kind",
    "task_index",
    "status",
    "configuration_digest",
    "entity_id",
    "output_directory",
    "finished_at_utc",
)

STRUCTURAL_DATASETS = (
    "structural_alignments",
    "pocket_comparisons",
    "pocket_residue_matches",
    "structural_alignment_summary",
    "structural_pocket_sensitivity_comparisons",
    "structural_pocket_sensitivity_residue_matches",
    "structural_pocket_sensitivity_member_summary",
    "structural_pocket_sensitivity_group_summary",
)

ASSET_MANIFEST_FIELDS = (
    "accession",
    "action",
    "bytes",
    "path",
    "sha256",
    "url",
)


def ligandability_task_count(config: WorkflowConfig) -> int:
    """Return the fixed upper-bound shard count for the configured campaign."""
    return (
        config.analysis.prioritisation.structure_group_limit
        * len(config.analysis.prioritisation.target_species)
    )


def structural_alignment_task_count(config: WorkflowConfig) -> int:
    """Return the fixed upper-bound group-shard count."""
    return config.analysis.prioritisation.structure_group_limit


def ligandability_shard_root(config: WorkflowConfig, task_index: int) -> Path:
    """Return one stable, hidden ligandability shard directory."""
    return (
        config.run_root
        / ".work_cache"
        / "09_ligandability"
        / f"task_{task_index:04d}"
    )


def structural_alignment_shard_root(
    config: WorkflowConfig,
    task_index: int,
) -> Path:
    """Return one stable, hidden structural-alignment shard directory."""
    return (
        config.run_root
        / ".work_cache"
        / "09b_structural_alignment"
        / f"task_{task_index:04d}"
    )


def _marker_path(root: Path) -> Path:
    """Return a shard's formal completion marker."""
    return root / "task_complete.tsv"


def _read_marker(root: Path) -> dict[str, str] | None:
    """Read one complete task marker, returning ``None`` when absent."""
    marker = _marker_path(root)
    if not marker.is_file():
        return None
    fields, rows = read_tsv(marker)
    if tuple(fields) != TASK_MARKER_FIELDS or len(rows) != 1:
        raise StageError(f"Malformed shard completion marker: {marker}")
    return rows[0]


def _validate_reusable_marker(
    *,
    root: Path,
    config: WorkflowConfig,
    task_kind: str,
    task_index: int,
    entity_id: str,
) -> bool:
    """Return whether an existing shard exactly matches the current task."""
    marker = _read_marker(root)
    if marker is None:
        return False
    expected = {
        "task_kind": task_kind,
        "task_index": str(task_index),
        "configuration_digest": config.digest,
        "entity_id": entity_id,
    }
    mismatches = {
        field: (expected_value, marker.get(field, ""))
        for field, expected_value in expected.items()
        if marker.get(field) != expected_value
    }
    if mismatches:
        raise StageError(
            f"Existing shard marker does not match task {task_kind}/{task_index}: "
            f"{mismatches}"
        )
    output_directory = Path(marker["output_directory"])
    if marker["status"] == "COMPLETE":
        manifest = output_directory / "provenance" / "run_manifest.json"
        if not manifest.is_file() or manifest.stat().st_size == 0:
            raise StageError(f"Completed shard lacks its run manifest: {manifest}")
    return True


def _publish_marker(
    *,
    root: Path,
    config: WorkflowConfig,
    task_kind: str,
    task_index: int,
    status: str,
    entity_id: str,
    output_directory: Path,
) -> Path:
    """Publish one deterministic shard marker."""
    write_tsv(
        _marker_path(root),
        [
            {
                "task_kind": task_kind,
                "task_index": task_index,
                "status": status,
                "configuration_digest": config.digest,
                "entity_id": entity_id,
                "output_directory": output_directory,
                "finished_at_utc": utc_now(),
            }
        ],
        TASK_MARKER_FIELDS,
    )
    return _marker_path(root)


def _archive_partial(root: Path) -> None:
    """Move a non-reusable task directory aside without deleting evidence."""
    if not root.exists():
        return
    failed_root = root.parent / "failed"
    failed_root.mkdir(parents=True, exist_ok=True)
    destination = failed_root / f"{root.name}.{uuid.uuid4().hex}"
    os.replace(root, destination)


def _run_component(
    *,
    argv: Sequence[str],
    log_path: Path,
    working_directory: Path,
) -> None:
    """Run one component command and retain unmodified combined output."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=working_directory,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
            )
        except OSError as exc:
            raise StageError(f"Could not start component command {argv[0]}: {exc}") from exc
    if completed.returncode != 0:
        raise StageError(
            f"Component command returned {completed.returncode}; see {log_path}"
        )


def _ligandability_records(config: WorkflowConfig) -> list[dict[str, str]]:
    """Read the deterministic Stage-08 ligandability task table."""
    path = (
        config.run_root
        / "08_shortlist_gate"
        / "tables"
        / "ligandability_accessions.tsv"
    )
    _fields, rows = read_tsv(path)
    return sorted(
        rows,
        key=lambda row: (
            int(row["evolutionary_group_rank"]),
            row["species_column"],
            row["accession"],
        ),
    )


def run_ligandability_shard(
    *,
    config: WorkflowConfig,
    task_index: int,
) -> dict[str, Any]:
    """Run or reuse one accession-level ligandability shard."""
    if task_index < 0 or task_index >= ligandability_task_count(config):
        raise StageError(f"Ligandability task index is outside the configured range: {task_index}")
    records = _ligandability_records(config)
    task_root = ligandability_shard_root(config, task_index)
    entity_id = records[task_index]["accession"] if task_index < len(records) else ""
    if _validate_reusable_marker(
        root=task_root,
        config=config,
        task_kind="ligandability",
        task_index=task_index,
        entity_id=entity_id,
    ):
        return {
            "status": "reused",
            "task_index": task_index,
            "marker": str(_marker_path(task_root)),
        }
    _archive_partial(task_root)
    task_root.parent.mkdir(parents=True, exist_ok=True)
    staging = task_root.parent / f".{task_root.name}.running.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    output_directory = staging / "component_output"
    if task_index >= len(records):
        _publish_marker(
            root=staging,
            config=config,
            task_kind="ligandability",
            task_index=task_index,
            status="SKIPPED_UNUSED_SLOT",
            entity_id="",
            output_directory=output_directory,
        )
        os.replace(staging, task_root)
        return {
            "status": "skipped_unused_slot",
            "task_index": task_index,
            "marker": str(_marker_path(task_root)),
        }
    record = records[task_index]
    component_config = config.analysis.ligandability.component_config
    if component_config is None:
        raise StageError("Generated ligandability requires analysis.ligandability.component_config")
    input_path = staging / "accession.tsv"
    write_tsv(input_path, [record], tuple(record))
    argv = (
        "conda",
        "run",
        "--no-capture-output",
        "--name",
        config.analysis.ligandability.conda_environment,
        "e3-ligandability",
        "run",
        "--input",
        str(input_path),
        "--output-dir",
        str(output_directory),
        "--config",
        str(component_config),
        "--git-repository",
        str(config.project_root),
    )
    try:
        _run_component(
            argv=argv,
            log_path=staging / "component.log",
            working_directory=config.project_root,
        )
        component_manifest = (
            output_directory / "provenance" / "run_manifest.json"
        )
        if component_manifest.is_file():
            _rebase_component_manifest(
                manifest_path=component_manifest,
                temporary_root=staging,
                stable_root=task_root,
            )
        else:
            LOGGER.warning(
                "Legacy ligandability component produced no JSON run manifest: %s",
                output_directory,
            )
        _publish_marker(
            root=staging,
            config=config,
            task_kind="ligandability",
            task_index=task_index,
            status="COMPLETE",
            entity_id=record["accession"],
            output_directory=task_root / "component_output",
        )
        os.replace(staging, task_root)
    except BaseException:
        failed = task_root.parent / "failed"
        failed.mkdir(parents=True, exist_ok=True)
        os.replace(staging, failed / f"{task_root.name}.{uuid.uuid4().hex}")
        raise
    return {
        "status": "complete",
        "task_index": task_index,
        "accession": record["accession"],
        "marker": str(_marker_path(task_root)),
    }


def _parquet_sources(
    *,
    roots: Sequence[Path],
    dataset: str,
) -> list[Path]:
    """Return one dataset's shard Parquets in deterministic order."""
    sources = [
        root / "component_output" / "tables" / "parquet" / f"{dataset}.parquet"
        for root in roots
    ]
    return [
        source.resolve()
        for source in sources
        if source.is_file() and source.stat().st_size > 0
    ]


def _copy_parquet_union(*, sources: Sequence[Path], destination: Path) -> None:
    """Atomically union compatible Parquet shards by column name."""
    if not sources:
        raise StageError(f"No Parquet shards were supplied for {destination.stem}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    source_sql = "[" + ", ".join(quote_literal(path) for path in sources) + "]"
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"COPY (SELECT * FROM read_parquet({source_sql}, union_by_name=true)) "
            f"TO {quote_literal(temporary)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StageError(f"Could not aggregate {destination.stem}: {exc}") from exc
    finally:
        connection.close()
    temporary.replace(destination)


def _relative_component_asset_path(*, recorded_path: str) -> Path:
    """Return the safe suffix below a shard's component-output directory.

    Args:
        recorded_path: Absolute component path written before atomic shard publication.

    Returns:
        Relative path below the unique ``component_output`` directory.

    Raises:
        StageError: If the recorded path is empty, ambiguous or unsafe.
    """
    supplied = Path(recorded_path)
    positions = [
        index for index, part in enumerate(supplied.parts) if part == "component_output"
    ]
    if len(positions) != 1:
        raise StageError(
            "Ligandability asset path does not contain exactly one "
            f"component_output directory: {recorded_path}"
        )
    relative = Path(*supplied.parts[positions[0] + 1:])
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise StageError(f"Ligandability asset path has an unsafe suffix: {recorded_path}")
    return relative


def _publish_rebased_asset_manifest(
    *,
    roots: Sequence[Path],
    destination: Path,
) -> int:
    """Publish stable shard asset paths after validating size and checksum.

    Component manifests are produced inside a temporary
    ``.task_NNNN.running.UUID`` directory. Atomic publication renames that
    directory to ``task_NNNN``; therefore every recorded path must be rebased
    onto the stable shard root before downstream structural analysis.

    Args:
        roots: Completed stable ligandability shard roots.
        destination: Aggregate asset-manifest Parquet path.

    Returns:
        Number of validated assets published.

    Raises:
        StageError: If an asset record, path, size or checksum is invalid.
    """
    records: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for task_root in roots:
        source = (
            task_root
            / "component_output"
            / "tables"
            / "parquet"
            / "asset_manifest.parquet"
        )
        if not source.is_file():
            continue
        marker = _read_marker(task_root)
        if marker is None:
            raise StageError(f"Ligandability shard has no completion marker: {task_root}")
        for row in _table_records(source):
            accession = str(row.get("accession") or "").strip()
            if not accession or accession != marker["entity_id"]:
                raise StageError(
                    "Ligandability asset accession does not match its stable shard: "
                    f"{accession!r} versus {marker['entity_id']!r}"
                )
            relative = _relative_component_asset_path(
                recorded_path=str(row.get("path") or "")
            )
            stable_root = (task_root / "component_output").resolve()
            stable_path = (stable_root / relative).resolve()
            if not stable_path.is_relative_to(stable_root):
                raise StageError(f"Ligandability asset escapes its shard: {stable_path}")
            if stable_path in seen_paths:
                raise StageError(f"Duplicate ligandability asset path: {stable_path}")
            seen_paths.add(stable_path)
            if not stable_path.is_file():
                raise StageError(f"Published ligandability asset is missing: {stable_path}")
            try:
                expected_size = int(row.get("bytes"))
            except (TypeError, ValueError) as exc:
                raise StageError(
                    f"Ligandability asset has an invalid byte count: {stable_path}"
                ) from exc
            if stable_path.stat().st_size != expected_size:
                raise StageError(f"Ligandability asset size changed: {stable_path}")
            expected_digest = str(row.get("sha256") or "").strip().lower()
            if sha256_file(stable_path) != expected_digest:
                raise StageError(f"Ligandability asset checksum changed: {stable_path}")
            records.append(
                {
                    "accession": accession,
                    "action": row.get("action", ""),
                    "bytes": expected_size,
                    "path": stable_path,
                    "sha256": expected_digest,
                    "url": row.get("url", ""),
                }
            )
    if not records:
        raise StageError("Generated ligandability shards published no asset records")
    records.sort(key=lambda row: (str(row["accession"]), str(row["path"])))
    count = write_records(
        tsv_path=destination.parent.parent / "asset_manifest.tsv",
        parquet_path=destination,
        fieldnames=ASSET_MANIFEST_FIELDS,
        records=records,
        column_types={"bytes": "BIGINT"},
    )
    LOGGER.info("Published %d checksum-validated stable ligandability assets", count)
    return count


def _rebase_component_manifest(
    *,
    manifest_path: Path,
    temporary_root: Path,
    stable_root: Path,
) -> None:
    """Replace temporary shard paths in a component provenance manifest.

    Args:
        manifest_path: Component JSON manifest to update before publication.
        temporary_root: Temporary shard directory embedded in input paths.
        stable_root: Final immutable shard directory.

    Raises:
        StageError: If the component manifest cannot be decoded.
    """
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(
            f"Could not read component provenance manifest: {manifest_path}"
        ) from exc

    temporary = str(temporary_root)
    stable = str(stable_root)

    def rebase(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(temporary, stable)
        if isinstance(value, list):
            return [rebase(item) for item in value]
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        return value

    atomic_write_json(manifest_path, rebase(payload))
    LOGGER.info(
        "Rebased temporary component paths in %s onto %s",
        manifest_path,
        stable_root,
    )


def aggregate_ligandability_shards(
    *,
    config: WorkflowConfig,
    stage_root: Path,
) -> Path:
    """Aggregate completed accession shards and return a controlled manifest."""
    task_roots = [
        ligandability_shard_root(config, index)
        for index in range(ligandability_task_count(config))
    ]
    markers = []
    complete_roots = []
    for task_root in task_roots:
        marker = _read_marker(task_root)
        if marker is None:
            raise StageError(f"Ligandability shard has no completion marker: {task_root}")
        if marker["configuration_digest"] != config.digest:
            raise StageError(f"Ligandability shard digest mismatch: {task_root}")
        markers.append(marker)
        if marker["status"] == "COMPLETE":
            complete_roots.append(task_root)
    if not complete_roots:
        raise StageError("No ligandability shard completed")
    aggregate_root = stage_root / "generated_ligandability"
    parquet_root = aggregate_root / "tables" / "parquet"
    for dataset in sorted(LIGANDABILITY_DATASETS):
        if dataset == "asset_manifest":
            _publish_rebased_asset_manifest(
                roots=complete_roots,
                destination=parquet_root / "asset_manifest.parquet",
            )
            continue
        sources = _parquet_sources(roots=complete_roots, dataset=dataset)
        if sources:
            _copy_parquet_union(
                sources=sources,
                destination=parquet_root / f"{dataset}.parquet",
            )
    status_path = parquet_root / "accession_status.parquet"
    if not status_path.is_file():
        raise StageError(
            "Generated ligandability shards did not publish accession_status.parquet"
        )
    status_connection = duckdb.connect(":memory:")
    try:
        status_counts = {
            str(status): int(count)
            for status, count in status_connection.execute(
                "SELECT CAST(status AS VARCHAR), count(*) "
                f"FROM read_parquet({quote_literal(status_path)}) "
                "GROUP BY CAST(status AS VARCHAR)"
            ).fetchall()
        }
    except duckdb.Error as exc:
        raise StageError(
            f"Could not summarise generated accession statuses: {exc}"
        ) from exc
    finally:
        status_connection.close()
    manifest = build_ligandability_manifest(
        roots=[aggregate_root],
        output_path=aggregate_root / "provenance" / "resource_manifest.tsv",
    )
    write_tsv(
        aggregate_root / "qc" / "distributed_ligandability_summary.tsv",
        [
            {
                "configured_task_slots": len(task_roots),
                "selected_accession_count": len(_ligandability_records(config)),
                "completed_task_count": len(complete_roots),
                "successful_accession_count": status_counts.get("SUCCESS", 0),
                "missing_model_accession_count": status_counts.get(
                    "MISSING_MODEL",
                    0,
                ),
                "failed_accession_count": status_counts.get("FAILED", 0),
                "skipped_unused_slot_count": sum(
                    row["status"] == "SKIPPED_UNUSED_SLOT" for row in markers
                ),
                "maximum_concurrent_jobs": 100,
                "cores_per_task": config.analysis.ligandability.shard_threads,
                "manifest": manifest,
            }
        ],
        (
            "configured_task_slots",
            "selected_accession_count",
            "completed_task_count",
            "successful_accession_count",
            "missing_model_accession_count",
            "failed_accession_count",
            "skipped_unused_slot_count",
            "maximum_concurrent_jobs",
            "cores_per_task",
            "manifest",
        ),
    )
    return manifest


def _structural_group_rows(config: WorkflowConfig) -> list[dict[str, Any]]:
    """Return selected-pocket groups in deterministic order."""
    selected = (
        config.run_root
        / "09_ligandability"
        / "tables"
        / "selected_pockets.parquet"
    )
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            "SELECT DISTINCT cluster_id, primary_group_type, primary_group_id "
            f"FROM read_parquet({quote_literal(selected)}) "
            "ORDER BY primary_group_type, primary_group_id, cluster_id"
        ).fetchall()
    except duckdb.Error as exc:
        raise StageError(f"Could not enumerate structural-alignment groups: {exc}") from exc
    finally:
        connection.close()
    return [
        {
            "cluster_id": str(row[0]),
            "primary_group_type": str(row[1]),
            "primary_group_id": str(row[2]),
            "entity_id": f"{row[1]}:{row[2]}",
        }
        for row in rows
    ]


def _filter_parquet(
    *,
    source: Path,
    destination: Path,
    accessions: Sequence[str],
    accession_column: str,
) -> None:
    """Copy rows for selected accessions into one typed Parquet."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE requested_accessions (accession VARCHAR)")
        connection.executemany(
            "INSERT INTO requested_accessions VALUES (?)",
            [(accession,) for accession in accessions],
        )
        connection.execute(
            f"COPY (SELECT source.* FROM read_parquet({quote_literal(source)}) AS source "
            "JOIN requested_accessions AS requested ON CAST(source."
            f'"{accession_column}" AS VARCHAR) = requested.accession) '
            f"TO {quote_literal(destination)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not filter {source.name}: {exc}") from exc
    finally:
        connection.close()


def _prepare_structural_task_inputs(
    *,
    config: WorkflowConfig,
    group: Mapping[str, Any],
    destination: Path,
) -> dict[str, Path]:
    """Create one group's immutable structural-alignment inputs."""
    destination.mkdir(parents=True, exist_ok=True)
    stage09 = config.run_root / "09_ligandability" / "tables"
    selected_source = stage09 / "selected_pockets.parquet"
    selected_path = destination / "selected_pockets.parquet"
    connection = duckdb.connect(":memory:")
    try:
        parameters = [
            group["cluster_id"],
            group["primary_group_type"],
            group["primary_group_id"],
        ]
        connection.execute(
            f"COPY (SELECT * FROM read_parquet({quote_literal(selected_source)}) "
            "WHERE CAST(cluster_id AS VARCHAR) = ? "
            "AND CAST(primary_group_type AS VARCHAR) = ? "
            "AND CAST(primary_group_id AS VARCHAR) = ?) "
            f"TO {quote_literal(selected_path)} (FORMAT PARQUET, COMPRESSION ZSTD)",
            parameters,
        )
        accessions = [
            str(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT candidate_accession FROM read_parquet("
                f"{quote_literal(selected_path)}) ORDER BY candidate_accession"
            ).fetchall()
        ]
    except duckdb.Error as exc:
        raise StageError(
            f"Could not prepare selected pockets for {group['entity_id']}: {exc}"
        ) from exc
    finally:
        connection.close()
    if not accessions:
        raise StageError(f"Structural group contains no selected accessions: {group['entity_id']}")
    mappings = destination / "pocket_residue_mappings.parquet"
    coordinates = destination / "pocket_sequence_coordinates.parquet"
    ranked_pockets = destination / "ranked_member_pockets.parquet"
    ranked_coordinates = (
        destination / "ranked_pocket_sequence_coordinates.parquet"
    )
    assets = destination / "asset_manifest.parquet"
    ranked_pocket_source = stage09 / "ranked_member_pockets.parquet"
    if not ranked_pocket_source.is_file():
        ranked_pocket_source = selected_source
        LOGGER.warning(
            "Ranked member pockets are unavailable; using strict rank-one "
            "pockets for backward-compatible structural analysis"
        )
    _filter_parquet(
        source=ranked_pocket_source,
        destination=ranked_pockets,
        accessions=accessions,
        accession_column="candidate_accession",
    )
    _filter_parquet(
        source=stage09 / "reused_pocket_residue_mappings.parquet",
        destination=mappings,
        accessions=accessions,
        accession_column="accession",
    )
    _filter_parquet(
        source=stage09 / "pocket_sequence_coordinates.parquet",
        destination=coordinates,
        accessions=accessions,
        accession_column="candidate_accession",
    )
    ranked_coordinate_source = (
        stage09 / "ranked_pocket_sequence_coordinates.parquet"
    )
    if not ranked_coordinate_source.is_file():
        ranked_coordinate_source = (
            stage09 / "pocket_sequence_coordinates.parquet"
        )
    _filter_parquet(
        source=ranked_coordinate_source,
        destination=ranked_coordinates,
        accessions=accessions,
        accession_column="candidate_accession",
    )
    _filter_parquet(
        source=stage09 / "reused_asset_manifest.parquet",
        destination=assets,
        accessions=accessions,
        accession_column="accession",
    )
    return {
        "selected_pockets": selected_path,
        "ranked_pockets": ranked_pockets,
        "pocket_residue_mappings": mappings,
        "pocket_sequence_coordinates": coordinates,
        "ranked_pocket_sequence_coordinates": ranked_coordinates,
        "asset_manifest": assets,
    }


def run_structural_alignment_shard(
    *,
    config: WorkflowConfig,
    task_index: int,
) -> dict[str, Any]:
    """Run or reuse one evolutionary-group structural-alignment shard."""
    if task_index < 0 or task_index >= structural_alignment_task_count(config):
        raise StageError(
            f"Structural-alignment task index is outside the configured range: {task_index}"
        )
    groups = _structural_group_rows(config)
    task_root = structural_alignment_shard_root(config, task_index)
    entity_id = groups[task_index]["entity_id"] if task_index < len(groups) else ""
    if _validate_reusable_marker(
        root=task_root,
        config=config,
        task_kind="structural_alignment",
        task_index=task_index,
        entity_id=entity_id,
    ):
        return {
            "status": "reused",
            "task_index": task_index,
            "marker": str(_marker_path(task_root)),
        }
    _archive_partial(task_root)
    task_root.parent.mkdir(parents=True, exist_ok=True)
    staging = task_root.parent / f".{task_root.name}.running.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    output_directory = staging / "component_output"
    if task_index >= len(groups):
        _publish_marker(
            root=staging,
            config=config,
            task_kind="structural_alignment",
            task_index=task_index,
            status="SKIPPED_UNUSED_SLOT",
            entity_id="",
            output_directory=output_directory,
        )
        os.replace(staging, task_root)
        return {
            "status": "skipped_unused_slot",
            "task_index": task_index,
            "marker": str(_marker_path(task_root)),
        }
    group = groups[task_index]
    inputs = _prepare_structural_task_inputs(
        config=config,
        group=group,
        destination=staging / "inputs",
    )
    settings = config.analysis.structural_alignment
    argv = (
        "conda",
        "run",
        "--no-capture-output",
        "--name",
        settings.conda_environment,
        "e3-structure-align",
        "run",
        "--selected-pockets",
        str(inputs["selected_pockets"]),
        "--ranked-pockets",
        str(inputs["ranked_pockets"]),
        "--pocket-residue-mappings",
        str(inputs["pocket_residue_mappings"]),
        "--pocket-sequence-coordinates",
        str(inputs["pocket_sequence_coordinates"]),
        "--ranked-pocket-sequence-coordinates",
        str(inputs["ranked_pocket_sequence_coordinates"]),
        "--asset-manifest",
        str(inputs["asset_manifest"]),
        "--output-dir",
        str(output_directory),
        "--usalign-executable",
        settings.usalign_executable,
        "--tmalign-executable",
        settings.tmalign_executable,
        "--threads",
        str(settings.shard_threads),
        "--member-pocket-top-k",
        str(settings.member_pocket_top_k),
        "--distance-threshold-angstrom",
        str(settings.distance_threshold_angstrom),
        "--maximum-centroid-distance-angstrom",
        str(settings.maximum_centroid_distance_angstrom),
        "--minimum-pocket-overlap-fraction",
        str(settings.minimum_pocket_overlap_fraction),
        "--minimum-global-tm-score",
        str(settings.minimum_global_tm_score),
        "--minimum-structural-residue-match-fraction",
        str(settings.minimum_structural_residue_match_fraction),
        "--minimum-structural-chemical-group-conservation",
        str(settings.minimum_structural_chemical_group_conservation),
        "--minimum-group-support-fraction",
        str(settings.minimum_group_support_fraction),
        "--resume",
    )
    try:
        _run_component(
            argv=argv,
            log_path=staging / "component.log",
            working_directory=config.project_root,
        )
        component_manifest = (
            output_directory / "provenance" / "run_manifest.json"
        )
        if component_manifest.is_file():
            _rebase_component_manifest(
                manifest_path=component_manifest,
                temporary_root=staging,
                stable_root=task_root,
            )
        else:
            LOGGER.warning(
                "Legacy structural component produced no JSON run manifest: %s",
                output_directory,
            )
        _publish_marker(
            root=staging,
            config=config,
            task_kind="structural_alignment",
            task_index=task_index,
            status="COMPLETE",
            entity_id=group["entity_id"],
            output_directory=task_root / "component_output",
        )
        os.replace(staging, task_root)
    except BaseException:
        failed = task_root.parent / "failed"
        failed.mkdir(parents=True, exist_ok=True)
        os.replace(staging, failed / f"{task_root.name}.{uuid.uuid4().hex}")
        raise
    return {
        "status": "complete",
        "task_index": task_index,
        "entity_id": group["entity_id"],
        "marker": str(_marker_path(task_root)),
    }


def _table_records(path: Path) -> list[dict[str, Any]]:
    """Read one Parquet table into bounded Python records for HTML output."""
    connection = duckdb.connect(":memory:")
    try:
        cursor = connection.execute(
            f"SELECT * FROM read_parquet({quote_literal(path)})"
        )
        fields = [str(item[0]) for item in cursor.description]
        return [dict(zip(fields, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def _validate_structural_summary_evidence(
    *,
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Require at least one real model-resolved structural comparison group.

    Args:
        summaries: Aggregated group-level structural summary records.

    Returns:
        Counts used by the Stage 09b validation report.

    Raises:
        StageError: If the summaries omit required counts or contain no
            model-resolved group capable of pairwise comparison.
    """
    required = {"selected_accession_count", "model_available_accession_count"}
    selected_total = 0
    resolved_total = 0
    selected_comparable_groups = 0
    resolved_comparable_groups = 0
    for row in summaries:
        missing = sorted(required.difference(row))
        if missing:
            raise StageError(
                "Structural summary is missing validation columns: "
                + ", ".join(missing)
            )
        try:
            selected = int(row["selected_accession_count"])
            resolved = int(row["model_available_accession_count"])
        except (TypeError, ValueError) as exc:
            raise StageError("Structural summary contains invalid model counts") from exc
        if selected < 0 or resolved < 0 or resolved > selected:
            raise StageError("Structural summary contains inconsistent model counts")
        selected_total += selected
        resolved_total += resolved
        selected_comparable_groups += selected >= 2
        resolved_comparable_groups += resolved >= 2
    if selected_total > 0 and resolved_total == 0:
        raise StageError(
            "Stage 09b resolved zero structural models despite selected Stage 09 "
            "accessions; check published asset-manifest paths"
        )
    if selected_comparable_groups > 0 and resolved_comparable_groups == 0:
        raise StageError(
            "Stage 09b resolved no evolutionary group with at least two structural "
            "models; no pairwise structural comparison is possible"
        )
    return {
        "selected_accession_instance_count": selected_total,
        "resolved_model_instance_count": resolved_total,
        "selected_comparable_group_count": selected_comparable_groups,
        "resolved_comparable_group_count": resolved_comparable_groups,
    }


def _write_structural_summary_html(
    *,
    path: Path,
    summaries: Sequence[Mapping[str, Any]],
) -> None:
    """Write a self-contained aggregate structural summary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in summaries:
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(record.get(field, '')))}</td>"
                for field in (
                    "primary_group_id",
                    "reference_accession",
                    "aligned_species_count",
                    "group_support_fraction",
                    "mean_minimum_tm_score",
                    "mean_pocket_overlap_fraction",
                    "alignment_status",
                )
            )
            + "</tr>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Structural alignment summary</title>
<style>
body{{font-family:Arial,sans-serif;margin:2rem;color:#172033}}h1{{color:#17365d}}
.note{{background:#eef5fb;border-left:5px solid #2f75b5;padding:1rem}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}
th{{background:#17365d;color:white}}
th,td{{padding:.45rem;text-align:left;border-bottom:1px solid #d8dee8}}
tr:nth-child(even){{background:#f7f9fc}}
</style></head><body><h1>Distributed structural alignment summary</h1>
<p class="note">One row represents one distinct evolutionary candidate group. US-align and
TM-align evidence remains computational and does not establish binding or E3 activity.</p>
<p>Groups reported: {len(summaries)}</p>
<table><thead><tr><th>Primary group</th><th>Reference</th><th>Aligned species</th>
<th>Support fraction</th><th>Mean minimum TM-score</th><th>Mean pocket overlap</th>
<th>3D status</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
    path.write_text(document, encoding="utf-8")


def aggregate_structural_alignment_shards(
    *,
    config: WorkflowConfig,
    stage_root: Path,
) -> None:
    """Aggregate completed group shards into the Stage-09b public contract."""
    task_roots = [
        structural_alignment_shard_root(config, index)
        for index in range(structural_alignment_task_count(config))
    ]
    markers = []
    complete_roots = []
    for task_root in task_roots:
        marker = _read_marker(task_root)
        if marker is None:
            raise StageError(f"Structural-alignment shard has no marker: {task_root}")
        if marker["configuration_digest"] != config.digest:
            raise StageError(f"Structural-alignment shard digest mismatch: {task_root}")
        markers.append(marker)
        if marker["status"] == "COMPLETE":
            complete_roots.append(task_root)
    output_root = stage_root / "structural_alignment"
    tables = output_root / "tables"
    published_datasets = []
    for dataset in STRUCTURAL_DATASETS:
        sources = [
            root / "component_output" / "tables" / f"{dataset}.parquet"
            for root in complete_roots
        ]
        sources = [source for source in sources if source.is_file()]
        if not sources:
            if dataset.startswith("structural_pocket_sensitivity_"):
                LOGGER.warning(
                    "Legacy structural shards did not produce optional "
                    "sensitivity dataset %s",
                    dataset,
                )
                continue
            raise StageError(f"No structural shard produced {dataset}.parquet")
        destination = tables / f"{dataset}.parquet"
        _copy_parquet_union(sources=sources, destination=destination)
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(
                f"COPY (SELECT * FROM read_parquet({quote_literal(destination)})) "
                f"TO {quote_literal(tables / f'{dataset}.tsv')} "
                "(FORMAT CSV, DELIMITER '\t', HEADER TRUE, QUOTE '\"')"
            )
        finally:
            connection.close()
        published_datasets.append(dataset)
    summaries = _table_records(tables / "structural_alignment_summary.parquet")
    evidence_counts = _validate_structural_summary_evidence(summaries=summaries)
    _write_structural_summary_html(
        path=output_root / "reports" / "structural_alignment_summary.html",
        summaries=summaries,
    )
    interactive_rows = []
    for task_root in complete_roots:
        marker = _read_marker(task_root)
        if marker is None:
            continue
        source_directory = (
            task_root
            / "component_output"
            / "interactive"
        )
        source = source_directory / "structural_alignment_browser.html"
        if source.is_file():
            slug = marker["entity_id"].replace(":", "__").replace("/", "_")
            destination = output_root / "interactive" / "groups" / slug
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_directory, destination, dirs_exist_ok=True)
            interactive_rows.append(
                (
                    marker["entity_id"],
                    f"groups/{slug}/structural_alignment_browser.html",
                )
            )
    browser_rows = "".join(
        f'<li><a href="{html.escape(relative)}">{html.escape(entity)}</a></li>'
        for entity, relative in interactive_rows
    )
    browser = output_root / "interactive" / "structural_alignment_browser.html"
    browser.parent.mkdir(parents=True, exist_ok=True)
    browser.write_text(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Structural alignment browsers</title></head><body>"
        "<h1>Structural alignment group browsers</h1><ul>"
        f"{browser_rows}</ul></body></html>",
        encoding="utf-8",
    )
    write_tsv(
        output_root / "qc" / "structural_alignment_validation.tsv",
        [
            {
                "configured_task_slots": len(task_roots),
                "completed_group_task_count": len(complete_roots),
                "skipped_unused_slot_count": sum(
                    row["status"] == "SKIPPED_UNUSED_SLOT" for row in markers
                ),
                "summary_group_count": len(summaries),
                **evidence_counts,
                "maximum_concurrent_jobs": 100,
                "cores_per_task": config.analysis.structural_alignment.shard_threads,
                "status": "PASS",
            }
        ],
        (
            "configured_task_slots",
            "completed_group_task_count",
            "skipped_unused_slot_count",
            "summary_group_count",
            "selected_accession_instance_count",
            "resolved_model_instance_count",
            "selected_comparable_group_count",
            "resolved_comparable_group_count",
            "maximum_concurrent_jobs",
            "cores_per_task",
            "status",
        ),
    )
    input_inventory = [
        {
            "task_index": int(row["task_index"]),
            "entity_id": row["entity_id"],
            "marker": str(
                _marker_path(
                    structural_alignment_shard_root(
                        config,
                        int(row["task_index"]),
                    )
                )
            ),
        }
        for row in markers
    ]
    published_tables = (
        config.run_root
        / "09b_structural_alignment"
        / "structural_alignment"
        / "tables"
    )
    atomic_write_json(
        output_root / "provenance" / "run_manifest.json",
        {
            "status": "complete",
            "configuration_digest": config.digest,
            "finished_at_utc": utc_now(),
            "task_count": len(complete_roots),
            "summary_group_count": len(summaries),
            "structural_evidence_counts": evidence_counts,
            "datasets": {
                dataset: {
                    "path": str(
                        published_tables / f"{dataset}.parquet"
                    ),
                    "sha256": sha256_file(tables / f"{dataset}.parquet"),
                }
                for dataset in published_datasets
            },
            "shards": input_inventory,
        },
    )
