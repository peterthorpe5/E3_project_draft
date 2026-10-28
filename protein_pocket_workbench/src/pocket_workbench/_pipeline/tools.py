"""External commands, process-group timeouts and tool identity capture."""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .io import sha256_file, write_json
from .models import Settings

LOGGER = logging.getLogger(__name__)


def resolve_executable(*, value: str) -> Path:
    """Resolve a command without invoking a shell.

    Args:
        value: PATH command name or explicit executable path.

    Returns:
        Absolute executable path.
    """
    located = shutil.which(cmd=os.path.expanduser(value))
    if located is None:
        raise ValueError(f"Executable not found: {value}. See docs/INSTALLATION.md")
    return Path(located).absolute()


def inspect_tools(*, fpocket: str, p2rank: str, settings: Settings) -> dict:
    """Capture and check executable versions and P2Rank model assets.

    Args:
        fpocket: fpocket executable.
        p2rank: P2Rank prank executable.
        settings: Required version and selected profiles.

    Returns:
        JSON-compatible identity used in provenance and resume fingerprints.
    """
    result = {}
    for name, value, flag in (("fpocket", fpocket, "-h"), ("p2rank", p2rank, "-v")):
        executable = resolve_executable(value=value)
        completed = subprocess.run(
            args=[str(executable), flag],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()
        if name == "p2rank" and (
            completed.returncode != 0 or settings.required_p2rank not in output
        ):
            raise ValueError(
                f"P2Rank version check failed (expected {settings.required_p2rank!r}); "
                f"{output[:600]}"
            )
        if name == "fpocket" and not output:
            raise ValueError("fpocket -h produced no identifiable tool output")
        result[name] = {
            "executable": str(executable),
            "sha256": sha256_file(path=executable),
            "version_command": [str(executable), flag],
            "return_code": completed.returncode,
            "version_output": output,
        }
    # Real P2Rank installations place configs/models beside prank. Capture
    # selected model weights as well as the launcher, not just its filename.
    root = Path(result["p2rank"]["executable"]).resolve().parent
    assets = (
        set(root.glob("bin/*.jar"))
        | set(root.glob("lib/*.jar"))
        | set(root.glob("bin/lib/*.jar"))
        | set(root.glob("config/*.groovy"))
        | set(root.glob("models/_score_transform/**/*.json"))
    )
    for profile in (settings.predict_config, settings.rescore_config):
        config = root / "config" / f"{profile}.groovy"
        if config.is_file():
            assets.add(config)
        weights = root / "models" / profile
        if weights.is_dir():
            assets.update(path for path in weights.rglob("*") if path.is_file())
    result["p2rank"]["assets"] = {
        str(path.relative_to(root)): sha256_file(path=path) for path in sorted(assets)
    }
    return result


def run_command(
    *, command: list[str], cwd: Path, log_prefix: Path, timeout: float
) -> dict:
    """Run one process tree with persistent command, stdout and stderr records.

    Args:
        command: Executable and arguments, passed directly without a shell.
        cwd: Tool-specific working directory.
        log_prefix: Output prefix for .stdout.log, .stderr.log and .command.json.
        timeout: Timeout in seconds, including child Java processes.

    Returns:
        Command provenance on success.

    Raises:
        RuntimeError: For non-zero exit or timeout, with log paths.
    """
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = log_prefix.with_suffix(".stdout.log")
    stderr_path = log_prefix.with_suffix(".stderr.log")
    record = {"argv": command, "cwd": str(cwd), "return_code": None, "timeout": False}
    started = time.monotonic()
    LOGGER.info("Running %s", shlex.join(command))
    with (
        stdout_path.open(mode="w", encoding="utf-8") as stdout,
        stderr_path.open(mode="w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            args=command,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            record["timeout"] = isinstance(error, subprocess.TimeoutExpired)
            if isinstance(error, KeyboardInterrupt):
                raise
        finally:
            record["return_code"] = process.returncode
            record["elapsed_seconds"] = time.monotonic() - started
            write_json(path=log_prefix.with_suffix(".command.json"), data=record)
    if record["timeout"] or process.returncode != 0:
        raise RuntimeError(
            f"{'Timeout' if record['timeout'] else 'Tool failure'} "
            f"(exit {process.returncode}); see {stderr_path} and {stdout_path}"
        )
    return record
