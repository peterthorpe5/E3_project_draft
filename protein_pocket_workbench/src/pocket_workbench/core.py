"""Validated settings and bounded, portable project I/O."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = "1.0"


class WorkbenchError(ValueError):
    """An actionable input, tool or project error."""


@dataclass(frozen=True, kw_only=True)
class ComparisonSettings:
    """Explicit comparison choices retained with every result.

    Attributes:
        engine: usalign or sequence_kabsch; auto selects installed USalign.
        min_plddt: Minimum residue confidence used to fit the structures.
        min_atoms: Minimum C-alpha count for a supported fit.
        top_pockets: Maximum ranked fpocket cavities per model after filtering.
        confident_only: Require the pipeline's local pocket confidence rule.
        quality_screen_only: Also require assessed PAE and cut/context screens.
        radius: Nearest-neighbour residue distance threshold in Angstroms.
        max_centroid: Maximum pocket centroid distance for positional support.
        min_overlap: Minimum symmetric fraction for positional support.
        min_tm: Minimum of the two USalign TM-scores for fold support.
        start: Optional inclusive reference sequence position for domain fitting.
        end: Optional inclusive reference sequence position for domain fitting.
        timeout: External command timeout in seconds.
        fit_scope: paired uses sequence correspondences; global fits independent traces.
        min_residue_match: Mutual-nearest residue Dice required for conservation.
        min_chemical: Chemical-group match fraction required for conservation.
    """

    engine: str = "auto"
    min_plddt: float = 70.0
    min_atoms: int = 12
    top_pockets: int = 10
    confident_only: bool = True
    quality_screen_only: bool = False
    radius: float = 4.0
    max_centroid: float = 8.0
    min_overlap: float = 0.5
    min_tm: float = 0.5
    start: int | None = None
    end: int | None = None
    timeout: int = 600
    fit_scope: str = "paired"
    min_residue_match: float = 0.5
    min_chemical: float = 0.6

    def __post_init__(self) -> None:
        """Reject unsupported engines, non-finite values and invalid bounds."""
        if self.engine not in {"auto", "usalign", "tmalign", "sequence_kabsch"}:
            raise WorkbenchError("Choose auto, usalign, tmalign or sequence_kabsch")
        if self.fit_scope not in {"paired", "global"}:
            raise WorkbenchError("Choose paired or global fit_scope")
        if (
            type(self.confident_only) is not bool
            or type(self.quality_screen_only) is not bool
        ):
            raise WorkbenchError("Pocket screen options must be booleans")
        if self.engine == "sequence_kabsch" and self.fit_scope == "global":
            raise WorkbenchError("Kabsch requires paired sequence correspondences")
        for name in ("min_plddt", "radius", "max_centroid", "min_overlap", "min_tm"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise WorkbenchError(f"{name} must be finite")
        if not 0 <= self.min_plddt <= 100:
            raise WorkbenchError("Minimum pLDDT must be between 0 and 100")
        if self.radius <= 0 or self.max_centroid <= 0:
            raise WorkbenchError("Distance thresholds must be positive")
        if not 0 <= self.min_overlap <= 1 or not 0 <= self.min_tm <= 1:
            raise WorkbenchError("Overlap and TM thresholds must be in [0, 1]")
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1
            for value in (self.min_residue_match, self.min_chemical)
        ):
            raise WorkbenchError(
                "Residue match and chemical thresholds must be in [0, 1]"
            )
        for name, minimum, maximum in (
            ("min_atoms", 3, 10000),
            ("top_pockets", 1, 100),
            ("timeout", 1, 86400),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise WorkbenchError(
                    f"{name} must be an integer in [{minimum}, {maximum}]"
                )
        if (self.start is None) != (self.end is None):
            raise WorkbenchError("Supply both domain start and end, or neither")
        if self.start is not None and (
            type(self.start) is not int
            or type(self.end) is not int
            or not 1 <= self.start <= self.end
        ):
            raise WorkbenchError("Domain positions must be positive and start <= end")


def utc_now() -> str:
    """Return an unambiguous UTC timestamp.

    Returns:
        ISO 8601 UTC time.
    """
    return datetime.now(timezone.utc).isoformat()


def digest_file(*, path: Path) -> str:
    """Hash input bytes without loading a complete structure archive.

    Args:
        path: Readable file.

    Returns:
        SHA-256 hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_id(*, value: str) -> str:
    """Validate a portable model or job identifier.

    Args:
        value: Candidate identifier.

    Returns:
        Unchanged validated identifier.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
        raise WorkbenchError(f"Invalid identifier {value!r}; use 1–120 safe characters")
    return value


def inside(*, root: Path, relative: str) -> Path:
    """Resolve a project-relative path without permitting an escape.

    Args:
        root: Owning project directory.
        relative: Relative filename from project metadata.

    Returns:
        Absolute path inside root.
    """
    path = Path(relative)
    if path.is_absolute() or "\\" in relative:
        raise WorkbenchError("Expected a project-relative path")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise WorkbenchError("A project path escapes its directory")
    return target


def write_json(*, path: Path, value: Any) -> None:
    """Atomically write finite JSON with restrictive temporary file creation.

    Args:
        path: Output path.
        value: JSON-compatible data.
    """
    encoded = json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_tsv(*, path: Path, rows: list[dict], columns: list[str]) -> None:
    """Write an explicitly ordered, header-preserving TSV.

    Args:
        path: Output path.
        rows: Table records.
        columns: Ordered column names.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(row.get(key), ensure_ascii=True)
                        if isinstance(row.get(key), (dict, list))
                        else row.get(key)
                    )
                    for key in columns
                }
            )


def load_project(*, root: Path) -> dict:
    """Read a compatible project without following paths outside its root.

    Args:
        root: Workbench resource directory.

    Returns:
        Validated project data dictionary.
    """
    try:
        data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise WorkbenchError(f"Cannot open workbench project: {root}") from error
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise WorkbenchError(
            "Unsupported workbench schema; import the original run again"
        )
    if not isinstance(data.get("models"), list) or not isinstance(
        data.get("pockets"), list
    ):
        raise WorkbenchError("Project models/pockets are malformed")
    for model in data["models"]:
        safe_id(value=model["sample_id"])
        for key in ("prepared_model", "coordinates"):
            if model.get(key):
                inside(root=root, relative=model[key])
    return data


def settings_record(*, settings: ComparisonSettings) -> dict:
    """Convert validated settings to a provenance record.

    Args:
        settings: Comparison configuration.

    Returns:
        Plain settings dictionary.
    """
    return asdict(settings)
