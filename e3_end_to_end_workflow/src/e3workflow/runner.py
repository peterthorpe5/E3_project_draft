"""Atomic execution and publication of workflow stages."""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from e3workflow import __version__
from e3workflow.benchmarking import (
    ProcessTreeResourceMonitor,
    StageResourceUsage,
    write_stage_resource_outputs,
)
from e3workflow.config import (
    STAGE_NAMES,
    WorkflowConfig,
    controlled_input_paths,
    stage_dependencies,
    stage_interpretation,
    stage_purpose,
)
from e3workflow.integration import run_app_ready_stage, run_integrated_stage
from e3workflow.ligandability import run_ligandability_stage
from e3workflow.control import stage_token_path
from e3workflow.errors import StageError
from e3workflow.io_utils import (
    atomic_write_json,
    close_logger,
    configure_logging,
    inventory_files,
    read_json,
    sha256_file,
    utc_now,
    write_tsv,
)
from e3workflow.manifests import validate_proteomes, validate_seed_evidence, validate_shortlist
from e3workflow.reporting import summarise_declared_outputs, write_stage_report
from e3workflow.prioritisation import run_prestructure_stage
from e3workflow.production import (
    run_candidate_evidence_stage,
    run_domain_stage,
    run_expression_stage,
    run_reused_orthofinder_stage,
    run_reused_discovery_stage,
)
from e3workflow.resources import (
    EXPRESSION_RESOURCE_TYPES,
    read_resource_manifest,
)


def format_command(command: tuple[str, ...], values: dict[str, str]) -> list[str]:
    """Substitute only documented placeholders in an argv sequence."""
    rendered = []
    for token in command:
        try:
            rendered.append(token.format_map(values))
        except KeyError as exc:
            raise StageError(f"Unknown command placeholder {exc.args[0]!r} in {token!r}") from exc
    return rendered


def _validate_upstream_manifest(path: Path, config: WorkflowConfig) -> list[dict[str, Any]]:
    """Validate one prerequisite manifest and return its lineage."""
    payload = read_json(path)
    if payload.get("configuration_digest") != config.digest:
        raise StageError(f"Upstream configuration digest differs: {path}")
    if payload.get("status") not in {"complete", "skipped_optional"}:
        raise StageError(f"Upstream stage is not complete: {path}")
    lineage = payload.get("lineage")
    if not isinstance(lineage, list):
        raise StageError(f"Upstream manifest has invalid lineage: {path}")
    outputs = payload.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise StageError(f"Upstream manifest has no output inventory: {path}")
    for record in outputs:
        if not isinstance(record, dict):
            raise StageError(f"Upstream manifest contains an invalid output record: {path}")
        relative = Path(str(record.get("path", "")))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise StageError(f"Upstream manifest contains an unsafe output path: {relative}")
        output = path.parent / relative
        if not output.is_file():
            raise StageError(f"Upstream output is missing: {output}")
        if output.stat().st_size != record.get("size_bytes"):
            raise StageError(f"Upstream output size changed: {output}")
        if sha256_file(output) != record.get("sha256"):
            raise StageError(f"Upstream output checksum changed: {output}")
    return list(lineage)


def validate_upstream(config: WorkflowConfig, stage_name: str) -> list[dict[str, Any]]:
    """Validate all scientific prerequisites and return de-duplicated lineage.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.

    Returns:
        Ordered lineage records across every prerequisite branch.
    """
    merged: dict[str, dict[str, Any]] = {}
    for dependency in stage_dependencies(stage_name):
        path = config.run_root / dependency / "stage_manifest.json"
        for record in _validate_upstream_manifest(path, config):
            lineage_stage = str(record.get("stage", ""))
            if not lineage_stage:
                raise StageError(f"Upstream lineage record has no stage name: {path}")
            merged[lineage_stage] = record
    return [merged[name] for name in STAGE_NAMES if name in merged]


def validate_expected_outputs(stage_root: Path, outputs: tuple[str, ...]) -> None:
    """Require every declared stage output to exist and be non-empty."""
    missing = []
    for relative in outputs:
        path = stage_root / relative
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(relative)
    if missing:
        raise StageError(f"Missing or empty declared outputs: {', '.join(missing)}")


def _run_internal_inputs(config: WorkflowConfig, stage_root: Path) -> None:
    """Validate controlled inputs required by enabled branches and publish an inventory."""
    required_inputs = dict(controlled_input_paths(config))
    rows: list[dict[str, Any]] = []
    if "proteomes" in required_inputs:
        proteomes = validate_proteomes(config.proteomes_manifest, verify_checksums=True)
        rows.append(
            {
                "manifest": "proteomes",
                "path": config.proteomes_manifest,
                "row_count": len(proteomes),
                "size_bytes": config.proteomes_manifest.stat().st_size,
                "sha256": sha256_file(config.proteomes_manifest),
            }
        )
    if config.stage("02_discovery").enabled and (
        config.stage("02_discovery").command or config.mode == "synthetic"
    ):
        seeds = validate_seed_evidence(config.seeds_manifest)
        rows.append(
            {
                "manifest": "seeds",
                "path": config.seeds_manifest,
                "row_count": len(seeds),
                "size_bytes": config.seeds_manifest.stat().st_size,
                "sha256": sha256_file(config.seeds_manifest),
            }
        )
    if config.stage("08_shortlist_gate").enabled and config.shortlist_manifest.is_file():
        shortlist = validate_shortlist(config.shortlist_manifest)
        rows.append(
            {
                "manifest": "shortlist",
                "path": config.shortlist_manifest,
                "row_count": len(shortlist),
                "size_bytes": config.shortlist_manifest.stat().st_size,
                "sha256": sha256_file(config.shortlist_manifest),
            }
        )
    existing_labels = {str(row["manifest"]) for row in rows}
    for label, path in required_inputs.items():
        if label in existing_labels:
            continue
        if not path.is_file() or path.stat().st_size == 0:
            raise StageError(f"Controlled input is missing or empty: {label}={path}")
        row_count: int | str = ""
        if label == "expression_manifest":
            row_count = len(
                read_resource_manifest(
                    path=path,
                    allowed_resource_types=EXPRESSION_RESOURCE_TYPES,
                    verify_checksums=True,
                )
            )
        elif label == "ligandability_manifest":
            row_count = len(
                read_resource_manifest(
                    path=path,
                    allowed_resource_types={"ligandability"},
                    verify_checksums=True,
                )
            )
        rows.append(
            {
                "manifest": label,
                "path": path,
                "row_count": row_count,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    write_tsv(
        stage_root / "input_validation.tsv",
        rows,
        ("manifest", "path", "row_count", "size_bytes", "sha256"),
    )


def _summarise_protein_fasta(path: Path) -> tuple[int, int]:
    """Validate one protein FASTA and return sequence and residue counts.

    Args:
        path: Existing uncompressed protein FASTA.

    Returns:
        Number of records and non-whitespace sequence characters.

    Raises:
        StageError: If records are malformed, empty or have duplicate primary identifiers.
    """
    sequence_count = 0
    residue_count = 0
    current_identifier = ""
    current_residue_count = 0
    identifiers: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    if current_identifier and current_residue_count == 0:
                        raise StageError(
                            f"FASTA record {current_identifier!r} has no residues at "
                            f"{path}:{line_number}"
                        )
                    identifier = line[1:].split(maxsplit=1)[0]
                    if not identifier:
                        raise StageError(f"Empty FASTA identifier at {path}:{line_number}")
                    if identifier in identifiers:
                        raise StageError(
                            f"Duplicate FASTA identifier {identifier!r} at {path}:{line_number}"
                        )
                    identifiers.add(identifier)
                    current_identifier = identifier
                    current_residue_count = 0
                    sequence_count += 1
                    continue
                if not current_identifier:
                    raise StageError(
                        f"Sequence data precede the first header at {path}:{line_number}"
                    )
                line_residues = sum(not character.isspace() for character in raw_line)
                current_residue_count += line_residues
                residue_count += line_residues
    except UnicodeError as exc:
        raise StageError(f"Protein FASTA is not valid UTF-8 text: {path}") from exc
    if sequence_count == 0:
        raise StageError(f"Protein FASTA contains no records: {path}")
    if current_residue_count == 0:
        raise StageError(f"FASTA record {current_identifier!r} has no residues at end of {path}")
    return sequence_count, residue_count


def _run_internal_prepared_proteomes(config: WorkflowConfig, stage_root: Path) -> None:
    """Copy checksum-validated proteomes into the isolated OrthoFinder input directory.

    Args:
        config: Validated workflow configuration.
        stage_root: Temporary atomic-publication directory for stage 01.

    Raises:
        StageError: If a copied FASTA differs from its controlled source.
    """
    proteomes = validate_proteomes(config.proteomes_manifest, verify_checksums=True)
    output_directory = stage_root / "proteomes"
    output_directory.mkdir(parents=True)
    rows = []
    for proteome in proteomes:
        source = Path(proteome["resolved_fasta_path"])
        sequence_count, residue_count = _summarise_protein_fasta(source)
        relative_output = Path("proteomes") / f"{proteome['species_id']}.fasta"
        destination = stage_root / relative_output
        shutil.copyfile(source, destination)
        prepared_sha256 = sha256_file(destination)
        source_sha256 = proteome["fasta_sha256"].strip().lower()
        if prepared_sha256 != source_sha256:
            raise StageError(
                f"Prepared FASTA checksum differs from its controlled source: {destination}"
            )
        rows.append(
            {
                "species_id": proteome["species_id"],
                "scientific_name": proteome["scientific_name"],
                "source_fasta_path": source,
                "source_fasta_sha256": source_sha256,
                "prepared_fasta_relative_path": relative_output,
                "prepared_fasta_sha256": prepared_sha256,
                "sequence_count": sequence_count,
                "residue_count": residue_count,
                "size_bytes": destination.stat().st_size,
            }
        )
    write_tsv(
        stage_root / "prepared_proteomes.tsv",
        rows,
        (
            "species_id",
            "scientific_name",
            "source_fasta_path",
            "source_fasta_sha256",
            "prepared_fasta_relative_path",
            "prepared_fasta_sha256",
            "sequence_count",
            "residue_count",
            "size_bytes",
        ),
    )


def _run_synthetic_shortlist(config: WorkflowConfig, stage_root: Path) -> None:
    """Publish explicitly approved synthetic accessions for orchestration tests only."""
    rows = validate_shortlist(config.shortlist_manifest)
    approved = [row for row in rows if row["decision"].strip().lower() == "approve"]
    write_tsv(stage_root / "approved_accessions.tsv", approved, tuple(rows[0]))


def run_internal_stage(config: WorkflowConfig, stage_name: str, stage_root: Path) -> None:
    """Run a safe built-in stage or a clearly labelled synthetic stage."""
    if stage_name == "00_inputs":
        _run_internal_inputs(config, stage_root)
    elif stage_name == "01_prepared_proteomes" and config.mode == "production":
        _run_internal_prepared_proteomes(config, stage_root)
    elif stage_name == "02_discovery" and config.mode == "production":
        run_reused_discovery_stage(config=config, stage_root=stage_root)
    elif stage_name == "03_candidate_evidence" and config.mode == "production":
        run_candidate_evidence_stage(config=config, stage_root=stage_root)
    elif stage_name == "04_orthofinder" and config.mode == "production":
        run_reused_orthofinder_stage(config=config, stage_root=stage_root)
    elif stage_name == "06_domains" and config.mode == "production":
        run_domain_stage(config=config, stage_root=stage_root)
    elif stage_name == "07_expression" and config.mode == "production":
        run_expression_stage(config=config, stage_root=stage_root)
    elif stage_name == "08_shortlist_gate" and config.mode == "production":
        run_prestructure_stage(config=config, stage_root=stage_root)
    elif stage_name == "08_shortlist_gate" and config.mode == "synthetic":
        _run_synthetic_shortlist(config=config, stage_root=stage_root)
    elif stage_name == "09_ligandability" and config.mode == "production":
        run_ligandability_stage(config=config, stage_root=stage_root)
    elif stage_name == "10_integrated_resource" and config.mode == "production":
        run_integrated_stage(config=config, stage_root=stage_root)
    elif stage_name == "11_app_ready":
        if config.mode == "production":
            run_app_ready_stage(config=config, stage_root=stage_root)
        else:
            write_tsv(
                stage_root / "app_handoff.tsv",
                [
                    {
                        "run_name": config.run_name,
                        "mode": config.mode,
                        "production_eligible": "false",
                        "integrated_stage": config.run_root / "10_integrated_resource",
                    }
                ],
                ("run_name", "mode", "production_eligible", "integrated_stage"),
            )
    elif config.mode == "synthetic":
        write_tsv(
            stage_root / "synthetic_stage.tsv",
            [{"stage": stage_name, "notice": "TEST DATA ONLY; NOT A SCIENTIFIC RESULT"}],
            ("stage", "notice"),
        )
    else:
        raise StageError(f"No internal production implementation exists for {stage_name}")


def run_external_command(
    argv: list[str],
    working_directory: Path,
    environment: dict[str, str],
    command_log: Path,
    logger: logging.Logger,
) -> int:
    """Run an external command while streaming output to file and console logs.

    Args:
        argv: Fully rendered command argument vector.
        working_directory: Existing command working directory.
        environment: Complete subprocess environment.
        command_log: Plain-text destination for unmodified tool output.
        logger: Configured stage logger.

    Returns:
        Process return code.
    """
    command_log.parent.mkdir(parents=True, exist_ok=True)
    with command_log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            argv,
            cwd=working_directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout is None:
            raise StageError("External command did not provide a readable output stream")
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            logger.info("tool | %s", line.rstrip("\n"))
        return process.wait()


def execute_stage(config: WorkflowConfig, stage_name: str, verbose: bool = False) -> Path:
    """Execute one stage in a temporary directory and atomically publish it.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.
        verbose: Emit DEBUG messages to the console as well as the log.

    Returns:
        Formal stage-manifest path.
    """
    stage = config.stage(stage_name)
    run_root = config.run_root
    run_root.mkdir(parents=True, exist_ok=True)
    staging = run_root / ".staging" / f"{stage_name}.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    logger = configure_logging(staging / "logs" / "stage.log", verbose)
    started = utc_now()
    started_monotonic = time.monotonic()
    status = "complete"
    stage_return_code = 0
    resource_usage: StageResourceUsage | None = None
    monitor_stopped = False
    monitor = ProcessTreeResourceMonitor(
        stage_name=stage_name,
        requested_threads=stage.threads,
        requested_memory_mb=stage.memory_mb,
        requested_runtime_minutes=stage.runtime_minutes,
        sample_interval_seconds=config.benchmarking.sample_interval_seconds,
    )
    try:
        monitor.start()
        lineage = validate_upstream(config=config, stage_name=stage_name)
        control_token = stage_token_path(config, stage_name)
        if not control_token.is_file():
            raise StageError(
                f"Workflow control token is missing: {control_token}. Run the shell wrapper."
            )
        purpose, rationale = stage_purpose(stage_name)
        dependencies = stage_dependencies(stage_name)
        logger.info("Stage: %s", stage_name)
        logger.info("What this stage does: %s", purpose)
        logger.info("Why this stage is required: %s", rationale)
        logger.info("Run mode: %s", config.mode)
        logger.info("Evidence mode: %s", stage.evidence_mode)
        logger.info("Prerequisite stages: %s", ", ".join(dependencies) or "controlled inputs")
        logger.info("Temporary stage directory: %s", staging)
        logger.info(
            "Requested resources: threads=%d, memory_mb=%d, runtime_minutes=%d",
            stage.threads,
            stage.memory_mb,
            stage.runtime_minutes,
        )
        logger.info(
            "Expected outputs: %s",
            ", ".join(stage.expected_outputs) or "explicit skipped-stage record",
        )
        logger.info(
            "Benchmarking: process-tree CPU, memory, I/O, processes and threads every %.3f s; "
            "the run summary also records broader runner timing and optional Slurm accounting.",
            config.benchmarking.sample_interval_seconds,
        )
        logger.info(
            "Reporting: after output validation, create a checksum-bound HTML summary with "
            "scientific interpretation, command provenance, resource graphics and bounded result "
            "previews. A complete-run report is created only after the full DAG finishes."
        )
        execution: dict[str, Any] = {
            "implementation": "internal",
            "working_directory": str(config.project_root),
            "argv": [],
            "display_command": (
                f"e3workflow.runner.run_internal_stage(stage_name={stage_name!r})"
            ),
        }
        if not stage.enabled:
            status = "skipped_optional"
            execution.update(
                {
                    "implementation": "disabled_optional",
                    "display_command": "No command: stage disabled in configuration.",
                }
            )
            logger.info("Stage is disabled and optional; publishing an explicit skipped record.")
            write_tsv(
                staging / "SKIPPED.tsv",
                [{"stage": stage_name, "reason": "disabled in configuration"}],
                ("stage", "reason"),
            )
        elif stage.command:
            values = {
                "project_root": str(config.project_root),
                "run_root": str(run_root),
                "stage_dir": str(staging),
                "proteomes_manifest": str(config.proteomes_manifest),
                "seeds_manifest": str(config.seeds_manifest),
                "shortlist_manifest": str(config.shortlist_manifest),
                "candidate_evidence": str(config.resources.candidate_evidence or ""),
                "candidate_evidence_manifest": str(
                    config.resources.candidate_evidence_manifest or ""
                ),
                "orthology_species_manifest": str(
                    config.resources.orthology_species_manifest or ""
                ),
                "inherited_sqlite": str(config.resources.inherited_sqlite or ""),
                "expression_manifest": str(config.resources.expression_manifest or ""),
                "ligandability_manifest": str(
                    config.resources.ligandability_manifest or ""
                ),
                "domain_annotation_manifest": str(
                    config.resources.domain_annotation_manifest or ""
                ),
                "domain_cache_root": str(config.resources.domain_cache_root or ""),
                "e3_domain_catalogue": str(config.resources.e3_domain_catalogue or ""),
                "selected_pockets": str(
                    run_root / "09_ligandability" / "tables" / "selected_pockets.parquet"
                ),
                "pocket_residue_mappings": str(
                    run_root
                    / "09_ligandability"
                    / "tables"
                    / "reused_pocket_residue_mappings.parquet"
                ),
                "structure_asset_manifest": str(
                    run_root
                    / "09_ligandability"
                    / "tables"
                    / "reused_asset_manifest.parquet"
                ),
                "usalign_executable": (
                    config.analysis.structural_alignment.usalign_executable
                ),
                "tmalign_executable": (
                    config.analysis.structural_alignment.tmalign_executable
                ),
                "structural_distance_threshold_angstrom": str(
                    config.analysis.structural_alignment.distance_threshold_angstrom
                ),
                "structural_maximum_centroid_distance_angstrom": str(
                    config.analysis.structural_alignment.maximum_centroid_distance_angstrom
                ),
                "structural_minimum_pocket_overlap_fraction": str(
                    config.analysis.structural_alignment.minimum_pocket_overlap_fraction
                ),
                "structural_minimum_global_tm_score": str(
                    config.analysis.structural_alignment.minimum_global_tm_score
                ),
                "structural_minimum_group_support_fraction": str(
                    config.analysis.structural_alignment.minimum_group_support_fraction
                ),
                "threads": str(stage.threads),
            }
            argv = format_command(stage.command, values)
            execution.update(
                {
                    "implementation": "external_argv",
                    "argv": argv,
                    "display_command": shlex.join(argv),
                }
            )
            logger.info("Command argv: %s", shlex.join(argv))
            environment = os.environ.copy()
            environment.update({f"E3_{key.upper()}": value for key, value in values.items()})
            return_code = run_external_command(
                argv=argv,
                working_directory=config.project_root,
                environment=environment,
                command_log=staging / "logs" / "command.log",
                logger=logger,
            )
            if return_code:
                stage_return_code = return_code
                raise StageError(
                    f"Stage command returned {return_code}; see logs/command.log"
                )
        else:
            logger.info("Using the package's validated internal implementation for this stage.")
            run_internal_stage(config, stage_name, staging)
        if stage.enabled:
            validate_expected_outputs(staging, stage.expected_outputs)
        logger.info("Validated %d declared outputs.", len(stage.expected_outputs))
        resource_usage, resource_samples = monitor.stop(
            return_code=stage_return_code,
            status=status,
        )
        monitor_stopped = True
        write_stage_resource_outputs(
            stage_root=staging,
            usage=resource_usage,
            samples=resource_samples,
        )
        logger.info(
            "Measured resources: wall=%.3f s, cpu=%.3f s, mean_cpu_cores=%.3f, "
            "peak_rss=%.3f MiB, read=%.3f MiB, write=%.3f MiB.",
            resource_usage.wall_seconds,
            resource_usage.total_cpu_seconds,
            resource_usage.mean_cpu_cores,
            resource_usage.peak_rss_mb,
            resource_usage.read_bytes / (1024.0**2),
            resource_usage.write_bytes / (1024.0**2),
        )
        logger.info("Freezing the stage log before calculating the checksum inventory.")
        close_logger(logger)
        result_summaries = summarise_declared_outputs(
            config=config,
            stage_name=stage_name,
            stage_root=staging,
        )
        outputs_before_report = inventory_files(
            staging,
            frozenset({"stage_manifest.json", "stage_report.html"}),
        )
        runner_wall_seconds = max(0.0, time.monotonic() - started_monotonic)
        interpretation, limitation = stage_interpretation(stage_name)
        summary = {
            "stage": stage_name,
            "status": status,
            "required": stage.required,
            "mode": config.mode,
            "evidence_mode": stage.evidence_mode,
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "runner_wall_seconds": runner_wall_seconds,
            "configuration": str(config.source_path),
            "configuration_digest": config.digest,
            "package_version": __version__,
            "purpose": purpose,
            "rationale": rationale,
            "supported_interpretation": interpretation,
            "scientific_limitation": limitation,
            "dependencies": list(dependencies),
            "control_token": {
                "path": str(control_token),
                "sha256": sha256_file(control_token),
            },
            "resources": {
                "threads": stage.threads,
                "memory_mb": stage.memory_mb,
                "runtime_minutes": stage.runtime_minutes,
            },
            "benchmark": resource_usage.as_record(),
            "execution": execution,
            "validation": {
                "declared_output_count": len(stage.expected_outputs),
                "declared_outputs_validated": True,
                "upstream_manifests_validated": len(dependencies),
            },
            "result_summaries": result_summaries,
            "report": {"path": "report/stage_report.html", "format": "self-contained HTML5"},
            "outputs": outputs_before_report,
        }
        summary["lineage"] = lineage + [
            {
                key: summary[key]
                for key in ("stage", "status", "required", "mode", "evidence_mode")
            }
        ]
        write_stage_report(
            config=config,
            stage_name=stage_name,
            stage_root=staging,
            stage_summary=summary,
            result_summaries=result_summaries,
            output_inventory=outputs_before_report,
        )
        summary["finished_at_utc"] = utc_now()
        summary["runner_wall_seconds"] = max(0.0, time.monotonic() - started_monotonic)
        summary["outputs"] = inventory_files(staging, frozenset({"stage_manifest.json"}))
        atomic_write_json(staging / "stage_manifest.json", summary)
        formal = run_root / stage_name
        if formal.exists():
            superseded = run_root / "superseded" / f"{stage_name}.{uuid.uuid4().hex}"
            superseded.parent.mkdir(parents=True, exist_ok=True)
            os.replace(formal, superseded)
        os.replace(staging, formal)
        return formal / "stage_manifest.json"
    except BaseException:
        if not monitor_stopped:
            try:
                resource_usage, resource_samples = monitor.stop(
                    return_code=stage_return_code or 1,
                    status="failed",
                )
                write_stage_resource_outputs(
                    stage_root=staging,
                    usage=resource_usage,
                    samples=resource_samples,
                )
                logger.error(
                    "Failed-stage resources retained: wall=%.3f s, cpu=%.3f s, "
                    "peak_rss=%.3f MiB.",
                    resource_usage.wall_seconds,
                    resource_usage.total_cpu_seconds,
                    resource_usage.peak_rss_mb,
                )
            except BaseException:
                logger.exception("Could not finalise failed-stage resource measurements.")
        close_logger(logger)
        failed = run_root / "failed" / staging.name
        failed.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.move(str(staging), str(failed))
        raise
