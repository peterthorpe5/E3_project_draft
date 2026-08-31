"""Streaming parsers for OrthoFinder identifiers and membership tables."""

from __future__ import annotations

import csv
import re
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path

from .errors import InputValidationError

csv.field_size_limit(sys.maxsize)

SPECIES_FIELDS = (
    "run_id",
    "species_index",
    "species_label",
    "source_fasta",
    "source_file",
    "source_line",
)
SEQUENCE_FIELDS = (
    "run_id",
    "internal_id",
    "species_index",
    "species_label",
    "source_fasta",
    "raw_header",
    "member_id",
    "source_file",
    "source_line",
)
MEMBERSHIP_FIELDS = (
    "run_id",
    "group_type",
    "hierarchy_node",
    "group_id",
    "legacy_orthogroup_id",
    "gene_tree_parent_clade",
    "species_label",
    "member_id",
    "source_file",
    "source_row",
)

_METADATA_HEADERS = {
    "hog",
    "og",
    "orthogroup",
    "gene tree parent clade",
    "gene_tree_parent_clade",
}


def read_species_ids(*, path: Path, run_id: str) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Parse ``SpeciesIDs.txt`` without normalising away source labels.

    Args:
        path: OrthoFinder species identifier file.
        run_id: Immutable caller-supplied run identifier.

    Returns:
        Species-index lookup and ordered row records.

    Raises:
        InputValidationError: If a line is malformed or an index is duplicated.
    """

    source = _non_empty_file(path=path, role="SpeciesIDs.txt")
    lookup: dict[str, str] = {}
    rows: list[dict[str, object]] = []
    with source.open(mode="r", encoding="utf-8", errors="strict") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            index, separator, fasta_name = line.partition(":")
            index = index.strip()
            fasta_name = fasta_name.strip()
            if not separator or not index or not fasta_name:
                raise InputValidationError(
                    f"Malformed SpeciesIDs.txt line {line_number} in {source}: {line!r}"
                )
            if index in lookup:
                raise InputValidationError(
                    f"Duplicate species index {index!r} at line {line_number} in {source}."
                )
            label = species_label_from_fasta(fasta_name=fasta_name)
            lookup[index] = fasta_name
            rows.append(
                {
                    "run_id": run_id,
                    "species_index": index,
                    "species_label": label,
                    "source_fasta": fasta_name,
                    "source_file": str(source),
                    "source_line": line_number,
                }
            )
    if not rows:
        raise InputValidationError(f"SpeciesIDs.txt contains no species: {source}")
    return lookup, rows


def iter_sequence_ids(
    *,
    path: Path,
    run_id: str,
    species_by_index: Mapping[str, str],
) -> Iterator[dict[str, object]]:
    """Yield long-form records from ``SequenceIDs.txt``.

    Args:
        path: OrthoFinder sequence identifier file.
        run_id: Immutable run identifier.
        species_by_index: Species index to FASTA filename mapping.

    Yields:
        Sequence identifier records preserving the complete raw header.

    Raises:
        InputValidationError: If a record or its species reference is invalid.
    """

    source = _non_empty_file(path=path, role="SequenceIDs.txt")
    with source.open(mode="r", encoding="utf-8", errors="strict") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            internal_id, separator, raw_header = line.partition(":")
            internal_id = internal_id.strip()
            raw_header = raw_header.strip()
            if not separator or not internal_id or not raw_header:
                raise InputValidationError(
                    f"Malformed SequenceIDs.txt line {line_number} in {source}: {line!r}"
                )
            species_index = internal_id.split("_", maxsplit=1)[0]
            if species_index not in species_by_index:
                raise InputValidationError(
                    f"Sequence {internal_id!r} references unknown species index "
                    f"{species_index!r} at line {line_number} in {source}."
                )
            source_fasta = species_by_index[species_index]
            yield {
                "run_id": run_id,
                "internal_id": internal_id,
                "species_index": species_index,
                "species_label": species_label_from_fasta(fasta_name=source_fasta),
                "source_fasta": source_fasta,
                "raw_header": raw_header,
                "member_id": raw_header.split(maxsplit=1)[0],
                "source_file": str(source),
                "source_line": line_number,
            }


def iter_memberships(
    *,
    path: Path,
    run_id: str,
    group_type: str,
    hierarchy_node: str = "",
) -> Iterator[dict[str, object]]:
    """Expand one OrthoFinder group table to one row per protein.

    Args:
        path: Legacy orthogroup or HOG TSV table.
        run_id: Immutable run identifier.
        group_type: ``LEGACY_ORTHOGROUP`` or ``HOG``.
        hierarchy_node: Species-tree node associated with a HOG table.

    Yields:
        Long-form membership records.

    Raises:
        ValueError: If ``group_type`` is unsupported.
        InputValidationError: If the table header or a data row is malformed.
    """

    if group_type not in {"LEGACY_ORTHOGROUP", "HOG"}:
        raise ValueError(f"Unsupported group_type: {group_type!r}")
    source = _non_empty_file(path=path, role=f"{group_type} table")
    with source.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        headings = next(reader, None)
        if headings is None:
            raise InputValidationError(f"Group table has no header: {source}")
        indices, species_indices = _membership_header_indices(
            headings=headings,
            group_type=group_type,
            source=source,
        )
        for source_row, row in enumerate(reader, start=2):
            if len(row) != len(headings):
                raise InputValidationError(
                    f"Row {source_row} in {source} has {len(row)} fields; expected {len(headings)}."
                )
            group_id = row[indices["group"]].strip()
            if not group_id:
                raise InputValidationError(f"Empty group identifier at row {source_row}: {source}")
            legacy_id = row[indices["legacy"]].strip() if "legacy" in indices else ""
            parent = row[indices["parent"]].strip() if "parent" in indices else ""
            for column_index in species_indices:
                species = headings[column_index].strip()
                for raw_member in row[column_index].split(","):
                    member_id = raw_member.strip()
                    if member_id:
                        yield {
                            "run_id": run_id,
                            "group_type": group_type,
                            "hierarchy_node": hierarchy_node,
                            "group_id": group_id,
                            "legacy_orthogroup_id": legacy_id,
                            "gene_tree_parent_clade": parent,
                            "species_label": species,
                            "member_id": member_id,
                            "source_file": str(source),
                            "source_row": source_row,
                        }


def species_label_from_fasta(*, fasta_name: str) -> str:
    """Remove recognised FASTA suffixes while preserving the source label.

    Args:
        fasta_name: Filename recorded by OrthoFinder.

    Returns:
        Source species label.

    Raises:
        InputValidationError: If the filename is empty.
    """

    name = Path(fasta_name.strip()).name
    if not name:
        raise InputValidationError("An empty species FASTA filename is invalid.")
    suffix_pattern = re.compile(r"(?i)(?:\.fa|\.faa|\.fasta|\.fas|\.pep)(?:\.gz)?$")
    return suffix_pattern.sub("", name)


def _membership_header_indices(
    *,
    headings: list[str],
    group_type: str,
    source: Path,
) -> tuple[dict[str, int], tuple[int, ...]]:
    """Resolve metadata and species columns across OrthoFinder versions.

    Args:
        headings: Exact table headings.
        group_type: Declared group semantics.
        source: Source path for diagnostics.

    Returns:
        Metadata indices and ordered species-column indices.

    Raises:
        InputValidationError: If required group or species columns are absent.
    """

    normalised = [heading.strip().lower() for heading in headings]
    indices: dict[str, int] = {}
    if group_type == "LEGACY_ORTHOGROUP":
        candidates = ("orthogroup", "og")
    else:
        candidates = ("hog", "hierarchical orthogroup")
    for candidate in candidates:
        if candidate in normalised:
            indices["group"] = normalised.index(candidate)
            break
    if "group" not in indices:
        raise InputValidationError(
            f"Could not identify the {group_type} identifier column in {source}: {headings}"
        )
    if group_type == "HOG":
        for candidate in ("og", "orthogroup"):
            if candidate in normalised:
                indices["legacy"] = normalised.index(candidate)
                break
        for candidate in ("gene tree parent clade", "gene_tree_parent_clade"):
            if candidate in normalised:
                indices["parent"] = normalised.index(candidate)
                break
    species_indices = tuple(
        index for index, heading in enumerate(normalised) if heading not in _METADATA_HEADERS
    )
    if not species_indices:
        raise InputValidationError(f"Group table has no species columns: {source}")
    if any(not headings[index].strip() for index in species_indices):
        raise InputValidationError(f"Group table contains an empty species heading: {source}")
    return indices, species_indices


def _non_empty_file(*, path: Path, role: str) -> Path:
    """Validate one non-empty regular file.

    Args:
        path: Candidate file path.
        role: Human-readable role.

    Returns:
        Resolved file path.

    Raises:
        InputValidationError: If the file is missing or empty.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise InputValidationError(f"Missing or empty {role}: {source}")
    return source
