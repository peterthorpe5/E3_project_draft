"""Shared structural method options for plant and human/plant workflow tasks."""

from __future__ import annotations

import json
from dataclasses import replace

from e3workflow.config import StructuralAlignmentAnalysisConfig
from e3workflow.errors import ConfigurationError


def structural_method_arguments(*, settings: StructuralAlignmentAnalysisConfig) -> tuple[str, ...]:
    """Build explicit optional aligner flags for both structural task routes.

    Args:
        settings: Validated workflow structural-alignment settings.

    Returns:
        CLI options appended to the shared structural component command.
    """
    arguments: list[str] = []
    if not settings.run_usalign:
        arguments.append("--skip-usalign")
    if not settings.run_tmalign:
        arguments.append("--skip-tmalign")
    if settings.run_lolalign:
        arguments.extend(("--run-lolalign", "--foldseek-executable", settings.foldseek_executable))
        if not settings.lolalign_multidomain:
            arguments.append("--lolalign-single-domain")
    return tuple(arguments)


def resolve_structural_methods(
    *, settings: StructuralAlignmentAnalysisConfig, options: str | None,
) -> StructuralAlignmentAnalysisConfig:
    """Apply explicit extension method overrides without changing the parent workflow.

    Args:
        settings: Immutable parent structural settings.
        options: Optional JSON object containing only method selection settings.

    Returns:
        Validated settings with the explicit overrides applied.

    Raises:
        ConfigurationError: If the JSON, method fields or values are invalid.
    """
    if options is None:
        return settings
    try:
        overrides = json.loads(s=options)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Structural method options must be a JSON object") from exc
    allowed = {
        "run_usalign", "run_tmalign", "run_lolalign", "foldseek_executable", "lolalign_multidomain",
    }
    if not isinstance(overrides, dict) or set(overrides) - allowed:
        raise ConfigurationError("Structural method options contain invalid or unknown fields")
    if "foldseek_executable" in overrides:
        executable = overrides["foldseek_executable"]
        if not isinstance(executable, str) or not executable.strip():
            raise ConfigurationError("Foldseek executable must be a non-empty string")
        overrides["foldseek_executable"] = executable.strip()
    return replace(settings, **overrides)
