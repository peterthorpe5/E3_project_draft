"""Named-option CLI for resource preparation, comparisons and the local app."""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

from . import __version__
from .core import ComparisonSettings, WorkbenchError, load_project


def build_parser() -> argparse.ArgumentParser:
    """Build the named-option command interface.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    app = sub.add_parser("app", help="Launch the local workbench")
    app.add_argument("--resource", type=Path)
    app.add_argument(
        "--workspace",
        type=Path,
        default=Path.home() / "protein_pocket_workbench_projects",
    )
    app.add_argument("--port", type=int, default=8510)
    app.add_argument("--address", default="127.0.0.1")
    app.add_argument(
        "--enable-jobs",
        action="store_true",
        help="Opt in to analysis workers on the machine hosting this app",
    )
    prepare = sub.add_parser("import", help="Prepare a new portable app resource")
    prepare.add_argument("--input", type=Path, action="append", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--title", default="Protein pocket project")
    prepare.add_argument("--fasta", type=Path)
    prepare.add_argument("--mapping", type=Path)
    prepare.add_argument("--chain", default="")
    prepare.add_argument("--confidence", choices=["plddt", "none"], default="plddt")
    compare = sub.add_parser(
        "compare", help="Fit structures and compare pocket positions"
    )
    compare.add_argument("--resource", type=Path, required=True)
    compare.add_argument("--reference")
    compare.add_argument("--mobile", action="append")
    compare.add_argument("--all-pairs", action="store_true")
    compare.add_argument(
        "--engine",
        choices=["auto", "usalign", "tmalign", "sequence_kabsch"],
        default="auto",
    )
    compare.add_argument("--usalign", default="USalign")
    compare.add_argument("--tmalign", default="TMalign")
    compare.add_argument("--workers", type=int, default=1)
    compare.add_argument("--fit-scope", choices=["paired", "global"], default="paired")
    compare.add_argument("--min-plddt", type=float, default=70)
    compare.add_argument("--min-atoms", type=int, default=12)
    compare.add_argument("--top-pockets", type=int, default=10)
    compare.add_argument("--include-low-confidence-pockets", action="store_true")
    compare.add_argument("--radius", type=float, default=4)
    compare.add_argument("--max-centroid", type=float, default=8)
    compare.add_argument("--min-overlap", type=float, default=0.5)
    compare.add_argument("--min-tm", type=float, default=0.5)
    compare.add_argument("--start", type=int)
    compare.add_argument("--end", type=int)
    compare.add_argument("--timeout", type=int, default=600)
    sequences = sub.add_parser(
        "align", help="Create MSA and optional NJ/bootstrap tree"
    )
    sequences.add_argument("--resource", type=Path, required=True)
    sequences.add_argument("--sequence-id", action="append")
    sequences.add_argument("--engine", choices=["famsa", "mafft"], default="famsa")
    sequences.add_argument("--aligned-fasta", type=Path)
    sequences.add_argument("--newick", type=Path)
    sequences.add_argument("--max-gap", type=float, default=0.5)
    sequences.add_argument("--bootstrap", type=int, default=0)
    sequences.add_argument("--seed", type=int, default=42)
    sequences.add_argument("--threads", type=int, default=4)
    sequences.add_argument("--timeout", type=int, default=3600)
    for action in ("export", "pack", "review"):
        command = sub.add_parser(action)
        command.add_argument("--resource", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    doctor = sub.add_parser("doctor", help="Show execution host and tool availability")
    doctor.add_argument("--resource", type=Path)
    build = sub.add_parser(
        "build", help="HPC batch build of a finished app and review package"
    )
    inputs = build.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--resource", type=Path)
    inputs.add_argument("--input", type=Path, action="append")
    build.add_argument("--output", type=Path)
    build.add_argument("--review-output", type=Path, required=True)
    build.add_argument("--fasta", type=Path)
    build.add_argument("--mapping", type=Path)
    build.add_argument("--title", default="Protein pocket project")
    build.add_argument("--chain", default="")
    build.add_argument("--confidence", choices=["plddt", "none"], default="plddt")
    build.add_argument(
        "--comparison-mode",
        choices=["all_pairs", "reference", "none"],
        default="all_pairs",
    )
    build.add_argument("--reference")
    build.add_argument(
        "--aligner", action="append", choices=["usalign", "tmalign", "sequence_kabsch"]
    )
    build.add_argument("--usalign", default="USalign")
    build.add_argument("--tmalign", default="TMalign")
    build.add_argument("--workers", type=int, default=4)
    build.add_argument("--threads", type=int, default=8)
    build.add_argument("--fit-scope", choices=["global", "paired"], default="global")
    build.add_argument("--min-plddt", type=float, default=0)
    build.add_argument("--min-atoms", type=int, default=12)
    build.add_argument("--top-pockets", type=int, default=5)
    build.add_argument("--confident-only", action="store_true")
    build.add_argument("--start", type=int)
    build.add_argument("--end", type=int)
    build.add_argument("--timeout", type=int, default=600)
    build.add_argument("--bootstrap", type=int, default=100)
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--sequence-engine", choices=["famsa", "mafft"], default="famsa")
    demo = sub.add_parser("demo", help="Create a synthetic validation project")
    demo.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a requested action with visible logging and actionable errors.

    Args:
        argv: Named command-line arguments, or process arguments.

    Returns:
        Exit status: 0 success, 1 error, 2 partial comparison batch.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            from .importing import import_project

            print(
                import_project(
                    sources=args.input,
                    output=args.output,
                    title=args.title,
                    fasta=args.fasta,
                    mapping=args.mapping,
                    chain=args.chain,
                    confidence=args.confidence,
                )
            )
        elif args.command == "app":
            from .importing import import_project

            if not 1 <= args.port <= 65535:
                raise WorkbenchError("Port must be in [1, 65535]")
            workspace = args.workspace.expanduser().resolve()
            environment = dict(os.environ, POCKET_WORKBENCH_WORKSPACE=str(workspace))
            environment["POCKET_WORKBENCH_ALLOW_JOBS"] = (
                "1" if args.enable_jobs else "0"
            )
            if args.resource:
                root = args.resource.expanduser().resolve()
                if not (root / "project.json").is_file():
                    root = import_project(
                        sources=[root],
                        output=workspace / ("imported_" + uuid.uuid4().hex[:12]),
                    )
                load_project(root=root)
                environment["POCKET_WORKBENCH_RESOURCE"] = str(root)
            return subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(Path(__file__).with_name("ui.py")),
                    "--server.port",
                    str(args.port),
                    "--server.address",
                    args.address,
                    "--server.maxUploadSize",
                    "2048",
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                    "--logger.hideWelcomeMessage",
                    "true",
                ],
                env=environment,
            )
        elif args.command == "compare":
            from .comparison import compare_batch

            data = load_project(root=args.resource)
            if args.all_pairs:
                if args.start is not None or args.end is not None:
                    raise WorkbenchError("Use one named reference for domain fitting")
                if args.reference or args.mobile:
                    raise WorkbenchError(
                        "Use --all-pairs on the whole resource, or named"
                        " reference/mobile options"
                    )
                pairs = list(
                    itertools.combinations(
                        [
                            row["sample_id"]
                            for row in data["models"]
                            if row.get("coordinates")
                        ],
                        2,
                    )
                )
            else:
                if not args.reference or not args.mobile:
                    raise WorkbenchError(
                        "Supply --reference and one or more --mobile options"
                    )
                pairs = [(args.reference, mobile) for mobile in args.mobile]
            settings = ComparisonSettings(
                engine=args.engine,
                min_plddt=args.min_plddt,
                min_atoms=args.min_atoms,
                top_pockets=args.top_pockets,
                confident_only=not args.include_low_confidence_pockets,
                radius=args.radius,
                max_centroid=args.max_centroid,
                min_overlap=args.min_overlap,
                min_tm=args.min_tm,
                start=args.start,
                end=args.end,
                timeout=args.timeout,
                fit_scope=args.fit_scope,
            )
            results = compare_batch(
                root=args.resource,
                pairs=pairs,
                settings=settings,
                usalign=args.usalign,
                tmalign=args.tmalign,
                workers=args.workers,
            )
            return 2 if any(row["status"] == "failed" for row in results) else 0
        elif args.command == "align":
            from .sequences import analyse_sequences

            analyse_sequences(
                root=args.resource,
                sequence_ids=args.sequence_id,
                engine=args.engine,
                aligned_fasta=args.aligned_fasta,
                newick=args.newick,
                max_gap=args.max_gap,
                bootstrap=args.bootstrap,
                seed=args.seed,
                threads=args.threads,
                timeout=args.timeout,
            )
        elif args.command == "export":
            from .database import export_tables

            export_tables(root=args.resource, output=args.output)
        elif args.command == "review":
            from .reporting import export_review

            print(export_review(root=args.resource, output=args.output))
        elif args.command == "doctor":
            from .runtime import execution_info

            print(json.dumps(execution_info(root=args.resource), indent=2))
        elif args.command == "build":
            from .building import build_resource

            return build_resource(
                resource=args.resource,
                sources=args.input,
                output=args.output,
                review_output=args.review_output,
                fasta=args.fasta,
                mapping=args.mapping,
                title=args.title,
                chain=args.chain,
                confidence=args.confidence,
                comparison_mode=args.comparison_mode,
                reference=args.reference,
                aligners=args.aligner,
                usalign=args.usalign,
                tmalign=args.tmalign,
                workers=args.workers,
                threads=args.threads,
                bootstrap=args.bootstrap,
                seed=args.seed,
                sequence_engine=args.sequence_engine,
                settings=ComparisonSettings(
                    engine="usalign",
                    fit_scope=args.fit_scope,
                    min_plddt=args.min_plddt,
                    min_atoms=args.min_atoms,
                    top_pockets=args.top_pockets,
                    confident_only=args.confident_only,
                    start=args.start,
                    end=args.end,
                    timeout=args.timeout,
                ),
            )
        elif args.command == "pack":
            from .database import pack_project

            print(pack_project(root=args.resource, output=args.output))
        elif args.command == "demo":
            from .demo import create_demo

            print(create_demo(output=args.output))
    except (ValueError, OSError, RuntimeError) as error:
        logging.getLogger(__name__).error("%s", error)
        return 1
    return 0
