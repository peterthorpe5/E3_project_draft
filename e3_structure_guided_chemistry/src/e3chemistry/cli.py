"""Command-line interface for the E3 structure-guided chemistry package."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from e3chemistry import __version__
from e3chemistry.candidate_manifest import prepare_candidate_manifest_files
from e3chemistry.config import load_config
from e3chemistry.errors import ChemistryError
from e3chemistry.pipeline import run_pipeline

LOGGER = logging.getLogger("e3chemistry")


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="e3-chemistry",
        description=(
            "Open-source E3 structure-guided pharmacophore workflow with no "
            "commercial-licence tools."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config", help="Validate YAML and licence policy.")
    validate.add_argument("--config", type=Path, required=True)
    prepare = subparsers.add_parser(
        "prepare-candidate-manifest",
        help="Prepare a reviewable expanded or approved candidate panel.",
    )
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--group-ranking", type=Path, required=True)
    prepare.add_argument("--selected-pockets", type=Path, required=True)
    prepare.add_argument("--pocket-residue-mappings", type=Path, required=True)
    prepare.add_argument("--structure-asset-manifest", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--maximum-rank", type=int, default=200)
    prepare.add_argument(
        "--decision-basis",
        choices=("EXPANDED_COMPUTATIONAL_SCREEN", "PROJECT_LEAD_APPROVED"),
        required=True,
    )
    prepare.add_argument("--decided-by", required=True)
    prepare.add_argument("--rationale", required=True)
    run = subparsers.add_parser("run", help="Run the complete open chemistry workflow.")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--candidate-manifest", type=Path, required=True)
    run.add_argument("--group-ranking", type=Path, required=True)
    run.add_argument("--selected-pockets", type=Path, required=True)
    run.add_argument("--pocket-residue-mappings", type=Path, required=True)
    run.add_argument("--pocket-conservation-summary", type=Path, required=True)
    run.add_argument("--structure-asset-manifest", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s",
    )
    try:
        if args.command == "validate-config":
            config = load_config(args.config)
            result = {
                "status": "valid",
                "method": config.method_name,
                "configuration_digest": config.digest,
                "fragment_screening_mode": config.fragment_screening_mode,
                "restricted_licence_tools_allowed": (
                    config.allow_restricted_licence_tools
                ),
            }
        elif args.command == "prepare-candidate-manifest":
            config = load_config(args.config)
            result = prepare_candidate_manifest_files(
                config=config,
                group_ranking_path=args.group_ranking,
                selected_pockets_path=args.selected_pockets,
                pocket_residue_mappings_path=args.pocket_residue_mappings,
                structure_asset_manifest_path=args.structure_asset_manifest,
                output_dir=args.output_dir,
                maximum_rank=args.maximum_rank,
                decision_basis=args.decision_basis,
                decided_by=args.decided_by,
                rationale=args.rationale,
            )
        else:
            result = run_pipeline(
                config_path=args.config,
                candidate_manifest_path=args.candidate_manifest,
                group_ranking_path=args.group_ranking,
                selected_pockets_path=args.selected_pockets,
                pocket_residue_mappings_path=args.pocket_residue_mappings,
                pocket_conservation_summary_path=(
                    args.pocket_conservation_summary
                ),
                structure_asset_manifest_path=args.structure_asset_manifest,
                output_dir=args.output_dir,
            )
    except ChemistryError as exc:
        LOGGER.error("%s", exc)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
