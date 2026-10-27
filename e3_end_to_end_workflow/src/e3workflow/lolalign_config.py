"""Prepare an isolated LoL-align workflow configuration from an existing run YAML."""

from __future__ import annotations

import argparse
import copy
import logging
import re
from pathlib import Path
from typing import Sequence

import yaml

from e3workflow.config import load_config
from e3workflow.errors import WorkflowError

LOGGER = logging.getLogger(__name__)
METHODS = {
    "alongside": (True, True, True),
    "replace-tmalign": (True, False, True),
    "lolalign-only": (False, False, True),
}


def prepare_lolalign_config(
    *, source_config: Path, output_config: Path, run_name: str,
    mode: str = "alongside", foldseek_executable: str = "foldseek",
    structure_group_limit: int | None = None,
) -> Path:
    """Write a validated new-run YAML without changing the source configuration.

    Args:
        source_config: Existing complete workflow YAML.
        output_config: New YAML in the source directory, preserving relative paths.
        run_name: New run name; must differ from the source run.
        mode: Add LoL-align, replace TM-align, or use LoL-align alone.
        foldseek_executable: LoL-enabled Foldseek binary name or absolute path.
        structure_group_limit: Optional new group limit; None preserves the source limit.

    Returns:
        Absolute path of the new validated configuration.

    Raises:
        ValueError: If the mode, paths or new run name are invalid.
        FileExistsError: If the destination already exists.
        WorkflowError: If either workflow configuration is invalid.
        OSError: If the YAML cannot be read or written.
    """
    source = source_config.expanduser().resolve(strict=True)
    destination = output_config.expanduser().resolve()
    if source == destination or source.parent != destination.parent:
        raise ValueError("Write a new YAML beside the source YAML to preserve relative paths")
    if mode not in METHODS or not foldseek_executable.strip():
        raise ValueError("Invalid LoL-align mode or Foldseek executable")
    if structure_group_limit is not None and (
        isinstance(structure_group_limit, bool) or not isinstance(structure_group_limit, int)
        or structure_group_limit < 1
    ):
        raise ValueError("structure_group_limit must be a positive integer")
    if not re.fullmatch(pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", string=run_name):
        raise ValueError("run_name must be a safe, non-empty directory name")
    previous = load_config(path=source)
    if run_name == previous.run_name:
        raise ValueError("LoL-align comparison requires a new run name")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    data = copy.deepcopy(raw)
    data["run"]["name"] = run_name
    structural = data.setdefault("analysis", {}).setdefault("structural_alignment", {})
    usalign, tmalign, lolalign = METHODS[mode]
    structural.update(
        run_usalign=usalign, run_tmalign=tmalign, run_lolalign=lolalign,
        foldseek_executable=foldseek_executable.strip(),
    )
    if structure_group_limit is not None:
        data["analysis"].setdefault("prioritisation", {})["structure_group_limit"] = (
            structure_group_limit
        )
    payload = yaml.safe_dump(data=data, sort_keys=False, default_flow_style=False)
    with destination.open(mode="x", encoding="utf-8") as handle:
        handle.write(payload)
    try:
        load_config(path=destination)
    except (WorkflowError, ValueError, OSError):
        destination.unlink(missing_ok=True)
        raise
    LOGGER.info("Prepared %s LoL-align run %s: %s", mode, run_name, destination)
    return destination


def main(*, argv: Sequence[str] | None = None) -> int:
    """Prepare a new LoL-align configuration using named CLI arguments.

    Args:
        argv: Optional command-line arguments for testing.

    Returns:
        Zero on success, or two for a configuration or filesystem error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", required=True, type=Path)
    parser.add_argument("--output-config", required=True, type=Path)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--mode", choices=tuple(METHODS), default="alongside")
    parser.add_argument("--foldseek-executable", default="foldseek")
    parser.add_argument("--structure-group-limit", type=int)
    args = parser.parse_args(args=argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        output = prepare_lolalign_config(
            source_config=args.source_config, output_config=args.output_config,
            run_name=args.run_name, mode=args.mode, foldseek_executable=args.foldseek_executable,
            structure_group_limit=args.structure_group_limit,
        )
    except (WorkflowError, ValueError, OSError, yaml.YAMLError) as exc:
        LOGGER.error("Could not prepare LoL-align configuration: %s", exc)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
