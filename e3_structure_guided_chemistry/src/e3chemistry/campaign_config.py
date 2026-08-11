"""Generate an immutable full-universe upstream structural-run configuration."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from e3chemistry.errors import InputValidationError


def _mapping(value: Any, label: str) -> dict[str, Any]:
    """Return a mutable string-keyed mapping or fail closed."""
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise InputValidationError(f"{label} must be a string-keyed mapping")
    return dict(value)


def build_full_universe_config(
    *,
    template: Mapping[str, Any],
    run_name: str,
    parent_run_root: Path,
    structure_group_limit: int,
) -> dict[str, Any]:
    """Return a full-universe workflow configuration derived from a template.

    Args:
        template: Validated-like end-to-end workflow configuration mapping.
        run_name: New immutable run name.
        parent_run_root: Completed corrected-expression parent run.
        structure_group_limit: Number of Stage 08 groups to send to structure.

    Returns:
        A modified configuration mapping for a new upstream structural campaign.

    Raises:
        InputValidationError: If required sections or safe scalar values are
            absent.
    """
    if not run_name.strip() or any(character.isspace() for character in run_name):
        raise InputValidationError("run_name must be non-empty and contain no spaces")
    if structure_group_limit < 1 or structure_group_limit > 10000:
        raise InputValidationError(
            "structure_group_limit must be between 1 and 10000"
        )
    source_parent = parent_run_root.expanduser().resolve()
    root = dict(template)
    run = _mapping(root.get("run"), "run")
    analysis = _mapping(root.get("analysis"), "analysis")
    prioritisation = _mapping(
        analysis.get("prioritisation"), "analysis.prioritisation"
    )
    stages = _mapping(root.get("stages"), "stages")
    ligandability = _mapping(stages.get("09_ligandability"), "09_ligandability")
    structural = _mapping(
        stages.get("09b_structural_alignment"), "09b_structural_alignment"
    )
    run["name"] = run_name.strip()
    run["parent_run_root"] = str(source_parent)
    prioritisation["structure_group_limit"] = structure_group_limit
    prioritisation["final_candidate_limit"] = min(structure_group_limit, 200)
    ligandability.update(
        {"enabled": True, "required": True, "evidence_mode": "generate"}
    )
    structural.update(
        {"enabled": True, "required": True, "evidence_mode": "generate"}
    )
    if "09c_computational_chemistry" in stages:
        chemistry = _mapping(
            stages["09c_computational_chemistry"],
            "09c_computational_chemistry",
        )
        chemistry.update(
            {"enabled": False, "required": False, "evidence_mode": "disabled"}
        )
        stages["09c_computational_chemistry"] = chemistry
    stages["09_ligandability"] = ligandability
    stages["09b_structural_alignment"] = structural
    analysis["prioritisation"] = prioritisation
    root["run"] = run
    root["analysis"] = analysis
    root["stages"] = stages
    return root


def write_full_universe_config(
    *,
    template_path: Path,
    output_path: Path,
    run_name: str,
    parent_run_root: Path,
    structure_group_limit: int,
) -> dict[str, Any]:
    """Write or verify one immutable generated workflow configuration."""
    source = template_path.expanduser().resolve()
    destination = output_path.expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise InputValidationError(f"Workflow template is missing or empty: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InputValidationError(f"Could not read workflow template: {exc}") from exc
    template = _mapping(raw, "workflow template")
    generated = build_full_universe_config(
        template=template,
        run_name=run_name,
        parent_run_root=parent_run_root,
        structure_group_limit=structure_group_limit,
    )
    configured_path_base = template.get("path_base")
    if configured_path_base is None:
        effective_path_base = source.parent
    elif isinstance(configured_path_base, str) and configured_path_base.strip():
        candidate_path_base = Path(configured_path_base).expanduser()
        effective_path_base = (
            candidate_path_base.resolve()
            if candidate_path_base.is_absolute()
            else (source.parent / candidate_path_base).resolve()
        )
    else:
        raise InputValidationError("workflow template path_base must be a path string")
    generated["path_base"] = str(effective_path_base)
    content = yaml.safe_dump(generated, sort_keys=False)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if destination.exists():
        if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
            raise InputValidationError(
                f"Generated workflow configuration conflicts with existing file: {destination}"
            )
        status = "unchanged"
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.partial")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
        status = "created"
    return {
        "status": status,
        "output": str(destination),
        "sha256": digest,
        "run_name": run_name,
        "structure_group_limit": structure_group_limit,
    }
