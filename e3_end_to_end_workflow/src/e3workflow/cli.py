"""Command-line interface for validation, planning, and stage execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from e3workflow.config import STAGE_NAMES, load_config
from e3workflow.errors import WorkflowError
from e3workflow.manifests import validate_accessions, validate_proteomes, validate_shortlist
from e3workflow.runner import execute_stage


def build_parser() -> argparse.ArgumentParser:
    """Build the complete named-option CLI parser."""

    parser = argparse.ArgumentParser(prog="e3-workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "plan"):
        child = subparsers.add_parser(name)
        child.add_argument("--config", type=Path, required=True)
    stage = subparsers.add_parser("run-stage")
    stage.add_argument("--config", type=Path, required=True)
    stage.add_argument("--stage", choices=STAGE_NAMES, required=True)
    stage.add_argument("--verbose", action="store_true")
    return parser


def validate_command(config_path: Path) -> dict[str, object]:
    """Validate configuration and all controlled input manifests."""

    config = load_config(config_path)
    proteomes = validate_proteomes(config.proteomes_manifest, verify_checksums=True)
    seeds = validate_accessions(config.seeds_manifest, {"evidence_type", "source"})
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
        "stages": [
            {
                "name": stage.name,
                "enabled": stage.enabled,
                "required": stage.required,
                "implementation": "external" if stage.command else "internal",
            }
            for stage in config.stages
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and convert expected failures to concise error messages."""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate_command(args.config)
        elif args.command == "plan":
            payload = plan_command(args.config)
        else:
            manifest = execute_stage(load_config(args.config), args.stage, args.verbose)
            payload = {"stage_manifest": str(manifest)}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
