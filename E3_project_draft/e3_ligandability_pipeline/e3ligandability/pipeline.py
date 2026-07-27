"""End-to-end production ligandability workflow orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .alphafold import (
    AlphaFoldNotFoundError,
    build_retry_session,
    materialise_model_assets,
    normalise_prediction_metadata,
    query_prediction_metadata,
    select_prediction,
)
from .io_utils import ensure_directory
from .mapping import (
    compute_pocket_quality,
    join_fpocket_and_p2rank,
    map_pocket_residues,
)
from .models import AccessionResult
from .outputs import build_duckdb_from_parquet, publish_all_datasets
from .p2rank import parse_all_prediction_files
from .provenance import build_run_manifest, utc_now_iso, write_run_manifest
from .qc import run_validation_checks
from .structure import (
    compare_api_quality,
    compute_model_quality,
    parse_model_residues,
)
from .tools import (
    capture_tool_version,
    check_required_version,
    resolve_executable,
    run_fpocket_rescore,
)
from .fpocket import (
    discover_fpocket_info_files,
    parse_all_pocket_residues,
    parse_fpocket_info,
)


_LOGGER = logging.getLogger("e3ligandability.pipeline")


def _optional_float(value: Any) -> float | None:
    """Parse an optional numeric input field.

    Args:
        value: Candidate scalar value.

    Returns:
        Float or ``None``.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return None
    return float(text)


def metadata_from_input(accession: str, record: dict[str, str]) -> dict[str, Any]:
    """Build normalised AlphaFold metadata from an input row.

    Args:
        accession: Protein accession.
        record: Input accession record.

    Returns:
        Normalised metadata dictionary.
    """

    confident = _optional_float(record.get("fraction_plddt_confident"))
    very_high = _optional_float(record.get("fraction_plddt_very_high"))
    fraction_ge_70 = None
    if confident is not None and very_high is not None:
        fraction_ge_70 = confident + very_high
    return {
        "accession": accession,
        "entry_id": record.get("entry_id") or None,
        "uniprot_accession": record.get("uniprot_accession") or accession,
        "global_metric_value": _optional_float(
            record.get("global_metric_value")
        ),
        "fraction_plddt_very_low": _optional_float(
            record.get("fraction_plddt_very_low")
        ),
        "fraction_plddt_low": _optional_float(
            record.get("fraction_plddt_low")
        ),
        "fraction_plddt_confident": confident,
        "fraction_plddt_very_high": very_high,
        "api_fraction_residues_ge_70": _optional_float(
            record.get("api_fraction_residues_ge_70")
        )
        if record.get("api_fraction_residues_ge_70")
        else fraction_ge_70,
        "cif_url": record.get("cif_url") or None,
        "pae_url": record.get("pae_url") or None,
        "msa_url": record.get("msa_url") or None,
        "plddt_url": record.get("plddt_url") or None,
        "model_created_date": record.get("model_created_date") or None,
        "latest_version": record.get("latest_version") or None,
        "selection_prediction_count": None,
        "selection_exact_accession_count": None,
        "selection_canonical_monomer_count": None,
        "selection_rule": "input_record",
    }


def resolve_alphafold_metadata(
    accession: str,
    input_record: dict[str, str],
    config: dict[str, Any],
    session: Any,
) -> dict[str, Any]:
    """Resolve metadata from the API or supplied input fields.

    Args:
        accession: Protein accession.
        input_record: Input accession record.
        config: Effective configuration.
        session: Configured HTTP session.

    Returns:
        Normalised AlphaFold metadata.

    Raises:
        AlphaFoldNotFoundError: If an API query is required but no model exists.
    """

    local_model = bool(input_record.get("model_path", "").strip())
    query_local = bool(config["alphafold"]["query_api_for_local_models"])
    should_query = not local_model or query_local
    if should_query:
        predictions = query_prediction_metadata(
            session=session,
            api_base_url=str(config["alphafold"]["api_base_url"]),
            accession=accession,
            timeout_seconds=float(
                config["alphafold"]["request_timeout_seconds"]
            ),
        )
        selected = select_prediction(predictions, accession)
        return normalise_prediction_metadata(accession, selected)
    return metadata_from_input(accession, input_record)


def preflight_external_tools(
    config: dict[str, Any],
) -> tuple[Path | None, Path | None, list[dict[str, Any]]]:
    """Resolve and validate external tool installations.

    Args:
        config: Effective configuration.

    Returns:
        FPocket executable, P2Rank executable and version records. Executable
        paths are ``None`` when external tools are disabled.
    """

    if not config["external_tools"]["run_fpocket_p2rank"]:
        return None, None, []

    fpocket = resolve_executable(
        str(config["external_tools"]["fpocket_executable"])
    )
    p2rank = resolve_executable(
        str(config["external_tools"]["p2rank_executable"])
    )
    fpocket_version = capture_tool_version(
        fpocket,
        version_arguments=list(
            config["external_tools"]["fpocket_version_arguments"]
        ),
    )
    p2rank_version = capture_tool_version(
        p2rank,
        version_arguments=list(
            config["external_tools"]["p2rank_version_arguments"]
        ),
    )
    check_required_version(
        fpocket_version,
        str(config["external_tools"]["required_fpocket_version_prefix"]),
        "FPocket",
    )
    check_required_version(
        p2rank_version,
        str(config["external_tools"]["required_p2rank_version_prefix"]),
        "P2Rank",
    )
    return fpocket, p2rank, [fpocket_version, p2rank_version]


def parse_tool_outputs(
    accession: str,
    tool_directory: Path,
    model_residues: list[Any],
    config: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Parse FPocket/P2Rank outputs and calculate pocket confidence.

    Args:
        accession: Protein accession.
        tool_directory: Accession-specific tool-output directory.
        model_residues: Parsed model residue records.
        config: Effective configuration.

    Returns:
        FPocket rows, P2Rank rows, joined pocket rows, residue mappings and
        pocket-quality rows.

    Raises:
        ValueError: If output discovery is ambiguous or required data are absent.
    """

    info_files = discover_fpocket_info_files(tool_directory)
    if len(info_files) != 1:
        raise ValueError(
            f"Expected exactly one FPocket info file for {accession}; "
            f"found {len(info_files)}: {info_files}"
        )
    fpocket_records = parse_fpocket_info(info_files[0], accession)
    p2rank_records = parse_all_prediction_files(tool_directory, accession)
    joined_records = join_fpocket_and_p2rank(fpocket_records, p2rank_records)
    pocket_residue_objects = parse_all_pocket_residues(
        tool_directory,
        accession,
    )
    mapping_records = map_pocket_residues(
        pocket_residue_objects,
        model_residues,
    )
    pocket_quality = compute_pocket_quality(
        mapping_records=mapping_records,
        confident_threshold=float(
            config["quality"]["model_confident_threshold"]
        ),
        very_high_threshold=float(
            config["quality"]["model_very_high_threshold"]
        ),
        minimum_mapping_fraction=float(
            config["quality"]["minimum_pocket_mapping_fraction"]
        ),
    )
    return (
        fpocket_records,
        p2rank_records,
        joined_records,
        mapping_records,
        pocket_quality,
    )


def process_accession(
    input_record: dict[str, str],
    accession_column: str,
    output_root: Path,
    config: dict[str, Any],
    session: Any,
    fpocket_executable: Path | None,
    p2rank_executable: Path | None,
) -> AccessionResult:
    """Process one accession through metadata, structure and pocket stages.

    Args:
        input_record: Accession input row.
        accession_column: Name of accession field.
        output_root: Run output root.
        config: Effective configuration.
        session: Configured HTTP session.
        fpocket_executable: Resolved FPocket executable or ``None``.
        p2rank_executable: Resolved P2Rank executable or ``None``.

    Returns:
        Accession result containing successful or failed stage evidence.
    """

    accession = input_record[accession_column]
    result = AccessionResult(accession=accession)
    try:
        result.stage = "alphafold_metadata"
        result.metadata = resolve_alphafold_metadata(
            accession=accession,
            input_record=input_record,
            config=config,
            session=session,
        )

        result.stage = "model_materialisation"
        model_path, asset_manifests = materialise_model_assets(
            accession=accession,
            input_record=input_record,
            metadata=result.metadata,
            output_directory=output_root / "models",
            session=session,
            timeout_seconds=float(
                config["alphafold"]["request_timeout_seconds"]
            ),
            reuse_existing=bool(config["alphafold"]["reuse_valid_files"]),
            download_pae=bool(config["alphafold"]["download_pae"]),
            download_msa=bool(config["alphafold"]["download_msa"]),
            download_plddt_json=bool(
                config["alphafold"]["download_plddt_json"]
            ),
        )
        result.model_path = model_path
        result.metadata["model_path"] = str(model_path)
        result.metadata["asset_manifest"] = asset_manifests

        result.stage = "model_quality"
        model_residues = parse_model_residues(model_path)
        result.model_quality = compute_model_quality(
            accession=accession,
            residues=model_residues,
            confident_threshold=float(
                config["quality"]["model_confident_threshold"]
            ),
            very_high_threshold=float(
                config["quality"]["model_very_high_threshold"]
            ),
        )
        result.model_quality.update(
            compare_api_quality(
                computed=result.model_quality,
                metadata=result.metadata,
                mean_tolerance=float(
                    config["quality"]["api_mean_plddt_tolerance"]
                ),
                fraction_tolerance=float(
                    config["quality"]["api_fraction_tolerance"]
                ),
            )
        )
        result.model_quality["model_path"] = str(model_path)
        result.model_quality["passes_model_confidence_threshold"] = (
            float(result.model_quality["fraction_residues_ge_70"])
            >= float(
                config["quality"]["minimum_fraction_residues_ge_70"]
            )
        )

        if config["external_tools"]["run_fpocket_p2rank"]:
            if fpocket_executable is None or p2rank_executable is None:
                raise RuntimeError("External tools enabled but not resolved.")
            result.stage = "fpocket_p2rank"
            tool_directory = output_root / "tool_outputs" / accession
            command_record = run_fpocket_rescore(
                accession=accession,
                model_path=model_path,
                output_directory=tool_directory,
                fpocket_executable=fpocket_executable,
                p2rank_executable=p2rank_executable,
                p2rank_model=str(
                    config["external_tools"]["p2rank_model"]
                ),
                threads=int(config["external_tools"]["p2rank_threads"]),
                keep_fpocket_output=bool(
                    config["external_tools"]["p2rank_keep_fpocket_output"]
                ),
                timeout_seconds=float(
                    config["external_tools"]["command_timeout_seconds"]
                ),
            )
            result.commands.append(command_record)

            result.stage = "pocket_output_parsing"
            (
                result.fpocket_records,
                result.p2rank_records,
                joined_records,
                result.pocket_residues,
                result.pocket_quality,
            ) = parse_tool_outputs(
                accession=accession,
                tool_directory=tool_directory,
                model_residues=model_residues,
                config=config,
            )
            result.metadata["joined_pockets"] = joined_records

        result.status = "SUCCESS"
        result.stage = "complete"
        result.message = "All enabled stages completed."
    except AlphaFoldNotFoundError as error:
        result.status = "MISSING_MODEL"
        result.message = str(error)
        _LOGGER.warning("%s: %s", accession, error)
    except Exception as error:  # noqa: BLE001 - accession failure is recorded.
        result.status = "FAILED"
        result.message = f"{type(error).__name__}: {error}"
        _LOGGER.exception(
            "Accession %s failed during stage %s",
            accession,
            result.stage,
        )
    return result


def results_to_datasets(
    results: list[AccessionResult],
) -> dict[str, list[dict[str, Any]]]:
    """Flatten accession results into analytical datasets.

    Args:
        results: Per-accession pipeline results.

    Returns:
        Dataset mapping used by validation and publication.
    """

    metadata_records = []
    asset_records = []
    model_quality = []
    fpocket_records = []
    p2rank_records = []
    joined_pockets = []
    pocket_mappings = []
    pocket_quality = []
    commands = []

    for result in results:
        if result.metadata:
            metadata = dict(result.metadata)
            assets = metadata.pop("asset_manifest", [])
            joined = metadata.pop("joined_pockets", [])
            metadata_records.append(metadata)
            asset_records.extend(assets)
            joined_pockets.extend(joined)
        if result.model_quality:
            model_quality.append(result.model_quality)
        fpocket_records.extend(result.fpocket_records)
        p2rank_records.extend(result.p2rank_records)
        pocket_mappings.extend(result.pocket_residues)
        pocket_quality.extend(result.pocket_quality)
        commands.extend(result.commands)

    return {
        "accession_status": [result.status_record() for result in results],
        "alphafold_metadata": metadata_records,
        "asset_manifest": asset_records,
        "model_quality": model_quality,
        "fpocket_pockets": fpocket_records,
        "p2rank_pockets": p2rank_records,
        "joined_pockets": joined_pockets,
        "pocket_residue_mappings": pocket_mappings,
        "pocket_quality": pocket_quality,
        "external_commands": commands,
        "validation": [],
    }


def run_pipeline(
    input_path: Path,
    accession_records: list[dict[str, str]],
    output_root: Path,
    config: dict[str, Any],
    git_repository: Path | None = None,
) -> dict[str, Any]:
    """Execute, validate and publish the production workflow.

    Args:
        input_path: Original accession input path.
        accession_records: Validated input rows.
        output_root: Run output directory.
        config: Effective configuration.
        git_repository: Optional Git repository root for provenance.

    Returns:
        Run outcome including datasets, manifest and success state.
    """

    started_at = utc_now_iso()
    root = ensure_directory(output_root)
    session = build_retry_session(
        retry_total=int(config["alphafold"]["retry_total"]),
        backoff_seconds=float(config["alphafold"]["retry_backoff_seconds"]),
    )
    try:
        fpocket, p2rank, tool_versions = preflight_external_tools(config)
        accession_column = str(config["input"]["accession_column"])
        results: list[AccessionResult] = []
        for record in accession_records:
            result = process_accession(
                input_record=record,
                accession_column=accession_column,
                output_root=root,
                config=config,
                session=session,
                fpocket_executable=fpocket,
                p2rank_executable=p2rank,
            )
            results.append(result)
            if (
                result.status not in {"SUCCESS"}
                and not config["execution"]["continue_on_accession_error"]
            ):
                break
    finally:
        session.close()

    datasets = results_to_datasets(results)
    datasets["validation"] = run_validation_checks(
        datasets=datasets,
        minimum_model_fraction=float(
            config["quality"]["minimum_fraction_residues_ge_70"]
        ),
    )
    file_manifests = publish_all_datasets(
        datasets=datasets,
        output_root=root,
        write_tsv=bool(config["output"]["write_tsv"]),
        write_parquet=bool(config["output"]["write_parquet"]),
    )
    if config["output"]["write_duckdb"]:
        parquet_manifests = [
            record for record in file_manifests if record["format"] == "parquet"
        ]
        database_manifest = build_duckdb_from_parquet(
            parquet_manifests=parquet_manifests,
            database_path=root / "duckdb" / "e3_ligandability.duckdb",
        )
        file_manifests.append(database_manifest)

    finished_at = utc_now_iso()
    manifest = build_run_manifest(
        input_path=input_path,
        output_root=root,
        config=config,
        started_at=started_at,
        finished_at=finished_at,
        datasets=datasets,
        file_manifests=file_manifests,
        tool_versions=tool_versions,
        git_repository=git_repository,
    )
    manifest_path = root / "provenance" / "run_manifest.json"
    write_run_manifest(manifest_path, manifest)

    failed_accessions = [
        result.accession for result in results if result.status != "SUCCESS"
    ]
    failed_checks = [
        record["check"]
        for record in datasets["validation"]
        if record["status"] != "PASS"
    ]
    fail_on_accession = bool(
        config["execution"]["fail_run_if_any_accession_failed"]
    )
    success = not failed_checks and not (
        fail_on_accession and failed_accessions
    )
    return {
        "success": success,
        "failed_accessions": failed_accessions,
        "failed_checks": failed_checks,
        "datasets": datasets,
        "file_manifests": file_manifests,
        "manifest": manifest,
        "manifest_path": str(manifest_path),
    }
