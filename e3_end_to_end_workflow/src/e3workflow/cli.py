"""Command-line interface for validation, planning, and stage execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from e3workflow import __version__
from e3workflow.benchmarking import aggregate_run_benchmarks
from e3workflow.config import (
    STAGE_NAMES,
    controlled_input_paths,
    load_config,
    stage_ancestors,
    stage_dependencies,
    stage_purpose,
)
from e3workflow.control import initialise_stage_tokens, stage_manifest_target
from e3workflow.diagnostics import (
    diagnose_installation,
    diagnose_slurm_executor,
    require_compatible_slurm_executor,
    require_matching_source,
)
from e3workflow.distributed import (
    run_ligandability_shard,
    run_structural_alignment_shard,
)
from e3workflow.errors import WorkflowError
from e3workflow.fresh import validate_fresh_config
from e3workflow.manifests import validate_proteomes, validate_seed_evidence, validate_shortlist
from e3workflow.reporting import generate_run_report, record_workflow_invocation
from e3workflow.production import cache_domain_annotations
from e3workflow.resources import (
    build_domain_cache_manifest,
    build_expression_manifest,
    build_ligandability_manifest,
)
from e3workflow.runner import execute_stage
from e3workflow.seed_evidence import build_seed_evidence
from e3workflow.sweeps import compare_sweep, prepare_sweep


def build_parser() -> argparse.ArgumentParser:
    """Build the complete named-option CLI parser."""
    parser = argparse.ArgumentParser(prog="e3-workflow")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", type=Path, required=True)
    validate_fresh = subparsers.add_parser("validate-fresh")
    validate_fresh.add_argument("--config", type=Path, required=True)
    validate_fresh.add_argument("--allow-existing-run", action="store_true")
    plan = subparsers.add_parser("plan")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--human", action="store_true")
    control = subparsers.add_parser("control")
    control.add_argument("--config", type=Path, required=True)
    control.add_argument("--force-stage", choices=STAGE_NAMES, action="append", default=[])
    target = subparsers.add_parser("stage-target")
    target.add_argument("--config", type=Path, required=True)
    target.add_argument("--stage", choices=STAGE_NAMES, required=True)
    run_root = subparsers.add_parser("run-root")
    run_root.add_argument("--config", type=Path, required=True)
    stage_range = subparsers.add_parser("validate-range")
    stage_range.add_argument("--start-at", choices=STAGE_NAMES, required=True)
    stage_range.add_argument("--stop-after", choices=STAGE_NAMES, required=True)
    stage = subparsers.add_parser("run-stage")
    stage.add_argument("--config", type=Path, required=True)
    stage.add_argument("--stage", choices=STAGE_NAMES, required=True)
    stage.add_argument("--verbose", action="store_true")
    ligandability_shard = subparsers.add_parser("run-ligandability-shard")
    ligandability_shard.add_argument("--config", type=Path, required=True)
    ligandability_shard.add_argument("--task-index", type=int, required=True)
    structural_shard = subparsers.add_parser("run-structural-alignment-shard")
    structural_shard.add_argument("--config", type=Path, required=True)
    structural_shard.add_argument("--task-index", type=int, required=True)
    benchmarks = subparsers.add_parser("aggregate-benchmarks")
    benchmarks.add_argument("--config", type=Path, required=True)
    benchmarks.add_argument("--output-dir", type=Path)
    report = subparsers.add_parser("generate-report")
    report.add_argument("--config", type=Path, required=True)
    report.add_argument("--output-dir", type=Path)
    invocation = subparsers.add_parser("record-invocation")
    invocation.add_argument("--config", type=Path, required=True)
    invocation.add_argument("workflow_argv", nargs=argparse.REMAINDER)
    evidence = subparsers.add_parser("build-seed-evidence")
    evidence.add_argument("--source", type=Path, required=True)
    evidence.add_argument(
        "--output",
        type=Path,
        default=Path("data/known_e3_seed_evidence.tsv.gz"),
    )
    evidence.add_argument("--provenance-output", type=Path)
    evidence.add_argument("--force", action="store_true")
    domain_cache = subparsers.add_parser("cache-domain-annotations")
    domain_cache.add_argument("--config", type=Path, required=True)
    domain_manifest = subparsers.add_parser("build-domain-cache-manifest")
    domain_manifest.add_argument("--cache-root", type=Path, required=True)
    domain_manifest.add_argument("--output", type=Path, required=True)
    expression_manifest = subparsers.add_parser("build-expression-manifest")
    expression_manifest.add_argument("--expression-root", type=Path, required=True)
    expression_manifest.add_argument("--output", type=Path, required=True)
    ligandability_manifest = subparsers.add_parser("build-ligandability-manifest")
    ligandability_manifest.add_argument("--root", type=Path, action="append", required=True)
    ligandability_manifest.add_argument("--output", type=Path, required=True)
    prepare_sweep_parser = subparsers.add_parser("prepare-sweep")
    prepare_sweep_parser.add_argument("--sweep-config", type=Path, required=True)
    prepare_sweep_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_sweep_parser.add_argument("--force", action="store_true")
    compare_sweep_parser = subparsers.add_parser("compare-sweep")
    compare_sweep_parser.add_argument("--manifest", type=Path, required=True)
    compare_sweep_parser.add_argument("--output-dir", type=Path, required=True)
    compare_sweep_parser.add_argument("--allow-incomplete", action="store_true")
    diagnostics = subparsers.add_parser("diagnose-install")
    diagnostics.add_argument("--source-root", type=Path)
    diagnostics.add_argument("--require-source-match", action="store_true")
    slurm_diagnostics = subparsers.add_parser("diagnose-slurm-executor")
    slurm_diagnostics.add_argument("--require-compatible", action="store_true")
    return parser


def validate_command(config_path: Path) -> dict[str, object]:
    """Validate configuration and all controlled input manifests."""
    config = load_config(config_path)
    input_paths = dict(controlled_input_paths(config))
    proteomes = (
        validate_proteomes(config.proteomes_manifest, verify_checksums=True)
        if "proteomes" in input_paths
        else []
    )
    seeds = validate_seed_evidence(config.seeds_manifest) if "seeds" in input_paths else []
    shortlist = validate_shortlist(config.shortlist_manifest) if "shortlist" in input_paths else []
    return {
        "status": "valid",
        "mode": config.mode,
        "run_root": str(config.run_root),
        "configuration_digest": config.digest,
        "configuration_schema_version": config.schema_version,
        "proteomes": len(proteomes),
        "seeds": len(seeds),
        "shortlist_rows": len(shortlist),
        "controlled_inputs": list(input_paths),
    }


def plan_command(config_path: Path) -> dict[str, object]:
    """Return an execution plan without creating workflow outputs."""
    config = load_config(config_path)
    return {
        "mode": config.mode,
        "run_root": str(config.run_root),
        "production_eligible": config.mode == "production",
        "configuration_schema_version": config.schema_version,
        "tools": config.tool_records(),
        "reporting": {
            "stage_reports": True,
            "complete_run_report": True,
            "preview_rows": config.reporting.preview_rows,
            "max_table_columns": config.reporting.max_table_columns,
            "max_chart_items": config.reporting.max_chart_items,
        },
        "stages": [
            {
                "name": stage.name,
                "purpose": stage_purpose(stage.name)[0],
                "rationale": stage_purpose(stage.name)[1],
                "depends_on": list(stage_dependencies(stage.name)),
                "enabled": stage.enabled,
                "required": stage.required,
                "implementation": "external" if stage.command else "internal",
                "evidence_mode": stage.evidence_mode,
                "threads": stage.threads,
                "memory_mb": stage.memory_mb,
                "runtime_minutes": stage.runtime_minutes,
                "expected_outputs": list(stage.expected_outputs),
            }
            for stage in config.stages
        ],
    }


def render_plan(payload: dict[str, object]) -> str:
    """Render a concise, readable workflow plan for console logs.

    Args:
        payload: Result from :func:`plan_command`.

    Returns:
        Multi-line plain-text plan.
    """
    lines = [
        "E3 end-to-end workflow plan",
        f"Mode: {payload['mode']}",
        f"Run root: {payload['run_root']}",
        "Independent branches are submitted concurrently when their dependencies are complete.",
        (
            "HTML reports: one checksummed report per completed stage and one consolidated "
            "report after the complete DAG."
        ),
        "",
    ]
    stages = payload.get("stages")
    if not isinstance(stages, list):
        raise WorkflowError("Plan payload does not contain a stage list")
    for stage in stages:
        if not isinstance(stage, dict):
            raise WorkflowError("Plan payload contains an invalid stage record")
        dependencies = stage["depends_on"]
        dependency_text = ", ".join(dependencies) if dependencies else "controlled inputs"
        lines.extend(
            [
                f"{stage['name']}",
                f"  Does: {stage['purpose']}",
                f"  Why: {stage['rationale']}",
                f"  Needs: {dependency_text}",
                f"  Evidence mode: {stage['evidence_mode']}",
                (
                    "  Resources: "
                    f"threads={stage['threads']}, memory_mb={stage['memory_mb']}, "
                    f"runtime_minutes={stage['runtime_minutes']}"
                ),
            ]
        )
    return "\n".join(lines)


def validate_stage_range(start_at: str, stop_after: str) -> dict[str, str]:
    """Validate that a start stage contributes to the selected stop target.

    Args:
        start_at: Stage that should be refreshed.
        stop_after: Requested Snakemake target stage.

    Returns:
        Machine-readable valid-range summary.

    Raises:
        WorkflowError: If the start stage is not the target or one of its prerequisites.
    """
    if start_at != stop_after and start_at not in stage_ancestors(stop_after):
        raise WorkflowError(
            f"{start_at} is not a prerequisite of {stop_after}; the requested target would not "
            "execute the refreshed start stage"
        )
    return {"status": "valid", "start_at": start_at, "stop_after": stop_after}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and convert expected failures to concise error messages."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate_command(args.config)
        elif args.command == "validate-fresh":
            payload = validate_fresh_config(
                config_path=args.config,
                allow_existing_run=args.allow_existing_run,
            )
        elif args.command == "plan":
            payload = plan_command(args.config)
            if args.human:
                print(render_plan(payload))
                return 0
        elif args.command == "control":
            payload = initialise_stage_tokens(
                config=load_config(args.config),
                force_stages=args.force_stage,
            )
        elif args.command == "stage-target":
            print(stage_manifest_target(load_config(args.config), args.stage))
            return 0
        elif args.command == "run-root":
            print(load_config(args.config).run_root)
            return 0
        elif args.command == "validate-range":
            payload = validate_stage_range(args.start_at, args.stop_after)
        elif args.command == "run-stage":
            manifest = execute_stage(load_config(args.config), args.stage, args.verbose)
            payload = {"stage_manifest": str(manifest)}
        elif args.command == "run-ligandability-shard":
            payload = run_ligandability_shard(
                config=load_config(args.config),
                task_index=args.task_index,
            )
        elif args.command == "run-structural-alignment-shard":
            payload = run_structural_alignment_shard(
                config=load_config(args.config),
                task_index=args.task_index,
            )
        elif args.command == "aggregate-benchmarks":
            config = load_config(path=args.config)
            payload = aggregate_run_benchmarks(
                config=config,
                output_dir=args.output_dir or config.run_root / "benchmark_summary",
            )
        elif args.command == "generate-report":
            config = load_config(path=args.config)
            payload = generate_run_report(
                config=config,
                output_dir=args.output_dir or config.run_root / "reports",
            )
        elif args.command == "record-invocation":
            payload = record_workflow_invocation(
                config=load_config(path=args.config),
                argv=args.workflow_argv,
            )
        elif args.command == "build-seed-evidence":
            payload = build_seed_evidence(
                source=args.source,
                output=args.output,
                provenance_output=args.provenance_output,
                force=args.force,
            )
        elif args.command == "cache-domain-annotations":
            payload = cache_domain_annotations(config=load_config(args.config))
        elif args.command == "build-domain-cache-manifest":
            destination = build_domain_cache_manifest(
                cache_root=args.cache_root,
                output_path=args.output,
            )
            payload = {"status": "complete", "manifest": str(destination)}
        elif args.command == "build-expression-manifest":
            destination = build_expression_manifest(
                expression_root=args.expression_root,
                output_path=args.output,
            )
            payload = {"status": "complete", "manifest": str(destination)}
        elif args.command == "build-ligandability-manifest":
            destination = build_ligandability_manifest(
                roots=args.root,
                output_path=args.output,
            )
            payload = {"status": "complete", "manifest": str(destination)}
        elif args.command == "prepare-sweep":
            payload = prepare_sweep(
                sweep_config=args.sweep_config,
                output_dir=args.output_dir,
                force=args.force,
            )
        elif args.command == "compare-sweep":
            payload = compare_sweep(
                manifest=args.manifest,
                output_dir=args.output_dir,
                allow_incomplete=args.allow_incomplete,
            )
        elif args.command == "diagnose-install":
            if args.require_source_match:
                if args.source_root is None:
                    raise WorkflowError(
                        "--require-source-match requires --source-root"
                    )
                payload = require_matching_source(source_root=args.source_root)
            else:
                payload = diagnose_installation(source_root=args.source_root)
        elif args.command == "diagnose-slurm-executor":
            payload = (
                require_compatible_slurm_executor()
                if args.require_compatible
                else diagnose_slurm_executor()
            )
        else:
            raise WorkflowError(f"Unsupported command: {args.command}")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
