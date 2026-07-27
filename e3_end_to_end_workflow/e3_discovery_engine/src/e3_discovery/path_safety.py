"""Filesystem path adaptation for external tools with whitespace limitations."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from e3_discovery.exceptions import ConfigurationError
from e3_discovery.io_utils import ensure_parent

LOGGER = logging.getLogger(__name__)
_WHITESPACE_PATTERN = re.compile(r"\s")


@dataclass(frozen=True)
class ExternalToolPathAlias:
    """Describe a whitespace-free alias for one workflow output root.

    Attributes:
        real_root: Canonical workflow output root used by Snakemake and users.
        tool_root: Whitespace-free path presented to the external tool.
        alias_created: Whether ``tool_root`` is a symbolic-link alias rather
            than the original output root.
    """

    real_root: Path
    tool_root: Path
    alias_created: bool

    def map_path(self, path: Path) -> Path:
        """Map a workflow path from the real root to the external-tool root.

        Args:
            path: Path located at or below :attr:`real_root`.

        Returns:
            The equivalent path beneath :attr:`tool_root`. When no alias is
            required, the original canonical path is returned.

        Raises:
            ConfigurationError: If ``path`` is outside the workflow root.
        """

        canonical_path = Path(path).expanduser().absolute()
        canonical_root = self.real_root.expanduser().absolute()
        try:
            relative = canonical_path.relative_to(canonical_root)
        except ValueError as exc:
            raise ConfigurationError(
                f"External-tool path is outside workflow root: {path}"
            ) from exc
        return self.tool_root / relative


def path_contains_whitespace(path: Path) -> bool:
    """Return whether a filesystem path contains any whitespace character.

    Args:
        path: Filesystem path to inspect.

    Returns:
        ``True`` when the string representation contains a whitespace
        character; otherwise ``False``.
    """

    return bool(_WHITESPACE_PATTERN.search(str(path)))


def _default_alias_parent(config_path: Path) -> Path:
    """Choose a persistent whitespace-free parent for path aliases.

    The repository-adjacent ``.e3_path_aliases`` directory is preferred. If
    its own path contains whitespace, a directory below the operating system's
    temporary root is used instead.

    Args:
        config_path: Workflow configuration path used to locate the repository.

    Returns:
        A whitespace-free alias-parent path that is not resolved through any
        symbolic links.

    Raises:
        ConfigurationError: If neither the repository-adjacent nor temporary
            candidate is whitespace-free.
    """

    config = Path(config_path).expanduser().absolute()
    repository_candidate = config.parent.parent / ".e3_path_aliases"
    if not path_contains_whitespace(repository_candidate):
        return repository_candidate
    temporary_candidate = (
        Path(tempfile.gettempdir()).expanduser().absolute()
        / "e3_discovery_path_aliases"
    )
    if path_contains_whitespace(temporary_candidate):
        raise ConfigurationError(
            "Could not identify a whitespace-free directory for external-tool "
            "path aliases"
        )
    return temporary_candidate


def _resolve_alias_parent(
    config_path: Path,
    configured_parent: Optional[str],
) -> Path:
    """Resolve and validate the parent directory used for path aliases.

    Args:
        config_path: Workflow configuration path used for relative resolution.
        configured_parent: Optional user-supplied alias parent. Relative values
            are interpreted relative to the configuration directory.

    Returns:
        Absolute, whitespace-free alias-parent path.

    Raises:
        ConfigurationError: If a configured or inferred path contains
            whitespace.
    """

    if configured_parent is None or not str(configured_parent).strip():
        parent = _default_alias_parent(config_path)
    else:
        parent = Path(str(configured_parent)).expanduser()
        if not parent.is_absolute():
            parent = Path(config_path).expanduser().absolute().parent / parent
        parent = Path(os.path.abspath(parent))
    if path_contains_whitespace(parent):
        raise ConfigurationError(
            "diamond.path_alias_root must not contain whitespace: "
            f"{parent}"
        )
    return parent


def _alias_name(real_root: Path) -> str:
    """Create a deterministic, filesystem-safe alias name for an output root.

    Args:
        real_root: Canonical workflow output root.

    Returns:
        A name containing a stable SHA-256 prefix derived from ``real_root``.
    """

    digest = hashlib.sha256(
        os.fsencode(str(real_root.expanduser().absolute()))
    ).hexdigest()[:16]
    return f"run_{digest}"


def prepare_external_tool_path_alias(
    real_root: Path,
    config_path: Path,
    configured_parent: Optional[str] = None,
) -> ExternalToolPathAlias:
    """Create or reuse a whitespace-free alias for a workflow output root.

    DIAMOND 2.2.x clustering can internally split database-related paths at
    whitespace even when Python passes an argument vector without a shell. If
    the workflow root contains whitespace, this function creates a persistent
    symbolic link from a safe path to the real output directory. All DIAMOND
    input and output paths can then be expressed beneath that alias while files
    remain physically stored in the configured result directory.

    Args:
        real_root: Workflow output root used by Snakemake and downstream code.
        config_path: Workflow YAML path, used to locate a default alias parent.
        configured_parent: Optional ``diamond.path_alias_root`` override.

    Returns:
        An :class:`ExternalToolPathAlias` describing the real and tool paths.

    Raises:
        ConfigurationError: If the alias parent contains whitespace, an
            existing alias is not a symbolic link, or an existing symbolic link
            points to a different workflow root.
        OSError: If the output root, alias directory or symbolic link cannot be
            created.
    """

    canonical_root = Path(real_root).expanduser().absolute()
    canonical_root.mkdir(parents=True, exist_ok=True)
    if not path_contains_whitespace(canonical_root):
        return ExternalToolPathAlias(
            real_root=canonical_root,
            tool_root=canonical_root,
            alias_created=False,
        )

    alias_parent = _resolve_alias_parent(config_path, configured_parent)
    alias_parent.mkdir(parents=True, exist_ok=True)
    alias = alias_parent / _alias_name(canonical_root)

    if os.path.lexists(alias):
        if not alias.is_symlink():
            raise ConfigurationError(
                f"External-tool path alias exists but is not a symlink: {alias}"
            )
        if alias.resolve() != canonical_root.resolve():
            raise ConfigurationError(
                "External-tool path alias points to a different output root: "
                f"{alias} -> {alias.resolve()}"
            )
    else:
        alias.symlink_to(canonical_root, target_is_directory=True)
        LOGGER.info(
            "Created whitespace-free external-tool path alias: %s -> %s",
            alias,
            canonical_root,
        )

    return ExternalToolPathAlias(
        real_root=canonical_root,
        tool_root=alias,
        alias_created=True,
    )


def write_path_alias_record(
    destination: Path,
    alias: ExternalToolPathAlias,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Write a JSON provenance record for an external-tool path mapping.

    Args:
        destination: JSON file to create or replace.
        alias: Real-to-tool root mapping used for the workflow stage.
        metadata: Optional additional JSON-serialisable provenance values.

    Returns:
        The written destination path.

    Raises:
        OSError: If the destination cannot be created or written.
        TypeError: If ``metadata`` contains non-serialisable values.
    """

    payload = {
        "real_root": str(alias.real_root),
        "tool_root": str(alias.tool_root),
        "alias_created": alias.alias_created,
        "reason": (
            "DIAMOND clustering path contains whitespace"
            if alias.alias_created
            else "No path alias required"
        ),
    }
    if metadata:
        payload.update(dict(metadata))
    output = ensure_parent(Path(destination))
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output
