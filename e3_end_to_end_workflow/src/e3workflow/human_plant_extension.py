"""Separate, restartable human-and-plant structural extension.

The extension consumes a completed plant-only production run. It never mutates
that run: human ligandability evidence, combined pocket alignments, structural
superpositions and the portable review bundle are published below a distinct
output root.
"""

from __future__ import annotations

import html
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from e3workflow.config import WorkflowConfig, load_config
from e3workflow.distributed import (
    STRUCTURAL_DATASETS,
    TASK_MARKER_FIELDS,
    _copy_parquet_union,
    _filter_parquet,
    _parquet_sources,
    _publish_rebased_asset_manifest,
    _rebase_component_manifest,
    _run_component,
    _table_records,
)
from e3workflow.errors import StageError
from e3workflow.io_utils import (
    atomic_write_json,
    read_tsv,
    sha256_file,
    utc_now,
    write_tsv,
)
from e3workflow.ligandability import (
    POCKET_CONSERVATION_COLUMN_TYPES,
    POCKET_CONSERVATION_FIELDS,
    POCKET_MEMBER_FIELDS,
    POCKET_SEQUENCE_COORDINATE_FIELDS,
    RANKED_POCKET_FIELDS,
    SELECTED_POCKET_FIELDS,
    _copy_reused_tables,
    _copy_strict_selected_pockets,
    _load_sequences,
    _read_query,
    build_selected_pockets,
    map_pocket_residues_to_fasta,
    measure_pocket_conservation,
)
from e3workflow.resources import (
    LIGANDABILITY_DATASETS,
    build_ligandability_manifest,
    read_resource_manifest,
)
from e3workflow.tabular import copy_query_to_parquet, quote_literal, write_records

LOGGER = logging.getLogger("e3workflow.human_plant_extension")
HUMAN_SPECIES = "Homo_sapiens"

HUMAN_TASK_FIELDS = (
    "task_index",
    "accession",
    "parsed_entry",
    "raw_identifier",
    "sequence_length",
    "sequence_sha256",
    "protein_sequence",
)

HUMAN_CONTEXT_FIELDS = (
    "review_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "species_column",
    "accession",
    "parsed_entry",
    "raw_identifier",
    "sequence_length",
    "sequence_sha256",
    "protein_sequence",
)

GROUP_FIELDS = (
    "group_task_index",
    "review_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "reference_accession",
    "human_accession_count",
)


def _resolve_first(*, root: Path, candidates: Sequence[str], label: str) -> Path:
    """Resolve the first existing production-contract path.

    Args:
        root: Root directory containing the candidate paths.
        candidates: Relative paths in descending order of preference.
        label: Human-readable description used in validation errors.

    Returns:
        The first candidate that exists as a file, resolved to an absolute path.

    Raises:
        StageError: If none of the candidate files exists below ``root``.
    """
    present = [root / candidate for candidate in candidates if (root / candidate).is_file()]
    if not present:
        raise StageError(
            f"Could not find {label} below {root}; expected one of: "
            + "; ".join(candidates)
        )
    return present[0].resolve()


def _require_columns(*, path: Path, required: Sequence[str]) -> set[str]:
    """Return a Parquet schema after requiring the named columns.

    Args:
        path: Parquet file to inspect.
        required: Column names that must be present.

    Returns:
        All column names in the Parquet schema.

    Raises:
        StageError: If the Parquet file cannot be inspected or lacks a required column.
    """
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({quote_literal(path)})"
        ).fetchall()
    except duckdb.Error as exc:
        raise StageError(f"Could not inspect {path}: {exc}") from exc
    finally:
        connection.close()
    columns = {str(row[0]) for row in rows}
    missing = sorted(set(required).difference(columns))
    if missing:
        raise StageError(f"{path.name} is missing columns: {', '.join(missing)}")
    return columns


def _validate_sequence_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    """Require complete, checksum-consistent exact protein sequences.

    Args:
        rows: Human sequence records to validate.

    Raises:
        StageError: If no rows are supplied or a sequence record is incomplete,
            internally inconsistent or checksum-invalid.
    """
    import hashlib

    if not rows:
        raise StageError("No exact human HOG-member accessions were selected")
    for row in rows:
        accession = str(row.get("accession") or "").strip()
        sequence = str(row.get("protein_sequence") or "").strip()
        digest = str(row.get("sequence_sha256") or "").strip().lower()
        try:
            length = int(row.get("sequence_length"))
        except (TypeError, ValueError) as exc:
            raise StageError(f"Invalid sequence length for {accession!r}") from exc
        if not accession or not sequence or length != len(sequence):
            raise StageError(f"Incomplete exact human sequence for {accession!r}")
        observed = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if observed != digest:
            raise StageError(f"Human sequence checksum mismatch for {accession}")


def prepare_human_plant_extension(
    *,
    parent_config_path: Path,
    output_root: Path,
    review_limit: int = 200,
    human_species: str = HUMAN_SPECIES,
) -> dict[str, Any]:
    """Materialise exact human tasks and preserved plant-reference groups.

    Args:
        parent_config_path: Immutable completed plant-workflow configuration.
        output_root: Separate human-and-plant extension output root.
        review_limit: Maximum original final evolutionary rank to include.
        human_species: Species label used to select exact human group members.

    Returns:
        Preparation metadata, including task and qualifying-group counts.

    Raises:
        StageError: If the review limit or a required production authority is
            invalid, or if exact human sequences and plant references cannot be
            prepared consistently.
    """
    if not 1 <= review_limit <= 500:
        raise StageError("review_limit must be between 1 and 500")
    config = load_config(parent_config_path)
    run_root = config.run_root
    destination = Path(output_root).expanduser().resolve()
    manifests = destination / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    structural_accessions = _resolve_first(
        root=run_root,
        candidates=(
            "08_shortlist_gate/tables/structural_analysis_accessions.parquet",
        ),
        label="plant structural-accession authority",
    )
    group_sequences = _resolve_first(
        root=run_root,
        candidates=(
            "05_orthology/orthology/tables/candidate_group_member_sequences.parquet",
            "05_orthology/tables/candidate_group_member_sequences.parquet",
        ),
        label="candidate-group sequence authority",
    )
    shortlist = _resolve_first(
        root=run_root,
        candidates=(
            "10_integrated_resource/final_results/top_computational_review_shortlist.parquet",
            "10_integrated_resource/final_results/top_computational_review_shortlist.tsv",
            "10_integrated_resource/final_results/top_50_computational_review_shortlist.parquet",
        ),
        label="final evolutionary shortlist",
    )
    structural_summary = _resolve_first(
        root=run_root,
        candidates=(
            "09b_structural_alignment/structural_alignment/tables/"
            "structural_alignment_summary.parquet",
        ),
        label="plant structural summary",
    )
    _require_columns(
        path=structural_accessions,
        required=("cluster_id", "primary_group_type", "primary_group_id"),
    )
    _require_columns(
        path=group_sequences,
        required=(
            "cluster_id",
            "record_type",
            "group_id",
            "species",
            "parsed_accession",
            "protein_sequence",
            "sequence_length",
            "sequence_sha256",
        ),
    )
    connection = duckdb.connect(":memory:")
    try:
        shortlist_reader = (
            f"read_parquet({quote_literal(shortlist)})"
            if shortlist.suffix == ".parquet"
            else f"read_csv_auto({quote_literal(shortlist)}, delim='\\t', header=true)"
        )
        contexts = connection.execute(
            f"""
            WITH ranked AS (
              SELECT TRY_CAST(final_evolutionary_rank AS BIGINT) AS review_rank,
                     CAST(lead_cluster_id AS VARCHAR) AS cluster_id,
                     CAST(primary_group_type AS VARCHAR) AS primary_group_type,
                     CAST(primary_group_id AS VARCHAR) AS primary_group_id
              FROM {shortlist_reader}
              WHERE TRY_CAST(final_evolutionary_rank AS BIGINT) <= ?
            ), selected_groups AS (
              SELECT DISTINCT r.*
              FROM ranked r
              INNER JOIN read_parquet({quote_literal(structural_accessions)}) a
                ON CAST(a.cluster_id AS VARCHAR) = r.cluster_id
               AND CAST(a.primary_group_type AS VARCHAR) = r.primary_group_type
               AND CAST(a.primary_group_id AS VARCHAR) = r.primary_group_id
            )
            SELECT g.review_rank, g.cluster_id, g.primary_group_type,
                   g.primary_group_id, CAST(m.species AS VARCHAR) AS species_column,
                   trim(CAST(m.parsed_accession AS VARCHAR)) AS accession,
                   coalesce(CAST(m.parsed_entry AS VARCHAR), '') AS parsed_entry,
                   coalesce(CAST(m.raw_identifier AS VARCHAR), '') AS raw_identifier,
                   TRY_CAST(m.sequence_length AS BIGINT) AS sequence_length,
                   lower(CAST(m.sequence_sha256 AS VARCHAR)) AS sequence_sha256,
                   CAST(m.protein_sequence AS VARCHAR) AS protein_sequence
            FROM selected_groups g
            INNER JOIN read_parquet({quote_literal(group_sequences)}) m
              ON CAST(m.cluster_id AS VARCHAR) = g.cluster_id
             AND CAST(m.record_type AS VARCHAR) = g.primary_group_type
             AND CAST(m.group_id AS VARCHAR) = g.primary_group_id
            WHERE CAST(m.species AS VARCHAR) = ?
              AND trim(coalesce(CAST(m.parsed_accession AS VARCHAR), '')) != ''
            QUALIFY row_number() OVER (
              PARTITION BY g.cluster_id, g.primary_group_type, g.primary_group_id,
                           trim(CAST(m.parsed_accession AS VARCHAR))
              ORDER BY CAST(m.raw_identifier AS VARCHAR)
            ) = 1
            ORDER BY g.review_rank, g.primary_group_id, accession
            """,
            [review_limit, human_species],
        ).fetchall()
        fields = [str(item[0]) for item in connection.description]
        context_rows = [dict(zip(fields, row)) for row in contexts]
        _validate_sequence_rows(context_rows)
        accessions: dict[str, dict[str, Any]] = {}
        for row in context_rows:
            accession = str(row["accession"])
            existing = accessions.get(accession)
            if existing and existing["sequence_sha256"] != row["sequence_sha256"]:
                raise StageError(f"Conflicting human sequences for {accession}")
            accessions.setdefault(accession, row)
        task_rows = []
        for task_index, accession in enumerate(sorted(accessions)):
            row = accessions[accession]
            task_rows.append(
                {
                    "task_index": task_index,
                    **{field: row[field] for field in HUMAN_TASK_FIELDS[1:]},
                }
            )
        connection.execute(
            "CREATE TEMP TABLE human_contexts ("
            "review_rank BIGINT, cluster_id VARCHAR, primary_group_type VARCHAR, "
            "primary_group_id VARCHAR, species_column VARCHAR, accession VARCHAR, "
            "parsed_entry VARCHAR, raw_identifier VARCHAR, sequence_length BIGINT, "
            "sequence_sha256 VARCHAR, protein_sequence VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO human_contexts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(row[field] for field in HUMAN_CONTEXT_FIELDS) for row in context_rows],
        )
        connection.execute(
            "CREATE TEMP TABLE qualifying_groups AS SELECT DISTINCT "
            "review_rank, cluster_id, primary_group_type, primary_group_id "
            "FROM human_contexts"
        )
        reference_rows = connection.execute(
            f"""
            WITH grouped AS (
              SELECT q.review_rank, q.cluster_id, q.primary_group_type,
                     q.primary_group_id,
                     min(CAST(s.reference_accession AS VARCHAR))
                       AS reference_accession,
                     count(DISTINCT c.accession) AS human_accession_count
              FROM qualifying_groups q
              INNER JOIN read_parquet({quote_literal(structural_summary)}) s
                ON CAST(s.cluster_id AS VARCHAR) = q.cluster_id
               AND CAST(s.primary_group_type AS VARCHAR) = q.primary_group_type
               AND CAST(s.primary_group_id AS VARCHAR) = q.primary_group_id
              INNER JOIN human_contexts c
                ON CAST(c.cluster_id AS VARCHAR) = q.cluster_id
               AND CAST(c.primary_group_type AS VARCHAR) = q.primary_group_type
               AND CAST(c.primary_group_id AS VARCHAR) = q.primary_group_id
              WHERE trim(coalesce(CAST(s.reference_accession AS VARCHAR), '')) != ''
              GROUP BY q.review_rank, q.cluster_id, q.primary_group_type,
                       q.primary_group_id
              HAVING count(DISTINCT CAST(s.reference_accession AS VARCHAR)) = 1
            )
            SELECT row_number() OVER (
                     ORDER BY review_rank, primary_group_id
                   ) - 1 AS group_task_index,
                   review_rank, cluster_id, primary_group_type, primary_group_id,
                   reference_accession, human_accession_count
            FROM grouped
            ORDER BY review_rank, primary_group_id
            """
        ).fetchall()
        reference_fields = [str(item[0]) for item in connection.description]
        group_rows = [dict(zip(reference_fields, row)) for row in reference_rows]
        if len(group_rows) != len(
            {(row["cluster_id"], row["primary_group_type"], row["primary_group_id"])
             for row in context_rows}
        ):
            raise StageError(
                "One or more human-containing groups lack a preserved plant reference"
            )
        connection.execute(
            "CREATE TEMP TABLE qualifying_keys AS SELECT DISTINCT cluster_id, "
            "primary_group_type, primary_group_id FROM qualifying_groups"
        )
        review_shortlist = manifests / "review_shortlist.parquet"
        copy_query_to_parquet(
            connection=connection,
            query=(
                f"SELECT s.* FROM {shortlist_reader} s INNER JOIN qualifying_keys q "
                "ON CAST(s.lead_cluster_id AS VARCHAR) = q.cluster_id "
                "AND CAST(s.primary_group_type AS VARCHAR) = q.primary_group_type "
                "AND CAST(s.primary_group_id AS VARCHAR) = q.primary_group_id "
                "ORDER BY TRY_CAST(s.final_evolutionary_rank AS BIGINT)"
            ),
            path=review_shortlist,
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not prepare human-and-plant extension: {exc}") from exc
    finally:
        connection.close()
    write_records(
        tsv_path=manifests / "human_accession_tasks.tsv",
        parquet_path=manifests / "human_accession_tasks.parquet",
        fieldnames=HUMAN_TASK_FIELDS,
        records=task_rows,
        column_types={"task_index": "BIGINT", "sequence_length": "BIGINT"},
    )
    write_records(
        tsv_path=manifests / "human_group_members.tsv",
        parquet_path=manifests / "human_group_members.parquet",
        fieldnames=HUMAN_CONTEXT_FIELDS,
        records=context_rows,
        column_types={"review_rank": "BIGINT", "sequence_length": "BIGINT"},
    )
    write_records(
        tsv_path=manifests / "groups.tsv",
        parquet_path=manifests / "groups.parquet",
        fieldnames=GROUP_FIELDS,
        records=group_rows,
        column_types={
            "group_task_index": "BIGINT",
            "review_rank": "BIGINT",
            "human_accession_count": "BIGINT",
        },
    )
    payload = {
        "status": "complete",
        "parent_config": str(Path(parent_config_path).expanduser().resolve()),
        "parent_run_root": str(run_root),
        "review_limit": review_limit,
        "human_species": human_species,
        "human_accession_task_count": len(task_rows),
        "human_group_member_count": len(context_rows),
        "qualifying_group_count": len(group_rows),
        "created_at_utc": utc_now(),
        "inputs": {
            "structural_accessions": str(structural_accessions),
            "group_sequences": str(group_sequences),
            "shortlist": str(shortlist),
            "structural_summary": str(structural_summary),
        },
    }
    atomic_write_json(manifests / "preparation_manifest.json", payload)
    return payload


def _task_record(*, path: Path, task_index: int) -> dict[str, str]:
    """Return one unique task-manifest row.

    Args:
        path: Tab-separated task manifest.
        task_index: Zero-based task index to retrieve.

    Returns:
        The unique matching task record.

    Raises:
        StageError: If the index column is missing or the requested index is
            absent or duplicated.
    """
    fields, rows = read_tsv(path)
    if "task_index" not in fields:
        raise StageError(f"Task manifest lacks task_index: {path}")
    selected = [row for row in rows if int(row["task_index"]) == task_index]
    if len(selected) != 1:
        raise StageError(f"Task index {task_index} is absent or duplicated in {path}")
    return selected[0]


def _write_task_marker(
    *,
    root: Path,
    task_kind: str,
    task_index: int,
    configuration_digest: str,
    entity_id: str,
    output_directory: Path,
) -> Path:
    """Publish one stable extension task marker.

    Args:
        root: Stable task output directory.
        task_kind: Component task category.
        task_index: Zero-based task index.
        configuration_digest: Digest of all task input authorities.
        entity_id: Stable biological entity identifier.
        output_directory: Published component output directory.

    Returns:
        Path to the tab-separated task-completion marker.
    """
    marker = root / "task_complete.tsv"
    write_tsv(
        marker,
        [
            {
                "task_kind": task_kind,
                "task_index": task_index,
                "status": "COMPLETE",
                "configuration_digest": configuration_digest,
                "entity_id": entity_id,
                "output_directory": output_directory,
                "finished_at_utc": utc_now(),
            }
        ],
        TASK_MARKER_FIELDS,
    )
    return marker


def run_human_ligandability_task(
    *,
    parent_config_path: Path,
    task_manifest: Path,
    output_root: Path,
    task_index: int,
    component_config: Path,
    conda_environment: str,
) -> Path:
    """Run one exact human accession through the ligandability package.

    Args:
        parent_config_path: Immutable completed plant-workflow configuration.
        task_manifest: Prepared human accession task manifest.
        output_root: Separate human-and-plant extension output root.
        task_index: Zero-based human accession task index.
        component_config: Ligandability component configuration.
        conda_environment: Conda environment containing ``e3-ligandability``.

    Returns:
        Path to the stable task-completion marker.

    Raises:
        StageError: If the task is invalid or the component produces no run manifest.
    """
    config = load_config(parent_config_path)
    row = _task_record(path=task_manifest, task_index=task_index)
    task_root = (
        Path(output_root).expanduser().resolve()
        / "work_cache"
        / "human_ligandability"
        / f"task_{task_index:04d}"
    )
    component_source = Path(component_config).expanduser().resolve()
    digest = _task_digest(
        Path(task_manifest).expanduser().resolve(),
        component_source,
        parent_digest=config.digest,
    )
    if _reusable_extension_task(
        root=task_root,
        task_kind="human_ligandability",
        task_index=task_index,
        entity_id=row["accession"],
        configuration_digest=digest,
    ):
        return task_root / "task_complete.tsv"
    if task_root.exists():
        archived = task_root.parent / "failed"
        archived.mkdir(parents=True, exist_ok=True)
        os.replace(task_root, archived / f"{task_root.name}.{uuid.uuid4().hex}")
    staging = task_root.parent / f".{task_root.name}.running.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    output_directory = staging / "component_output"
    input_path = staging / "accession.tsv"
    write_tsv(input_path, [row], tuple(row))
    try:
        _run_component(
            argv=(
                "conda",
                "run",
                "--no-capture-output",
                "--name",
                conda_environment,
                "e3-ligandability",
                "run",
                "--input",
                str(input_path),
                "--output-dir",
                str(output_directory),
                "--config",
                str(component_source),
                "--git-repository",
                str(config.project_root),
            ),
            log_path=staging / "component.log",
            working_directory=config.project_root,
        )
        component_manifest = output_directory / "provenance" / "run_manifest.json"
        if not component_manifest.is_file():
            raise StageError("Human ligandability task produced no run manifest")
        _rebase_component_manifest(
            manifest_path=component_manifest,
            temporary_root=staging,
            stable_root=task_root,
        )
        _write_task_marker(
            root=staging,
            task_kind="human_ligandability",
            task_index=task_index,
            configuration_digest=digest,
            entity_id=row["accession"],
            output_directory=task_root / "component_output",
        )
        os.replace(staging, task_root)
    except BaseException:
        failed = task_root.parent / "failed"
        failed.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            os.replace(staging, failed / f"{task_root.name}.{uuid.uuid4().hex}")
        raise
    return task_root / "task_complete.tsv"


def _write_parquet_as_tsv(path: Path) -> Path:
    """Publish a tab-separated companion for one Parquet table.

    Args:
        path: Source Parquet table.

    Returns:
        Path to the tab-separated companion file.

    Raises:
        StageError: If DuckDB cannot convert the source table.
    """
    destination = path.with_suffix(".tsv")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"COPY (SELECT * FROM read_parquet({quote_literal(path)})) "
            f"TO {quote_literal(destination)} "
            "(FORMAT CSV, DELIMITER '\\t', HEADER TRUE, QUOTE '\"')"
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not publish TSV companion for {path}: {exc}") from exc
    finally:
        connection.close()
    return destination


def _union_distinct_assets(*, sources: Sequence[Path], destination: Path) -> None:
    """Publish one model asset per accession from plant and human manifests.

    Ligandability asset manifests can contain a structure model together with
    auxiliary PAE and confidence JSON files. Structural alignment consumes
    only PDB, CIF and mmCIF models, so auxiliary assets must not participate in
    model-checksum conflict detection or model selection.

    Args:
        sources: Plant and human Parquet asset manifests.
        destination: Destination structural-model Parquet manifest.

    Raises:
        StageError: If no structure models are available, one accession maps
            to conflicting structure models or the tables cannot be combined.
    """
    source_sql = "[" + ", ".join(quote_literal(path) for path in sources) + "]"
    model_predicate = (
        "lower(CAST(path AS VARCHAR)) LIKE '%.pdb' OR "
        "lower(CAST(path AS VARCHAR)) LIKE '%.cif' OR "
        "lower(CAST(path AS VARCHAR)) LIKE '%.mmcif'"
    )
    connection = duckdb.connect(":memory:")
    try:
        available = connection.execute(
            f"SELECT 1 FROM read_parquet({source_sql}, union_by_name=true) "
            f"WHERE {model_predicate} LIMIT 1"
        ).fetchone()
        if available is None:
            raise StageError("Plant and human manifests contain no structure models")
        conflict = connection.execute(
            f"SELECT accession FROM read_parquet({source_sql}, union_by_name=true) "
            f"WHERE {model_predicate} "
            "GROUP BY accession HAVING count(DISTINCT sha256) > 1 LIMIT 1"
        ).fetchone()
        if conflict:
            raise StageError(f"Conflicting model assets for accession {conflict[0]}")
        copy_query_to_parquet(
            connection=connection,
            query=(
                f"SELECT * EXCLUDE (asset_rank) FROM (SELECT *, row_number() OVER ("
                "PARTITION BY accession ORDER BY sha256, path) AS asset_rank "
                f"FROM read_parquet({source_sql}, union_by_name=true) "
                f"WHERE {model_predicate}) WHERE asset_rank = 1"
            ),
            path=destination,
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not combine structure assets: {exc}") from exc
    finally:
        connection.close()


def aggregate_human_ligandability(
    *,
    parent_config_path: Path,
    task_manifest: Path,
    group_member_manifest: Path,
    group_manifest: Path,
    output_root: Path,
) -> Path:
    """Aggregate human pockets and publish combined alignment inputs.

    Args:
        parent_config_path: Immutable completed plant-workflow configuration.
        task_manifest: Prepared human accession task manifest.
        group_member_manifest: Exact human group-member manifest.
        group_manifest: Prepared human-containing group manifest.
        output_root: Separate human-and-plant extension output root.

    Returns:
        Path to the ligandability aggregate manifest.

    Raises:
        StageError: If component tasks are incomplete or their plant and human
            ligandability authorities cannot be validated and combined.
    """
    config = load_config(parent_config_path)
    root = Path(output_root).expanduser().resolve()
    _fields, tasks = read_tsv(task_manifest)
    task_roots = [
        root / "work_cache" / "human_ligandability" / f"task_{int(row['task_index']):04d}"
        for row in tasks
    ]
    missing = [path for path in task_roots if not (path / "task_complete.tsv").is_file()]
    if missing:
        raise StageError(f"Human ligandability tasks are incomplete: {missing[0]}")
    aggregate_root = root / "ligandability" / "generated_ligandability"
    parquet_root = aggregate_root / "tables" / "parquet"
    for dataset in sorted(LIGANDABILITY_DATASETS):
        if dataset == "asset_manifest":
            _publish_rebased_asset_manifest(
                roots=task_roots,
                destination=parquet_root / "asset_manifest.parquet",
            )
            continue
        sources = _parquet_sources(roots=task_roots, dataset=dataset)
        if sources:
            _copy_parquet_union(
                sources=sources,
                destination=parquet_root / f"{dataset}.parquet",
            )
    resource_manifest = build_ligandability_manifest(
        roots=[aggregate_root],
        output_path=aggregate_root / "provenance" / "resource_manifest.tsv",
    )
    resource_records = read_resource_manifest(
        path=resource_manifest,
        allowed_resource_types={"ligandability"},
        verify_checksums=True,
    )
    human_stage = root / "ligandability" / "human"
    copied = _copy_reused_tables(
        records=resource_records,
        stage_root=human_stage,
        datasets=sorted(LIGANDABILITY_DATASETS),
    )
    contexts = Path(group_member_manifest).expanduser().resolve()
    human_requested = human_stage / "tables" / "structural_analysis_accessions.parquet"
    connection = duckdb.connect(":memory:")
    try:
        copy_query_to_parquet(
            connection=connection,
            query=(
                "SELECT review_rank AS computational_rank, review_rank AS "
                "evolutionary_group_rank, cluster_id, primary_group_type, "
                "primary_group_id, accession AS candidate_accession, "
                f"species_column FROM read_parquet({quote_literal(contexts)})"
            ),
            path=human_requested,
        )
    finally:
        connection.close()
    human_ranked = human_stage / "tables" / "ranked_member_pockets.parquet"
    build_selected_pockets(
        config=config,
        structural_accessions=human_requested,
        joined_pockets=copied["joined_pockets"],
        pocket_quality=copied["pocket_quality"],
        output_path=human_ranked,
        maximum_rank=config.analysis.structural_alignment.member_pocket_top_k,
    )
    human_selected = human_stage / "tables" / "selected_pockets.parquet"
    _copy_strict_selected_pockets(
        ranked_path=human_ranked,
        output_path=human_selected,
    )
    ranked_records = _read_query(path=human_ranked)
    selected_records = _read_query(path=human_selected)
    mapping_records = _read_query(
        path=copied["pocket_residue_mappings"],
        query=(
            "SELECT accession, pocket_number, mapping_status, model_label_chain, "
            "model_label_seq_id, model_auth_chain, model_auth_seq_id, "
            "model_insertion_code, model_residue_name, model_plddt FROM source"
        ),
    )
    context_records = _read_query(path=contexts)
    sequences = {
        str(row["accession"]): str(row["protein_sequence"])
        for row in context_records
    }
    human_coordinates = map_pocket_residues_to_fasta(
        selected_records=selected_records,
        mapping_records=mapping_records,
        sequences=sequences,
    )
    human_ranked_coordinates = map_pocket_residues_to_fasta(
        selected_records=ranked_records,
        mapping_records=mapping_records,
        sequences=sequences,
    )
    human_coordinates_path = human_stage / "tables" / "pocket_sequence_coordinates.parquet"
    human_ranked_coordinates_path = (
        human_stage / "tables" / "ranked_pocket_sequence_coordinates.parquet"
    )
    write_records(
        tsv_path=human_coordinates_path.with_suffix(".tsv"),
        parquet_path=human_coordinates_path,
        fieldnames=POCKET_SEQUENCE_COORDINATE_FIELDS,
        records=human_coordinates,
    )
    write_records(
        tsv_path=human_ranked_coordinates_path.with_suffix(".tsv"),
        parquet_path=human_ranked_coordinates_path,
        fieldnames=POCKET_SEQUENCE_COORDINATE_FIELDS,
        records=human_ranked_coordinates,
    )
    for path, fields, records in (
        (human_selected.with_suffix(".tsv"), SELECTED_POCKET_FIELDS, selected_records),
        (human_ranked.with_suffix(".tsv"), RANKED_POCKET_FIELDS, ranked_records),
    ):
        write_tsv(
            path,
            [{field: row.get(field, "") for field in fields} for row in records],
            fields,
        )

    plant_tables = config.run_root / "09_ligandability" / "tables"
    combined = root / "ligandability" / "combined"
    combined_tables = combined / "tables"
    unions = {
        "selected_pockets": (
            plant_tables / "selected_pockets.parquet",
            human_selected,
        ),
        "ranked_member_pockets": (
            plant_tables / "ranked_member_pockets.parquet",
            human_ranked,
        ),
        "pocket_sequence_coordinates": (
            plant_tables / "pocket_sequence_coordinates.parquet",
            human_coordinates_path,
        ),
        "ranked_pocket_sequence_coordinates": (
            plant_tables / "ranked_pocket_sequence_coordinates.parquet",
            human_ranked_coordinates_path,
        ),
        "pocket_residue_mappings": (
            plant_tables / "reused_pocket_residue_mappings.parquet",
            copied["pocket_residue_mappings"],
        ),
    }
    for name, sources in unions.items():
        destination = combined_tables / f"{name}.parquet"
        _copy_parquet_union(sources=sources, destination=destination)
        _write_parquet_as_tsv(destination)
    assets = combined_tables / "asset_manifest.parquet"
    _union_distinct_assets(
        sources=(
            plant_tables / "reused_asset_manifest.parquet",
            copied["asset_manifest"],
        ),
        destination=assets,
    )
    _write_parquet_as_tsv(assets)
    combined_selected = _read_query(path=combined_tables / "selected_pockets.parquet")
    combined_mappings = _read_query(path=combined_tables / "pocket_residue_mappings.parquet")
    requested_accessions = {
        str(row["candidate_accession"]) for row in combined_selected
    }
    combined_sequences = _load_sequences(config=config, accessions=requested_accessions)
    if requested_accessions.difference(combined_sequences):
        missing_accession = sorted(requested_accessions.difference(combined_sequences))[0]
        raise StageError(f"Combined alignment lacks exact sequence for {missing_accession}")
    summaries, members = measure_pocket_conservation(
        config=config,
        selected_records=combined_selected,
        mapping_records=combined_mappings,
        sequences=combined_sequences,
        stage_root=combined,
    )
    write_records(
        tsv_path=combined_tables / "pocket_conservation_summary.tsv",
        parquet_path=combined_tables / "pocket_conservation_summary.parquet",
        fieldnames=POCKET_CONSERVATION_FIELDS,
        records=summaries,
        column_types=POCKET_CONSERVATION_COLUMN_TYPES,
    )
    write_records(
        tsv_path=combined_tables / "pocket_conservation_members.tsv",
        parquet_path=combined_tables / "pocket_conservation_members.parquet",
        fieldnames=POCKET_MEMBER_FIELDS,
        records=members,
    )
    group_source = Path(group_manifest).expanduser().resolve()
    reference_manifest = combined_tables / "reference_manifest.tsv"
    _group_fields, group_rows = read_tsv(group_source)
    reference_fields = (
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
        "reference_accession",
    )
    write_tsv(
        reference_manifest,
        [{field: row[field] for field in reference_fields} for row in group_rows],
        reference_fields,
    )
    payload = {
        "status": "complete",
        "human_task_count": len(tasks),
        "human_selected_pocket_count": len(selected_records),
        "combined_selected_pocket_count": len(combined_selected),
        "combined_group_count": len(summaries),
        "resource_manifest": str(resource_manifest),
        "reference_manifest": str(reference_manifest),
        "finished_at_utc": utc_now(),
    }
    manifest = root / "ligandability" / "aggregate_manifest.json"
    atomic_write_json(manifest, payload)
    return manifest


def _group_record(*, path: Path, task_index: int) -> dict[str, str]:
    """Return one unique group-task row from the prepared manifest.

    Args:
        path: Tab-separated group manifest.
        task_index: Zero-based group task index.

    Returns:
        The unique matching group record.

    Raises:
        StageError: If the index is absent, duplicated or malformed.
    """
    fields, rows = read_tsv(path)
    if "group_task_index" not in fields:
        raise StageError(f"Group manifest lacks group_task_index: {path}")
    try:
        selected = [
            row for row in rows if int(row["group_task_index"]) == task_index
        ]
    except (TypeError, ValueError) as exc:
        raise StageError(f"Group manifest contains an invalid task index: {path}") from exc
    if len(selected) != 1:
        raise StageError(
            f"Group task index {task_index} is absent or duplicated in {path}"
        )
    return selected[0]


def _filter_group_parquet(
    *,
    source: Path,
    destination: Path,
    group: Mapping[str, str],
) -> None:
    """Copy one exact evolutionary-group context into typed Parquet.

    Args:
        source: Source Parquet containing group-key columns.
        destination: Destination Parquet.
        group: Record containing cluster, group type and group identifier.

    Raises:
        StageError: If the source cannot be filtered or produces no rows.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"COPY (SELECT * FROM read_parquet({quote_literal(source)}) "
            "WHERE CAST(cluster_id AS VARCHAR) = ? "
            "AND CAST(primary_group_type AS VARCHAR) = ? "
            "AND CAST(primary_group_id AS VARCHAR) = ?) "
            f"TO {quote_literal(destination)} (FORMAT PARQUET, COMPRESSION ZSTD)",
            [
                group["cluster_id"],
                group["primary_group_type"],
                group["primary_group_id"],
            ],
        )
        row_count = connection.execute(
            f"SELECT count(*) FROM read_parquet({quote_literal(destination)})"
        ).fetchone()[0]
    except duckdb.Error as exc:
        raise StageError(
            f"Could not filter {source.name} for {group['primary_group_id']}: {exc}"
        ) from exc
    finally:
        connection.close()
    if int(row_count) < 1:
        raise StageError(
            f"Group {group['primary_group_id']} has no rows in {source.name}"
        )


def _prepare_human_plant_structural_inputs(
    *,
    combined_root: Path,
    group: Mapping[str, str],
    destination: Path,
) -> dict[str, Path]:
    """Materialise one combined group for structural superposition.

    The original plant reference is supplied separately and remains unchanged.
    Rows are filtered by the complete three-column group key so a reused protein
    accession cannot leak evidence between different evolutionary contexts.

    Args:
        combined_root: Combined ligandability output directory.
        group: Prepared group manifest record.
        destination: Immutable per-task input directory.

    Returns:
        Mapping of structural command-line input roles to files.
    """
    tables = combined_root / "tables"
    group_tables = {
        "selected_pockets": "selected_pockets.parquet",
        "ranked_pockets": "ranked_member_pockets.parquet",
        "pocket_sequence_coordinates": "pocket_sequence_coordinates.parquet",
        "ranked_pocket_sequence_coordinates": (
            "ranked_pocket_sequence_coordinates.parquet"
        ),
    }
    outputs: dict[str, Path] = {}
    for role, filename in group_tables.items():
        source = tables / filename
        if not source.is_file():
            raise StageError(f"Combined structural input is missing: {source}")
        destination_path = destination / filename
        _filter_group_parquet(
            source=source,
            destination=destination_path,
            group=group,
        )
        outputs[role] = destination_path
    selected_rows = _read_query(path=outputs["selected_pockets"])
    accessions = sorted(
        {str(row["candidate_accession"]).strip() for row in selected_rows}
    )
    if len(accessions) < 2:
        raise StageError(
            f"Combined group {group['primary_group_id']} has fewer than two "
            "selected-pocket structures"
        )
    for role, filename, accession_column in (
        (
            "pocket_residue_mappings",
            "pocket_residue_mappings.parquet",
            "accession",
        ),
        ("asset_manifest", "asset_manifest.parquet", "accession"),
    ):
        source = tables / filename
        if not source.is_file():
            raise StageError(f"Combined structural input is missing: {source}")
        destination_path = destination / filename
        _filter_parquet(
            source=source,
            destination=destination_path,
            accessions=accessions,
            accession_column=accession_column,
        )
        outputs[role] = destination_path
    reference = str(group["reference_accession"]).strip()
    if reference not in accessions:
        raise StageError(
            f"Preserved plant reference {reference} is not an eligible selected-pocket "
            f"model for {group['primary_group_id']}"
        )
    reference_manifest = destination / "reference_manifest.tsv"
    reference_fields = (
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
        "reference_accession",
    )
    write_tsv(
        reference_manifest,
        [{field: group[field] for field in reference_fields}],
        reference_fields,
    )
    outputs["reference_manifest"] = reference_manifest
    return outputs


def _task_digest(*paths: Path, parent_digest: str) -> str:
    """Return a deterministic checksum for extension task authorities.

    Args:
        *paths: Input authorities included in the task identity.
        parent_digest: Digest of the immutable parent workflow configuration.

    Returns:
        SHA-256 digest of the parent configuration and resolved input files.
    """
    import hashlib

    canonical = "\n".join(
        [parent_digest]
        + [f"{Path(path).resolve()}\t{sha256_file(Path(path))}" for path in paths]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reusable_extension_task(
    *,
    root: Path,
    task_kind: str,
    task_index: int,
    entity_id: str,
    configuration_digest: str,
) -> bool:
    """Return whether a published extension task exactly matches its inputs.

    Args:
        root: Stable task output directory.
        task_kind: Expected component task category.
        task_index: Expected zero-based task index.
        entity_id: Expected biological entity identifier.
        configuration_digest: Expected digest of all task input authorities.

    Returns:
        ``True`` when the marker and component manifest exactly match the task.

    Raises:
        StageError: If an existing task marker cannot be read or is malformed.
    """
    marker_path = root / "task_complete.tsv"
    if not marker_path.is_file():
        return False
    try:
        fields, rows = read_tsv(marker_path)
    except (OSError, ValueError) as exc:
        raise StageError(f"Could not read extension task marker {marker_path}: {exc}") from exc
    if tuple(fields) != TASK_MARKER_FIELDS or len(rows) != 1:
        raise StageError(f"Malformed extension task marker: {marker_path}")
    expected = {
        "task_kind": task_kind,
        "task_index": str(task_index),
        "status": "COMPLETE",
        "configuration_digest": configuration_digest,
        "entity_id": entity_id,
    }
    return all(rows[0].get(key) == value for key, value in expected.items()) and (
        root / "component_output" / "provenance" / "run_manifest.json"
    ).is_file()


def run_human_plant_structural_task(
    *,
    parent_config_path: Path,
    group_manifest: Path,
    ligandability_manifest: Path,
    output_root: Path,
    task_index: int,
    conda_environment: str,
) -> Path:
    """Run one combined human-and-plant group through structural alignment.

    Args:
        parent_config_path: Immutable parent plant-workflow configuration.
        group_manifest: Prepared group tasks with preserved plant references.
        ligandability_manifest: Completion authority for combined pocket inputs.
        output_root: Separate extension output root.
        task_index: Zero-based group task index.
        conda_environment: Conda environment containing the structural package.

    Returns:
        Stable task-completion marker path.
    """
    config = load_config(parent_config_path)
    group_source = Path(group_manifest).expanduser().resolve()
    aggregate_source = Path(ligandability_manifest).expanduser().resolve()
    row = _group_record(path=group_source, task_index=task_index)
    entity_id = f"{row['primary_group_type']}:{row['primary_group_id']}"
    digest = _task_digest(
        group_source,
        aggregate_source,
        parent_digest=config.digest,
    )
    task_root = (
        Path(output_root).expanduser().resolve()
        / "work_cache"
        / "human_plant_structural"
        / f"task_{task_index:04d}"
    )
    if _reusable_extension_task(
        root=task_root,
        task_kind="human_plant_structural",
        task_index=task_index,
        entity_id=entity_id,
        configuration_digest=digest,
    ):
        return task_root / "task_complete.tsv"
    if task_root.exists():
        failed = task_root.parent / "superseded"
        failed.mkdir(parents=True, exist_ok=True)
        os.replace(task_root, failed / f"{task_root.name}.{uuid.uuid4().hex}")
    staging = task_root.parent / f".{task_root.name}.running.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    output_directory = staging / "component_output"
    inputs = _prepare_human_plant_structural_inputs(
        combined_root=(
            Path(output_root).expanduser().resolve()
            / "ligandability"
            / "combined"
        ),
        group=row,
        destination=staging / "inputs",
    )
    settings = config.analysis.structural_alignment
    argv = (
        "conda",
        "run",
        "--no-capture-output",
        "--name",
        conda_environment,
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
        "--reference-manifest",
        str(inputs["reference_manifest"]),
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
        component_manifest = output_directory / "provenance" / "run_manifest.json"
        if not component_manifest.is_file():
            raise StageError(
                f"Structural task {entity_id} produced no run manifest"
            )
        _rebase_component_manifest(
            manifest_path=component_manifest,
            temporary_root=staging,
            stable_root=task_root,
        )
        _write_task_marker(
            root=staging,
            task_kind="human_plant_structural",
            task_index=task_index,
            configuration_digest=digest,
            entity_id=entity_id,
            output_directory=task_root / "component_output",
        )
        os.replace(staging, task_root)
    except BaseException:
        failed = task_root.parent / "failed"
        failed.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            os.replace(staging, failed / f"{task_root.name}.{uuid.uuid4().hex}")
        raise
    return task_root / "task_complete.tsv"


def _write_structural_browser(
    *,
    destination: Path,
    links: Sequence[tuple[str, str]],
) -> None:
    """Write a minimal, portable index for group-level 3D viewers.

    Args:
        destination: HTML file to publish.
        links: Pairs of biological entity identifiers and relative viewer paths.
    """
    items = "".join(
        f'<li><a href="{html.escape(relative)}">{html.escape(entity)}</a></li>'
        for entity, relative in links
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Human and plant structural alignments</title></head><body>"
        "<h1>Human and plant structural-alignment viewers</h1>"
        "<p>The original plant reference is retained for every group.</p><ul>"
        f"{items}</ul></body></html>",
        encoding="utf-8",
    )


def aggregate_human_plant_structural(
    *,
    group_manifest: Path,
    output_root: Path,
) -> Path:
    """Aggregate group shards and publish portable interactive viewers.

    Args:
        group_manifest: Prepared group task manifest.
        output_root: Separate human-and-plant extension root.

    Returns:
        Aggregate structural completion manifest.
    """
    root = Path(output_root).expanduser().resolve()
    fields, groups = read_tsv(Path(group_manifest).expanduser().resolve())
    missing_fields = sorted(set(GROUP_FIELDS).difference(fields))
    if missing_fields:
        raise StageError(
            "Group manifest is missing columns: " + ", ".join(missing_fields)
        )
    task_roots: list[Path] = []
    group_by_entity: dict[str, Mapping[str, str]] = {}
    for group in groups:
        task_index = int(group["group_task_index"])
        task_root = (
            root
            / "work_cache"
            / "human_plant_structural"
            / f"task_{task_index:04d}"
        )
        marker_path = task_root / "task_complete.tsv"
        if not marker_path.is_file():
            raise StageError(f"Human-and-plant structural task is incomplete: {task_root}")
        marker_fields, marker_rows = read_tsv(marker_path)
        if tuple(marker_fields) != TASK_MARKER_FIELDS or len(marker_rows) != 1:
            raise StageError(f"Malformed structural task marker: {marker_path}")
        expected_entity = (
            f"{group['primary_group_type']}:{group['primary_group_id']}"
        )
        if (
            marker_rows[0]["status"] != "COMPLETE"
            or marker_rows[0]["entity_id"] != expected_entity
        ):
            raise StageError(f"Structural task marker does not match {expected_entity}")
        task_roots.append(task_root)
        group_by_entity[expected_entity] = group
    if not task_roots:
        raise StageError("No human-containing structural groups were produced")
    structural_root = root / "structural_alignment"
    tables = structural_root / "tables"
    published: list[str] = []
    for dataset in STRUCTURAL_DATASETS:
        sources = [
            task_root / "component_output" / "tables" / f"{dataset}.parquet"
            for task_root in task_roots
        ]
        sources = [source for source in sources if source.is_file()]
        if not sources:
            if dataset.startswith("structural_pocket_sensitivity_"):
                LOGGER.warning("Optional structural dataset is absent: %s", dataset)
                continue
            raise StageError(f"No extension task produced {dataset}.parquet")
        destination = tables / f"{dataset}.parquet"
        _copy_parquet_union(sources=sources, destination=destination)
        _write_parquet_as_tsv(destination)
        published.append(dataset)
    links: list[tuple[str, str]] = []
    for task_root in task_roots:
        _marker_fields, marker_rows = read_tsv(task_root / "task_complete.tsv")
        entity_id = marker_rows[0]["entity_id"]
        source_directory = task_root / "component_output" / "interactive"
        if not (source_directory / "structural_alignment_browser.html").is_file():
            raise StageError(f"Structural viewer directory is incomplete: {source_directory}")
        slug = entity_id.replace(":", "__").replace("/", "_")
        destination = structural_root / "interactive" / "groups" / slug
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_directory, destination, dirs_exist_ok=True)
        links.append(
            (entity_id, f"groups/{slug}/structural_alignment_browser.html")
        )
    _write_structural_browser(
        destination=(
            structural_root / "interactive" / "structural_alignment_browser.html"
        ),
        links=sorted(links),
    )
    summary_rows = _table_records(tables / "structural_alignment_summary.parquet")
    for row in summary_rows:
        entity = f"{row['primary_group_type']}:{row['primary_group_id']}"
        expected = group_by_entity.get(entity)
        if expected is None:
            raise StageError(f"Unexpected structural summary group: {entity}")
        if str(row["reference_accession"]) != expected["reference_accession"]:
            raise StageError(
                f"Plant reference changed for {entity}: "
                f"{row['reference_accession']} instead of "
                f"{expected['reference_accession']}"
            )
    payload = {
        "status": "complete",
        "group_count": len(groups),
        "summary_count": len(summary_rows),
        "published_datasets": published,
        "interactive_group_count": len(links),
        "plant_references_preserved": True,
        "finished_at_utc": utc_now(),
    }
    manifest = structural_root / "aggregate_manifest.json"
    atomic_write_json(manifest, payload)
    return manifest


def _remove_empty_orchestrator_output_tree(*, path: Path) -> None:
    """Remove an empty output hierarchy created by a workflow orchestrator.

    Snakemake creates parent directories for declared file outputs before a
    rule runs. The portable-review component publishes through an atomic
    staging directory and therefore requires its final destination not to
    exist on a fresh run. This helper removes only a hierarchy containing
    real, empty directories. Any file, symlink or other filesystem entry keeps
    the destination intact so the component's resume validation remains
    fail-closed.

    Args:
        path: Prospective portable-review destination.

    Raises:
        StageError: If the destination is a symlink, cannot be inspected or
            changes while its empty hierarchy is being removed.
    """
    destination = Path(path)
    if destination.is_symlink():
        raise StageError(
            f"Refusing to remove orchestrator output symlink: {destination}"
        )
    if not destination.exists() or not destination.is_dir():
        return

    directories = [destination]
    for directory in directories:
        try:
            children = tuple(directory.iterdir())
        except OSError as exc:
            raise StageError(
                f"Could not inspect orchestrator output placeholder "
                f"{destination}: {exc}"
            ) from exc
        for child in children:
            if child.is_symlink() or not child.is_dir():
                return
            directories.append(child)

    try:
        for directory in reversed(directories):
            directory.rmdir()
    except OSError as exc:
        raise StageError(
            f"Could not remove empty orchestrator output placeholder "
            f"{destination}: {exc}"
        ) from exc
    LOGGER.info(
        "Removed empty orchestrator output placeholder: %s",
        destination,
    )


def build_human_plant_review(
    *,
    parent_config_path: Path,
    output_root: Path,
    conda_environment: str,
    review_limit: int,
) -> Path:
    """Build the app-ready human-and-plant portable review bundle.

    Args:
        parent_config_path: Immutable parent plant-workflow configuration.
        output_root: Separate human-and-plant extension root.
        conda_environment: Conda environment containing ``e3-pocket-review``.
        review_limit: Maximum original final evolutionary rank included.

    Returns:
        Review bundle run-manifest path.
    """
    if not 1 <= review_limit <= 500:
        raise StageError("review_limit must be between 1 and 500")
    config = load_config(parent_config_path)
    root = Path(output_root).expanduser().resolve()
    combined = root / "ligandability" / "combined"
    combined_tables = combined / "tables"
    structural = root / "structural_alignment"
    structural_tables = structural / "tables"
    output_directory = root / "pocket_review"
    _remove_empty_orchestrator_output_tree(path=output_directory)
    argv = [
        "conda",
        "run",
        "--no-capture-output",
        "--name",
        conda_environment,
        "e3-pocket-review",
        "--run-root",
        str(config.run_root),
        "--output-dir",
        str(output_directory),
        "--review-limit",
        str(review_limit),
        "--member-pocket-top-k",
        str(config.analysis.structural_alignment.member_pocket_top_k),
        "--shortlist",
        str(root / "manifests" / "review_shortlist.parquet"),
        "--selected-pockets",
        str(combined_tables / "selected_pockets.parquet"),
        "--ranked-pockets",
        str(combined_tables / "ranked_member_pockets.parquet"),
        "--ranked-pocket-sequence-coordinates",
        str(combined_tables / "ranked_pocket_sequence_coordinates.parquet"),
        "--asset-manifest",
        str(combined_tables / "asset_manifest.parquet"),
        "--alignments-root",
        str(combined / "alignments"),
        "--structural-summary",
        str(structural_tables / "structural_alignment_summary.parquet"),
        "--sensitivity-group-summary",
        str(
            structural_tables
            / "structural_pocket_sensitivity_group_summary.parquet"
        ),
        "--sensitivity-member-summary",
        str(
            structural_tables
            / "structural_pocket_sensitivity_member_summary.parquet"
        ),
        "--structural-alignments",
        str(structural_tables / "structural_alignments.parquet"),
        "--structural-pocket-comparisons",
        str(structural_tables / "pocket_comparisons.parquet"),
        "--structural-interactive-root",
        str(structural / "interactive"),
        "--supplementary-group-sequences",
        str(root / "manifests" / "human_group_members.parquet"),
        "--resume",
    ]
    _run_component(
        argv=tuple(argv),
        log_path=root / "logs" / "pocket_review.log",
        working_directory=config.project_root,
    )
    manifest = output_directory / "provenance" / "run_manifest.json"
    if not manifest.is_file():
        raise StageError("Human-and-plant review produced no run manifest")
    return manifest


def build_plant_baseline_review(
    *,
    parent_config_path: Path,
    output_root: Path,
    conda_environment: str,
    review_limit: int,
) -> Path:
    """Republish the plant-only baseline with portable pairwise viewers.

    This reporting-only step reads the completed Stage 09/09b/10 authorities.
    It does not rerun aligners, change the selected reference or modify the
    parent workflow directory.

    Args:
        parent_config_path: Immutable completed plant-workflow configuration.
        output_root: Separate human-and-plant extension root.
        conda_environment: Conda environment containing ``e3-pocket-review``.
        review_limit: Maximum original final evolutionary rank included.

    Returns:
        Plant-only portable review run-manifest path.
    """
    if not 1 <= review_limit <= 500:
        raise StageError("review_limit must be between 1 and 500")
    config = load_config(parent_config_path)
    root = Path(output_root).expanduser().resolve()
    output_directory = root / "plant_pocket_review"
    _remove_empty_orchestrator_output_tree(path=output_directory)
    _run_component(
        argv=(
            "conda",
            "run",
            "--no-capture-output",
            "--name",
            conda_environment,
            "e3-pocket-review",
            "--run-root",
            str(config.run_root),
            "--output-dir",
            str(output_directory),
            "--review-limit",
            str(review_limit),
            "--member-pocket-top-k",
            str(config.analysis.structural_alignment.member_pocket_top_k),
            "--resume",
        ),
        log_path=root / "logs" / "plant_pocket_review.log",
        working_directory=config.project_root,
    )
    manifest = output_directory / "provenance" / "run_manifest.json"
    if not manifest.is_file():
        raise StageError("Plant-only pocket review produced no run manifest")
    return manifest
