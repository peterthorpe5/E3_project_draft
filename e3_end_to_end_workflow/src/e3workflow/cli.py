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
    load_config,
    stage_ancestors,
    stage_dependencies,
    stage_purpose,
)
from e3workflow.control import initialise_stage_tokens, stage_manifest_target
from e3workflow.errors import WorkflowError
from e3workflow.manifests import validate_proteomes, validate_seed_evidence, validate_shortlist
from e3workflow.reporting import generate_run_report, record_workflow_invocation
from e3workflow.runner import execute_stage
from e3workflow.seed_evidence import build_seed_evidence


def build_parser() -> argparse.ArgumentParser:
    """Build the complete named-option CLI parser."""
    parser = argparse.ArgumentParser(prog="e3-workflow")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", type=Path, required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--human", action="store_true")
    control = subparsers.add_parser("control")
    control.add_argument("--config", type=Path, required=True)
    control.add_argument("--force-stage", choices=STAGE_NAMES, action="append", default=[])
    target = subparsers.add_parser("stage-target")
    target.add_argument("--config", type=Path, required=True)
    target.add_argument("--stage", choices=STAGE_NAMES, required=True)
    stage_range = subparsers.add_parser("validate-range")
    stage_range.add_argument("--start-at", choices=STAGE_NAMES, required=True)
    stage_range.add_argument("--stop-after", choices=STAGE_NAMES, required=True)
    stage = subparsers.add_parser("run-stage")
    stage.add_argument("--config", type=Path, required=True)
    stage.add_argument("--stage", choices=STAGE_NAMES, required=True)
    stage.add_argument("--verbose", action="store_true")
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
    return parser


def validate_command(config_path: Path) -> dict[str, object]:
    """Validate configuration and all controlled input manifests."""
    config = load_config(config_path)
    proteomes = validate_proteomes(config.proteomes_manifest, verify_checksums=True)
    seeds = validate_seed_evidence(config.seeds_manifest)
    shortlist = validate_shortlist(config.shortlist_manifest)
    return {
        "status": "valid",
        "mode": config.mode,
        "run_root": str(config.run_root),
        "configuration_digest": config.digest,
        "proteomes": len(proteomes),
        "seeds": len(seeds),
        "shortlist_rows": len(shortlist),
    }


def plan_command(config_path: Path) -> dict[str, object]:
    """Return an execution plan without creating workflow outputs."""
    config = load_config(config_path)
    return {
        "mode": config.mode,
        "run_root": str(config.run_root),
        "production_eligible": config.mode == "production",
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
        elif args.command == "validate-range":
            payload = validate_stage_range(args.start_at, args.stop_after)
        elif args.command == "run-stage":
            manifest = execute_stage(load_config(args.config), args.stage, args.verbose)
            payload = {"stage_manifest": str(manifest)}
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
        else:
            raise WorkflowError(f"Unsupported command: {args.command}")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
