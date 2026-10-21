"""Generic command-line submission, installation checks and queue workers."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Sequence

from .common import ResearchConfig, ResearchError, bounded_number, load_config
from .jobs import OPERATIONS, cancel_job, get_job, list_jobs, submit_job
from .runner import run_next_job


def build_parser() -> argparse.ArgumentParser:
    """Build the generic research CLI with named data and resource controls.

    Returns:
        Parser for submission, workers, queue inspection and standalone UI.
    """
    parser = argparse.ArgumentParser(prog="protein-research-workbench")
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect configured data and optional executables")
    commands.add_parser("jobs", help="List recent queue status as JSON")
    cancel = commands.add_parser("cancel", help="Cancel one queued job")
    cancel.add_argument("--job-id", required=True)
    submit = commands.add_parser("submit", help="Queue work without blocking the web process")
    submit.add_argument("--operation", choices=sorted(OPERATIONS), required=True)
    submit.add_argument(
        "--parameters", type=Path, help="JSON object containing scientific controls"
    )
    submit.add_argument("--fasta", type=Path)
    worker = commands.add_parser("worker", help="Execute queued work on a local or HPC worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--job-id")
    worker.add_argument("--poll-seconds", type=float, default=5)
    worker.add_argument(
        "--max-jobs", type=int, default=0, help="Zero keeps polling until interrupted"
    )
    serve = commands.add_parser("serve", help="Launch the generic UI without E3 resource inputs")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8503)
    return parser


def installation_status(*, config: ResearchConfig) -> dict[str, object]:
    """Inspect prerequisites without downloading databases or invoking prediction providers.

    Args:
        config: Operator profile.

    Returns:
        Paths and availability; missing optional tools disable only their own workflows.
    """
    return {
        "workspace": str(config.workspace),
        "data": {
            name: {
                "configured": bool(getattr(config, name)),
                "exists": Path(getattr(config, name)).is_file() if getattr(config, name) else False,
            }
            for name in (
                "index",
                "sequences",
                "sequence_map",
                "taxonomy",
                "cluster_taxonomy",
                "centroid_database",
            )
        },
        "executables": {
            name: shutil.which(getattr(config, name))
            for name in ("diamond", "mafft", "fasttree", "interproscan", "emapper")
        },
        "local_folding_dependencies": all(
            importlib.util.find_spec(name) is not None for name in ("torch", "transformers")
        ),
        "dedicated_folding_endpoint": bool(config.esm_endpoint),
        "auspice_url": config.auspice_url or None,
    }


def work_queue(
    *,
    config: ResearchConfig,
    once: bool = False,
    job_id: str | None = None,
    poll_seconds: float = 5,
    maximum_jobs: int = 0,
) -> int:
    """Execute a bounded or persistent worker, returning a failing status for failed jobs.

    Args:
        config: Trusted worker profile, shared with the submitting UI.
        once: Process at most one queued job and return.
        job_id: Optional exact queued job, also implies one execution.
        poll_seconds: Queue polling interval, at most 30 seconds.
        maximum_jobs: Stop after this many executed jobs; zero is unlimited.

    Returns:
        Zero on successful/empty work, one if a job failed.
    """
    pause = bounded_number(value=poll_seconds, label="Polling interval", minimum=0.1, maximum=30)
    maximum = bounded_number(
        value=maximum_jobs, label="Maximum jobs", minimum=0, maximum=1_000_000, integer=True
    )
    count, failed = 0, False
    while True:
        completed = run_next_job(config=config, job_id=job_id)
        if completed:
            status = get_job(workspace=config.workspace, job_id=completed)
            print(json.dumps(status), flush=True)
            count += 1
            failed = failed or status["status"] == "FAILED"
        if once or job_id or (maximum and count >= maximum):
            return int(failed)
        time.sleep(pause)


def main(*, argv: Sequence[str] | None = None) -> int:
    """Validate named inputs and run the requested generic workflow command.

    Args:
        argv: Optional explicit arguments for tests and embedding.

    Returns:
        Process exit code; no Git operations or remote jobs are initiated implicitly.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        config = load_config(path=args.config)
        if args.command == "doctor":
            print(json.dumps(installation_status(config=config), indent=2))
        elif args.command == "jobs":
            print(json.dumps(list_jobs(workspace=config.workspace), indent=2))
        elif args.command == "cancel":
            cancel_job(workspace=config.workspace, job_id=args.job_id)
        elif args.command == "submit":
            parameters = (
                json.loads(args.parameters.read_text(encoding="utf-8")) if args.parameters else {}
            )
            if not isinstance(parameters, dict):
                raise ResearchError("Parameters file must contain a JSON object")
            if args.fasta and args.fasta.stat().st_size > 20_000_000:
                raise ResearchError(
                    "FASTA upload exceeds 20 MB; use a completed retrieval artifact"
                )
            fasta = args.fasta.read_text(encoding="utf-8") if args.fasta else None
            print(
                submit_job(
                    workspace=config.workspace,
                    operation=args.operation,
                    parameters=parameters,
                    fasta=fasta,
                )
            )
        elif args.command == "worker":
            return work_queue(
                config=config,
                once=args.once,
                job_id=args.job_id,
                poll_seconds=args.poll_seconds,
                maximum_jobs=args.max_jobs,
            )
        elif args.command == "serve":
            port = bounded_number(
                value=args.port, label="Port", minimum=1, maximum=65535, integer=True
            )
            if not args.host or any(character.isspace() for character in args.host):
                raise ResearchError("Host must be non-empty without whitespace")
            environment = os.environ.copy()
            if args.config:
                environment["E3_RESEARCH_CONFIG"] = str(args.config.expanduser().resolve())
            return subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(Path(__file__).with_name("standalone.py")),
                    "--server.address",
                    args.host,
                    "--server.port",
                    str(port),
                    "--server.headless",
                    "true",
                ],
                env=environment,
            )
    except KeyboardInterrupt:
        return 130
    except (ResearchError, OSError, ValueError) as exc:
        logging.getLogger(__name__).error("Research command failed: %s", exc)
        return 2
    return 0
