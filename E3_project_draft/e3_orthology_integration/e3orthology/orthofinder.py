"""Streaming OrthoFinder result discovery and membership parsing."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import InputValidationError
from .identifiers import ParsedIdentifier, parse_identifier
from .io_utils import ensure_readable_file

csv.field_size_limit(sys.maxsize)


@dataclass(frozen=True)
class MembershipRecord:
    """One raw protein identifier in an OrthoFinder group and species cell."""

    record_type: str
    group_id: str
    orthogroup_id: str
    gene_tree_parent_clade: str
    species: str
    parsed: ParsedIdentifier
    source_file: str
    source_row: int

    def to_record(self) -> dict[str, str | int | None]:
        """Return a flat portable membership record.

        Returns:
            Membership and parsed-identifier fields.
        """

        return {
            "record_type": self.record_type,
            "group_id": self.group_id,
            "orthogroup_id": self.orthogroup_id,
            "gene_tree_parent_clade": self.gene_tree_parent_clade,
            "species": self.species,
            **self.parsed.to_record(),
            "source_file": self.source_file,
            "source_row": self.source_row,
        }


def discover_results_directory(*, source_root: Path, expected_name: str) -> Path:
    """Resolve one exact OrthoFinder results directory below a source root.

    Args:
        source_root: Direct results directory or extraction root.
        expected_name: Required result directory basename.

    Returns:
        Unique absolute results directory.

    Raises:
        InputValidationError: If zero or multiple matching directories exist.
    """

    root = Path(source_root).expanduser().resolve()
    if root.is_dir() and root.name == expected_name:
        return root
    if not root.is_dir():
        raise InputValidationError(f"OrthoFinder source root does not exist: {root}")
    matches = sorted(path for path in root.rglob(expected_name) if path.is_dir())
    if len(matches) != 1:
        raise InputValidationError(
            f"Expected exactly one {expected_name!r} below {root}; found {len(matches)}: "
            + "; ".join(str(path) for path in matches)
        )
    return matches[0]


def read_species_columns(*, table_path: Path, metadata_column_count: int) -> tuple[str, ...]:
    """Read species headings from an OrthoFinder TSV.

    Args:
        table_path: Orthogroups or hierarchical orthogroups TSV.
        metadata_column_count: Number of leading non-species fields.

    Returns:
        Ordered species column labels.

    Raises:
        InputValidationError: If the header does not contain species fields.
    """

    if metadata_column_count <= 0:
        raise ValueError("metadata_column_count must be positive.")
    source = ensure_readable_file(path=table_path)
    with source.open(mode="r", encoding="utf-8", newline="") as handle:
        headings = next(csv.reader(handle, delimiter="\t"), None)
    if headings is None or len(headings) <= metadata_column_count:
        raise InputValidationError(f"OrthoFinder table has no species columns: {source}")
    return tuple(headings[metadata_column_count:])


def iter_membership_records(
    *,
    table_path: Path,
    record_type: str,
) -> Iterator[MembershipRecord]:
    """Yield parsed protein membership from an OrthoFinder TSV.

    Args:
        table_path: ``Orthogroups.tsv`` or root-level ``N0.tsv``.
        record_type: ``ORTHOGROUP`` or ``HIERARCHICAL_ORTHOGROUP``.

    Yields:
        One membership record per raw protein identifier.

    Raises:
        InputValidationError: If table structure or group identifiers are invalid.
    """

    if record_type not in {"ORTHOGROUP", "HIERARCHICAL_ORTHOGROUP"}:
        raise ValueError(f"Unsupported record_type: {record_type}")
    metadata_count = 1 if record_type == "ORTHOGROUP" else 3
    source = ensure_readable_file(path=table_path)
    with source.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        headings = next(reader, None)
        if headings is None or len(headings) <= metadata_count:
            raise InputValidationError(f"Invalid OrthoFinder table header: {source}")
        for source_row, row in enumerate(reader, start=2):
            if len(row) != len(headings):
                raise InputValidationError(
                    f"Row {source_row} in {source} has {len(row)} fields; expected {len(headings)}."
                )
            group_id = row[0].strip()
            orthogroup_id = row[0].strip() if metadata_count == 1 else row[1].strip()
            parent = "" if metadata_count == 1 else row[2].strip()
            if not group_id or not orthogroup_id:
                raise InputValidationError(f"Empty group identifier at row {source_row}: {source}")
            for column_index in range(metadata_count, len(row)):
                species = headings[column_index].strip()
                for raw_identifier in row[column_index].split(","):
                    stripped = raw_identifier.strip()
                    if not stripped:
                        continue
                    yield MembershipRecord(
                        record_type=record_type,
                        group_id=group_id,
                        orthogroup_id=orthogroup_id,
                        gene_tree_parent_clade=parent,
                        species=species,
                        parsed=parse_identifier(value=stripped),
                        source_file=str(source),
                        source_row=source_row,
                    )
