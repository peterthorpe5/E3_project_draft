"""Detached local workers with persisted requests, statuses and logs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

from .core import (
    ComparisonSettings,
    WorkbenchError,
    load_project,
    utc_now,
    write_json,
    write_tsv,
)
from .runtime import execution_info

LOGGER = logging.getLogger(__name__)


def start_job(*, root: Path, task: str, options: dict) -> str:
    """Launch one detached worker, retaining its request before process creation.

    Args:
        root: Existing resource directory.
        task: compare, sequences, predict or review.
        options: Validated task options for the worker.

    Returns:
        Persistent job identifier.
    """
    import fcntl

    load_project(root=root)
    with (root / ".jobs.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _launch_job(root=root, task=task, options=options)


def _launch_job(*, root: Path, task: str, options: dict) -> str:
    """Create and launch a request while holding the project's job lock.

    Args:
        root: Validated project directory.
        task: Supported worker operation.
        options: Task options.

    Returns:
        Persistent worker identifier.
    """
    if task not in {"compare", "sequences", "predict", "review"}:
        raise WorkbenchError("Unknown background task")
    for status_file in (root / "jobs").glob("*/status.json"):
        status = json.loads(status_file.read_text())
        if status.get("status") in {"queued", "running"}:
            pid = status.get("pid")
            launch_path = status_file.with_name("launch.json")
            if not pid and launch_path.is_file():
                pid = json.loads(launch_path.read_text()).get("pid")
            if pid and status.get("hostname", socket.gethostname()) == (
                socket.gethostname()
            ):
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    status["status"] = "interrupted"
                    write_json(path=status_file, value=status)
                    continue
            raise WorkbenchError(
                "This project already has an active job; review Jobs first"
            )
    identifier = "job_" + uuid.uuid4().hex[:16]
    directory = root / "jobs" / identifier
    directory.mkdir(parents=True)
    request = {
        "job_id": identifier,
        "root": str(root.resolve()),
        "task": task,
        "options": options,
        "execution": execution_info(root=root),
    }
    write_json(path=directory / "request.json", value=request)
    write_json(
        path=directory / "status.json",
        value={
            "job_id": identifier,
            "task": task,
            "status": "queued",
            "started_utc": utc_now(),
            "hostname": socket.gethostname(),
            "execution": request["execution"],
        },
    )
    try:
        with (directory / "worker.log").open("ab") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "pocket_workbench.jobs",
                    "--request",
                    str(directory / "request.json"),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            # Keep the PID even before the child updates its running status.
            # Tests and unusual process launch adapters may not return a process.
            if process is not None:
                write_json(
                    path=directory / "launch.json",
                    value={"pid": process.pid, "hostname": socket.gethostname()},
                )
    except OSError as error:
        write_json(
            path=directory / "status.json",
            value={
                "job_id": identifier,
                "task": task,
                "status": "failed",
                "finished_utc": utc_now(),
                "error": str(error),
            },
        )
        raise WorkbenchError(f"Could not launch worker: {error}") from error
    return identifier


def run_prediction(*, root: Path, options: dict, job_id: str) -> int:
    """Run the bundled original predictors and merge their report into the app.

    Args:
        root: Project resource.
        options: Tool locations, thread count and per-command timeout.
        job_id: Owning job ID, used for a new prediction output directory.

    Returns:
        Original pipeline exit status, including 2 for partial analyses.
    """
    from .database import save_project
    from .importing import read_report

    data = load_project(root=root)
    if not all(model.get("prepared_model") for model in data["models"]):
        raise WorkbenchError(
            "Upload coordinates for all models before predicting pockets"
        )
    if len({row.get("confidence", "plddt") for row in data["models"]}) > 1:
        raise WorkbenchError("Predict one confidence interpretation per project")
    manifest = root / "jobs" / job_id / "prediction_manifest.tsv"
    write_tsv(
        path=manifest,
        rows=[
            {
                "sample_id": model["sample_id"],
                "model_path": str(root / model["prepared_model"]),
                "cluster": model["group_id"],
            }
            for model in data["models"]
        ],
        columns=["sample_id", "model_path", "cluster"],
    )
    output = root / "prediction_runs" / job_id
    command = [
        sys.executable,
        "-m",
        "pocket_workbench._pipeline",
        "run",
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--fpocket",
        options.get("fpocket", "fpocket"),
        "--p2rank",
        options.get("p2rank", "prank"),
        "--threads",
        str(options.get("threads", 4)),
        "--timeout",
        str(options.get("timeout", 3600)),
        "--confidence",
        data["models"][0].get("confidence", "plddt"),
    ]
    status = subprocess.run(command, check=False).returncode
    if status not in {0, 2} or not (output / "report.html").is_file():
        raise WorkbenchError(
            f"Prediction failed with status {status}; inspect worker.log and prediction"
            " logs"
        )
    report = read_report(path=output / "report.html")
    ranks = {(row["sample_id"], row["pocket_id"]): row for row in report["ranked"]}
    data["pockets"] = [
        (
            dict(
                row,
                **{
                    key: value
                    for key, value in ranks.get(
                        (row["sample_id"], row["pocket_id"]), {}
                    ).items()
                    if key not in row
                    or key
                    in {
                        "review_rank",
                        "ranking_basis",
                        "p2rank_rescore_score",
                        "p2rank_rescore_rank",
                        "p2rank_rescore_probability",
                    }
                },
            )
            if row["method"] == "fpocket"
            else row
        )
        for row in report["pockets"]
    ]
    statuses = {row["sample_id"]: row for row in report["samples"]}
    for model in data["models"]:
        for key in (
            "status",
            "error",
            "fpocket_status",
            "p2rank_status",
            "rescore_status",
        ):
            model[key] = statuses[model["sample_id"]].get(key)
    data["source_manifest"] = report["manifest"]
    data["method_runs"] = report["methods"]
    # Comparisons belong to the pocket set that generated them.
    data["comparisons"] = []
    save_project(root=root, data=data)
    return status


def run_job(*, request_path: Path) -> int:
    """Execute a request and always retain a terminal success/failure status.

    Args:
        request_path: Worker request JSON.

    Returns:
        Process exit status.
    """
    request = json.loads(request_path.read_text())
    root = Path(request["root"]).resolve()
    if request_path.resolve().parent.parent != root / "jobs":
        raise WorkbenchError("Job request is outside its owning project")
    status_path = request_path.parent / "status.json"
    status = {
        "job_id": request["job_id"],
        "task": request["task"],
        "status": "running",
        "started_utc": utc_now(),
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "execution": execution_info(root=root),
    }
    write_json(path=status_path, value=status)
    code = 0
    try:
        options = request["options"]
        if request["task"] == "compare":
            from .comparison import compare_batch

            results = compare_batch(
                root=root,
                pairs=[tuple(pair) for pair in options["pairs"]],
                settings=ComparisonSettings(**options["settings"]),
                usalign=options.get("usalign", "USalign"),
            )
            code = 2 if any(result["status"] == "failed" for result in results) else 0
        elif request["task"] == "sequences":
            from .sequences import analyse_sequences

            for key in ("aligned_fasta", "newick"):
                if options.get(key):
                    options[key] = Path(options[key])
            analyse_sequences(root=root, **options)
        elif request["task"] == "predict":
            code = run_prediction(root=root, options=options, job_id=request["job_id"])
        elif request["task"] == "review":
            from .reporting import export_review

            path = export_review(root=root, output=Path(options["output"]))
            status["review_directory"] = str(path)
            status["review_zip"] = str(path.with_suffix(".zip"))
        else:
            raise WorkbenchError("Unknown worker task")
        status["status"] = "partial" if code else "complete"
    except Exception as error:
        LOGGER.exception("Background job failed")
        status.update(status="failed", error=str(error))
        code = 1
    finally:
        status["finished_utc"] = utc_now()
        write_json(path=status_path, value=status)
    return code


def main() -> int:
    """Parse the worker's named request argument and configure persistent logs.

    Returns:
        Worker exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    return run_job(request_path=args.request)


if __name__ == "__main__":
    raise SystemExit(main())
