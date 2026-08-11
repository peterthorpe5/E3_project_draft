"""Command-line interface for the E3 structure-guided chemistry package."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from e3chemistry import __version__
from e3chemistry.candidate_manifest import prepare_candidate_manifest_files
from e3chemistry.campaign_config import write_full_universe_config
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
    campaign = subparsers.add_parser(
        "prepare-full-universe-workflow-config",
        help="Generate an immutable upstream full-universe structural config.",
    )
    campaign.add_argument("--template", type=Path, required=True)
    campaign.add_argument("--output", type=Path, required=True)
    campaign.add_argument("--run-name", required=True)
    campaign.add_argument("--parent-run-root", type=Path, required=True)
    campaign.add_argument("--structure-group-limit", type=int, required=True)
    prepare = subparsers.add_parser(
        "prepare-candidate-manifest",
        help="Prepare a reviewable expanded or approved candidate panel.",
    )
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--group-ranking", type=Path, required=True)
    prepare.add_argument("--selected-pockets", type=Path, required=True)
    prepare.add_argument("--pocket-residue-mappings", type=Path, required=True)
    prepare.add_argument("--structure-asset-manifest", type=Path, required=True)
    prepare.add_argument("--ranked-pockets", type=Path)
    prepare.add_argument("--output-dir", type=Path, required=True)
    scope = prepare.add_mutually_exclusive_group(required=True)
    scope.add_argument("--maximum-rank", type=int)
    scope.add_argument("--all-ranked-groups", action="store_true")
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
    run.add_argument("--integrated-evidence", type=Path)
    run.add_argument("--ranked-pockets", type=Path)
    run.add_argument("--structural-alignment-summary", type=Path)
    run.add_argument("--output-dir", type=Path, required=True)
    workflow = subparsers.add_parser(
        "run-workflow-campaign",
        help=(
            "Prepare a checksum-bound all-group candidate manifest from the current "
            "workflow run and execute chemistry without a hand-written panel."
        ),
    )
    workflow.add_argument("--config", type=Path, required=True)
    workflow.add_argument("--group-ranking", type=Path, required=True)
    workflow.add_argument("--selected-pockets", type=Path, required=True)
    workflow.add_argument("--pocket-residue-mappings", type=Path, required=True)
    workflow.add_argument("--pocket-conservation-summary", type=Path, required=True)
    workflow.add_argument("--structure-asset-manifest", type=Path, required=True)
    workflow.add_argument("--ranked-pockets", type=Path)
    workflow.add_argument("--structural-alignment-summary", type=Path)
    workflow.add_argument("--output-dir", type=Path, required=True)
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
        elif args.command == "prepare-full-universe-workflow-config":
            result = write_full_universe_config(
                template_path=args.template,
                output_path=args.output,
                run_name=args.run_name,
                parent_run_root=args.parent_run_root,
                structure_group_limit=args.structure_group_limit,
            )
        elif args.command == "prepare-candidate-manifest":
            config = load_config(args.config)
            result = prepare_candidate_manifest_files(
                config=config,
                group_ranking_path=args.group_ranking,
                selected_pockets_path=args.selected_pockets,
                pocket_residue_mappings_path=args.pocket_residue_mappings,
                structure_asset_manifest_path=args.structure_asset_manifest,
                ranked_pockets_path=args.ranked_pockets,
                output_dir=args.output_dir,
                maximum_rank=(
                    None if args.all_ranked_groups else args.maximum_rank
                ),
                decision_basis=args.decision_basis,
                decided_by=args.decided_by,
                rationale=args.rationale,
            )
        elif args.command == "run-workflow-campaign":
            config = load_config(args.config)
            destination = args.output_dir.expanduser().resolve()
            panel_dir = destination / "provenance" / "candidate_panel"
            preparation = prepare_candidate_manifest_files(
                config=config,
                group_ranking_path=args.group_ranking,
                selected_pockets_path=args.selected_pockets,
                pocket_residue_mappings_path=args.pocket_residue_mappings,
                structure_asset_manifest_path=args.structure_asset_manifest,
                ranked_pockets_path=args.ranked_pockets,
                output_dir=panel_dir,
                maximum_rank=None,
                decision_basis="EXPANDED_COMPUTATIONAL_SCREEN",
                decided_by="end-to-end workflow",
                rationale=(
                    "Complete computational campaign generated from the current "
                    "checksum-bound Stage 08 and Stage 09 authorities."
                ),
            )
            result = run_pipeline(
                config_path=args.config,
                candidate_manifest_path=Path(preparation["candidate_manifest"]),
                group_ranking_path=args.group_ranking,
                selected_pockets_path=args.selected_pockets,
                pocket_residue_mappings_path=args.pocket_residue_mappings,
                pocket_conservation_summary_path=args.pocket_conservation_summary,
                structure_asset_manifest_path=args.structure_asset_manifest,
                ranked_pockets_path=args.ranked_pockets,
                structural_alignment_summary_path=args.structural_alignment_summary,
                output_dir=destination,
            )
            result["candidate_panel"] = preparation
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
                integrated_evidence_path=args.integrated_evidence,
                ranked_pockets_path=args.ranked_pockets,
                structural_alignment_summary_path=(
                    args.structural_alignment_summary
                ),
                output_dir=args.output_dir,
            )
    except ChemistryError as exc:
        LOGGER.error("%s", exc)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
