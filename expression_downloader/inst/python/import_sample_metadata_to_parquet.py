#!/usr/bin/env python3
"""Import Expression Atlas SDRF/sample metadata into Parquet.

This importer handles two metadata shapes commonly seen in Expression Atlas
FTP folders:

1. Headered SDRF-like tables, where each row already contains columns such as
   ``Assay Group`` or ``Characteristics[organism part]``.
2. Condensed SDRF vertical key-value tables, where rows look like::

      E-CURD-27    <blank>    SRR1138410    characteristic    age    9 day
      E-CURD-27    <blank>    SRR1138410    factor           sampling site  leaf section 1

Expression matrices use compact group labels such as ``g1`` and ``g10`` rather
than assay accessions such as ``SRR1138410``. The authoritative mapping is read
from each experiment's Expression Atlas ``*-configuration.xml``. The importer
requires exact agreement between matrix group IDs and configuration group IDs,
then combines metadata only from the assays explicitly assigned to each group.
It never infers biological groups from row order or factor combinations.

Outputs:
  atlas_sample_metadata_long
      One row per metadata field/value. Includes both assay-level metadata and,
      group-level metadata keyed by ``g1``/``g2`` labels.

  atlas_sample_metadata_wide
      One row per metadata record or authoritative expression group with commonly
      useful fields flattened.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None

TRUE_VALUES = {"true", "t", "yes", "y", "1"}
FALSE_VALUES = {"false", "f", "no", "n", "0", ""}
METADATA_FILE_TYPES = {"sample_metadata"}
EXPRESSION_FILE_TYPES = {"tpms", "fpkms"}
GROUP_PATTERN = re.compile(r"^g([1-9][0-9]*)$")
METADATA_SCHEMA_VERSION = "3.1"
SCHEMA_VERSION_METADATA_KEY = b"e3_sample_metadata_schema_version"
METADATA_SHA256_METADATA_KEY = b"e3_sample_metadata_source_sha256"
CONFIGURATION_SHA256_METADATA_KEY = b"e3_configuration_source_sha256"
EXPRESSION_SHA256_METADATA_KEY = b"e3_expression_source_sha256"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

PREFERRED_FIELDS = {
    "organism": (
        "characteristics[organism]",
        "organism",
    ),
    "organism_part": (
        "characteristics[organism part]",
        "characteristics[organism_part]",
        "organism part",
        "organism_part",
        "factor value[organism part]",
    ),
    "developmental_stage": (
        "characteristics[developmental stage]",
        "developmental stage",
        "developmental_stage",
        "factor value[developmental stage]",
        "age",
        "characteristics[age]",
    ),
    "genotype": (
        "characteristics[genotype]",
        "genotype",
        "factor value[genotype]",
    ),
    "cultivar": (
        "characteristics[cultivar]",
        "cultivar",
        "characteristics[variety]",
        "variety",
    ),
    "treatment": (
        "characteristics[treatment]",
        "treatment",
        "factor value[treatment]",
        "factor value[compound]",
        "compound",
    ),
    "condition": (
        "factor value[condition]",
        "condition",
        "factor value[disease]",
        "factor value[phenotype]",
    ),
    "assay_name": (
        "assay name",
        "assay_name",
    ),
    "source_name": (
        "source name",
        "source_name",
    ),
    "sample_name": (
        "sample name",
        "sample_name",
    ),
}

GROUP_COLUMN_HINTS = (
    "assay group",
    "sample group",
    "atlas group",
    "group",
    "factor value",
    "comment[ea",
    "comment[atlas",
)


@dataclass(frozen=True)
class MetadataJob:
    """A single metadata import job."""

    metadata_tsv: Path
    experiment_accession: str
    species_column: str
    source_database: str = "ExpressionAtlas"
    metadata_file_kind: str = "sample_metadata"
    expression_tsv: Optional[Path] = None
    configuration_xml: Optional[Path] = None
    metadata_sha256: str = ""
    expression_sha256: str = ""
    configuration_sha256: str = ""


@dataclass(frozen=True)
class AssayGroup:
    """One authoritative Expression Atlas assay group."""

    group_id: str
    label: str
    assay_ids: tuple[str, ...]


@dataclass(frozen=True)
class MetadataResult:
    """Summary of one metadata import."""

    metadata_tsv: Path
    experiment_accession: str
    species_column: str
    metadata_file_kind: str
    action: str
    success: bool
    metadata_records: int
    wide_rows: int
    long_rows: int
    mapped_group_records: int
    message: str


def require_pyarrow() -> None:
    """Stop with a clear message if pyarrow is unavailable."""

    if pa is None or pq is None:
        raise SystemExit(
            "Missing Python dependency: pyarrow. Install it with:\n"
            "  mamba install -c conda-forge pyarrow"
        )


def parse_bool(value: object, default: bool = False) -> bool:
    """Convert common text values to boolean."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return default


def metadata_file_kind(path: Path | str) -> str:
    """Classify an Expression Atlas metadata file by filename."""

    name = Path(path).name.lower()
    if "condensed-sdrf" in name and not name.endswith(".bak"):
        return "condensed_sdrf"
    if name.endswith(".sdrf.txt") or "sdrf" in name:
        if name.endswith(".bak"):
            return "backup_sdrf"
        return "sdrf"
    return "sample_metadata"


def metadata_file_priority(path: Path | str) -> int:
    """Return a sort priority for choosing one metadata file per experiment."""

    kind = metadata_file_kind(path)
    priorities = {
        "condensed_sdrf": 0,
        "sdrf": 1,
        "sample_metadata": 2,
        "backup_sdrf": 9,
    }
    return priorities.get(kind, 5)


def merge_metadata_value(existing: str, new_value: str) -> str:
    """Merge metadata values while preserving unique non-empty terms."""

    existing = str(existing or "").strip()
    new_value = str(new_value or "").strip()
    if not existing:
        return new_value
    if not new_value:
        return existing
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if new_value not in parts:
        parts.append(new_value)
    return "; ".join(parts)


def merge_wide_record(
    existing: dict[str, object], new_record: dict[str, object]
) -> dict[str, object]:
    """Collapse multiple metadata records for the same join key."""

    merged = dict(existing)
    for key, value in new_record.items():
        if key == "assay_count":
            existing_count = int(merged.get(key, 0) or 0)
            new_count = int(value or 0)
            if existing_count and new_count and existing_count != new_count:
                raise ValueError(
                    "Conflicting assay counts for metadata join key "
                    f"{existing.get('sample_or_condition', '')!r}: "
                    f"{existing_count} and {new_count}"
                )
            merged[key] = max(existing_count, new_count)
            continue
        if key in {
            "source_database",
            "experiment_accession",
            "species_column",
            "sample_or_condition",
            "source_file",
        }:
            if not str(merged.get(key, "")).strip() and str(value).strip():
                merged[key] = value
            continue
        merged[key] = merge_metadata_value(str(merged.get(key, "")), str(value))
    return merged


def open_text(path: Path):
    """Open a plain or gzipped text file."""

    if str(path).endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8", newline="")
    return path.open(mode="r", encoding="utf-8", newline="")


def make_closed_temp_path(parent_dir: Path, suffix: str) -> Path:
    """Create a temporary path and immediately close the file descriptor."""

    file_descriptor, temporary_name = tempfile.mkstemp(
        suffix=suffix,
        dir=str(parent_dir),
    )
    os.close(file_descriptor)
    return Path(temporary_name)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the lowercase SHA-256 digest of one file.

    Args:
        path: Existing regular file.
        chunk_size: Bytes read per digest update.

    Returns:
        Lowercase hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_file_sha256(path: Optional[Path], expected: str, label: str) -> str:
    """Calculate and validate one optional raw-input digest.

    Args:
        path: Input file, or ``None`` when the input does not apply.
        expected: Optional manifest SHA-256.
        label: Input description for validation errors.

    Returns:
        Verified lowercase digest, or an empty string for ``None``.

    Raises:
        ValueError: If the file is absent, digest malformed, or checksum differs.
    """
    if path is None:
        return ""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{label} is missing or empty: {path}")
    expected = expected.strip().lower()
    if expected and not SHA256_PATTERN.fullmatch(expected):
        raise ValueError(f"Malformed {label} SHA-256 for {path}: {expected!r}")
    observed = sha256_file(path)
    if expected and observed != expected:
        raise ValueError(
            f"{label} SHA-256 mismatch for {path}: manifest={expected}, observed={observed}"
        )
    return observed


def normalise_header(value: str) -> str:
    """Normalise a metadata header for matching."""

    text = value.strip().strip('"').strip("'")
    text = re.sub(r"\s+", " ", text)
    return text


def normalise_key(value: str) -> str:
    """Return a lower-case matching key."""

    return normalise_header(value).lower()


def make_unique(names: Iterable[str]) -> list[str]:
    """Return unique column names while preserving order."""

    seen: dict[str, int] = {}
    unique: list[str] = []
    for name in names:
        clean = normalise_header(name)
        if clean == "":
            clean = "unnamed_column"
        count = seen.get(clean, 0) + 1
        seen[clean] = count
        if count == 1:
            unique.append(clean)
        else:
            unique.append(f"{clean}_{count}")
    return unique


def is_group_value(value: str) -> bool:
    """Return true when a value looks like an Atlas group label."""

    return bool(GROUP_PATTERN.match(value.strip()))


def group_label_sort_key(value: str) -> tuple[int, str]:
    """Sort Atlas group labels by their numeric suffix."""

    match = re.match(r"^g(\d+)$", value.strip(), flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), value
    return sys.maxsize, value


def choose_sample_or_condition(row: dict[str, str]) -> str:
    """Infer the compact expression group/sample label for a metadata row."""

    for key, value in row.items():
        key_lower = normalise_key(key)
        if any(hint in key_lower for hint in GROUP_COLUMN_HINTS) and is_group_value(value):
            return value.strip()

    for value in row.values():
        if is_group_value(value):
            return value.strip()

    for preferred_key in ("assay name", "sample name", "source name"):
        for key, value in row.items():
            if normalise_key(key) == preferred_key and value.strip():
                return value.strip()

    return ""


def get_preferred_value(row: dict[str, str], field_name: str) -> str:
    """Extract a preferred flattened metadata value from a row."""

    aliases = PREFERRED_FIELDS.get(field_name, ())
    keyed = {normalise_key(key): value.strip() for key, value in row.items()}

    for alias in aliases:
        alias_key = normalise_key(alias)
        merged = ""
        for key, value in keyed.items():
            if key == alias_key or re.fullmatch(
                re.escape(alias_key) + r"_[2-9][0-9]*",
                key,
            ):
                merged = merge_metadata_value(merged, value)
        if merged:
            return merged

    return ""


def metadata_category(field_name: str) -> str:
    """Classify a metadata field by broad SDRF origin."""

    key = normalise_key(field_name)
    if key.startswith("characteristics["):
        return "characteristic"
    if key.startswith("factor value["):
        return "factor_value"
    if key.startswith("comment["):
        return "comment"
    if key.startswith("protocol"):
        return "protocol"
    return "field"


def vertical_metadata_category(category: str) -> str:
    """Normalise vertical condensed-SDRF metadata categories."""

    key = normalise_key(category)
    if key == "characteristic":
        return "characteristic"
    if key == "factor":
        return "factor_value"
    if key == "comment":
        return "comment"
    if key:
        return key
    return "field"


def looks_like_vertical_condensed_row(row: list[str], job: MetadataJob) -> bool:
    """Return true if a row looks like vertical condensed-SDRF metadata."""

    if len(row) < 6:
        return False
    if row[0].strip() != job.experiment_accession:
        return False
    category = normalise_key(row[3])
    return category in {"characteristic", "factor", "comment", "protocol"}


def read_expression_group_labels(expression_tsv: Optional[Path]) -> list[str]:
    """Read expression matrix group columns such as g1/g2 from a TSV header."""

    if expression_tsv is None or not expression_tsv.exists() or expression_tsv.stat().st_size == 0:
        return []

    with open_text(expression_tsv) as handle:
        first_line = handle.readline()

    if not first_line:
        return []

    header = [item.strip().strip('"').strip("'") for item in first_line.rstrip("\n\r").split("\t")]
    expression_columns = [
        name
        for name in header
        if normalise_key(name) not in {"geneid", "gene id", "gene name", "gene_name", "name"}
    ]
    group_labels = [name for name in expression_columns if is_group_value(name)]
    if len(group_labels) != len(expression_columns):
        invalid = [name for name in expression_columns if not is_group_value(name)]
        raise ValueError(f"Expression matrix contains non-group condition labels: {invalid!r}")
    if len(set(group_labels)) != len(group_labels):
        raise ValueError(f"Expression matrix contains duplicate group labels: {group_labels!r}")
    return group_labels


def xml_local_name(tag: str) -> str:
    """Return an XML tag without an optional namespace prefix.

    Args:
        tag: ElementTree tag.

    Returns:
        Local XML element name.
    """
    return tag.rsplit("}", maxsplit=1)[-1]


def read_configuration_groups(configuration_xml: Path) -> OrderedDict[str, AssayGroup]:
    """Read the authoritative Atlas group-to-assay mapping.

    Args:
        configuration_xml: Experiment ``*-configuration.xml`` file.

    Returns:
        Assay groups keyed by their matrix group ID.

    Raises:
        ValueError: If the XML is missing, malformed, duplicated or incomplete.
    """
    if not configuration_xml.exists() or configuration_xml.stat().st_size == 0:
        raise ValueError(f"Expression Atlas configuration XML is missing: {configuration_xml}")
    try:
        root = ET.parse(configuration_xml).getroot()
    except (ET.ParseError, OSError) as error:
        raise ValueError(
            f"Invalid Expression Atlas configuration XML: {configuration_xml}: {error}"
        ) from error

    groups: OrderedDict[str, AssayGroup] = OrderedDict()
    for element in root.iter():
        if xml_local_name(element.tag) != "assay_group":
            continue
        group_id = (element.attrib.get("id") or "").strip()
        label = (element.attrib.get("label") or "").strip()
        assay_ids = tuple(
            (child.text or "").strip()
            for child in element
            if xml_local_name(child.tag) == "assay" and (child.text or "").strip()
        )
        if not GROUP_PATTERN.fullmatch(group_id):
            raise ValueError(f"Configuration contains an invalid assay-group ID: {group_id!r}")
        if group_id in groups:
            raise ValueError(f"Configuration contains duplicate assay-group ID: {group_id!r}")
        if not assay_ids or len(set(assay_ids)) != len(assay_ids):
            raise ValueError(f"Configuration group {group_id!r} has missing or duplicate assays")
        groups[group_id] = AssayGroup(group_id, label, assay_ids)

    if not groups:
        raise ValueError(f"Configuration contains no assay groups: {configuration_xml}")
    all_assays = [assay for group in groups.values() for assay in group.assay_ids]
    duplicate_assays = sorted({assay for assay in all_assays if all_assays.count(assay) > 1})
    if duplicate_assays:
        raise ValueError(f"Configuration assigns assays to multiple groups: {duplicate_assays!r}")
    return groups


def validate_matrix_configuration_groups(
    group_labels: list[str],
    configuration_groups: OrderedDict[str, AssayGroup],
) -> list[AssayGroup]:
    """Match matrix groups to configuration groups and fail on disagreement.

    Args:
        group_labels: Expression matrix condition columns.
        configuration_groups: Authoritative groups from configuration XML.

    Returns:
        Configuration groups in matrix-column order.

    Raises:
        ValueError: If labels are duplicated, non-group fields, or the two
            sources do not contain exactly the same group IDs.
    """
    if len(set(group_labels)) != len(group_labels):
        raise ValueError("Expression matrix contains duplicate group labels")
    invalid_labels = [label for label in group_labels if not GROUP_PATTERN.fullmatch(label)]
    if invalid_labels:
        raise ValueError(
            f"Expression matrix contains non-group condition labels: {invalid_labels!r}"
        )
    matrix_ids = set(group_labels)
    configuration_ids = set(configuration_groups)
    if not matrix_ids.issubset(configuration_ids):
        missing = sorted(matrix_ids - configuration_ids, key=group_label_sort_key)
        raise ValueError(
            "Matrix/configuration assay groups disagree; "
            f"missing_from_configuration={missing!r}"
        )
    return [configuration_groups[label] for label in group_labels]


def field_values_to_wide_record(
    *,
    job: MetadataJob,
    sample_or_condition: str,
    metadata_record_id: str,
    field_values: dict[str, str],
    source_file: str,
    condition_value: str = "",
    atlas_group_label: str = "",
    assay_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build one wide metadata record from normalised field values."""

    def pick(*names: str) -> str:
        for name in names:
            value = field_values.get(normalise_key(name), "").strip()
            if value:
                return value
        return ""

    condition = pick("condition")
    if not condition:
        condition = condition_value

    return {
        "source_database": job.source_database,
        "experiment_accession": job.experiment_accession,
        "species_column": job.species_column,
        "sample_or_condition": sample_or_condition,
        "atlas_group_label": atlas_group_label,
        "assay_ids": ";".join(assay_ids),
        "assay_count": len(assay_ids),
        "metadata_record_id": metadata_record_id,
        "organism": pick("organism"),
        "organism_part": pick("organism part", "organism_part"),
        "developmental_stage": pick("developmental stage", "developmental_stage", "age"),
        "genotype": pick("genotype"),
        "cultivar": pick("cultivar", "variety"),
        "treatment": pick("treatment", "compound"),
        "condition": condition,
        "assay_name": pick("assay name"),
        "source_name": pick("source name"),
        "sample_name": pick("sample name"),
        "source_file": source_file,
        "source_file_sha256": job.metadata_sha256,
        "configuration_file": (
            str(job.configuration_xml) if job.configuration_xml is not None else ""
        ),
        "configuration_file_sha256": job.configuration_sha256,
        "expression_file_sha256": job.expression_sha256,
    }


def make_long_record(
    *,
    job: MetadataJob,
    sample_or_condition: str,
    metadata_record_id: str,
    metadata_field: str,
    metadata_category_value: str,
    metadata_value: str,
) -> dict[str, object]:
    """Build one long metadata record."""

    return {
        "source_database": job.source_database,
        "experiment_accession": job.experiment_accession,
        "species_column": job.species_column,
        "sample_or_condition": sample_or_condition,
        "metadata_record_id": metadata_record_id,
        "metadata_field": metadata_field,
        "metadata_category": metadata_category_value,
        "metadata_value": metadata_value,
        "source_file": str(job.metadata_tsv),
        "source_file_sha256": job.metadata_sha256,
        "configuration_file": (
            str(job.configuration_xml) if job.configuration_xml is not None else ""
        ),
        "configuration_file_sha256": job.configuration_sha256,
        "expression_file_sha256": job.expression_sha256,
    }


def parse_tabular_metadata(
    job: MetadataJob,
    header: list[str],
    rows: Iterable[list[str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], int, int]:
    """Parse headered SDRF-like metadata rows."""

    unique_header = make_unique(header)
    wide_records: list[dict[str, object]] = []
    long_records: list[dict[str, object]] = []
    metadata_records = 0
    mapped_group_records = 0

    for row_index, raw_row in enumerate(rows, start=1):
        if not raw_row:
            continue
        if len(raw_row) != len(unique_header):
            raise ValueError(
                f"Metadata row {row_index} has {len(raw_row)} fields; expected {len(unique_header)}"
            )
        values = [value.strip() for value in raw_row]
        row = dict(zip(unique_header, values))
        sample_or_condition = choose_sample_or_condition(row=row)
        metadata_record_id = f"{job.experiment_accession}:{row_index}"
        metadata_records += 1
        if sample_or_condition:
            mapped_group_records += 1

        wide_records.append(
            {
                "source_database": job.source_database,
                "experiment_accession": job.experiment_accession,
                "species_column": job.species_column,
                "sample_or_condition": sample_or_condition,
                "atlas_group_label": "",
                "assay_ids": "",
                "assay_count": 0,
                "metadata_record_id": metadata_record_id,
                "organism": get_preferred_value(row, "organism"),
                "organism_part": get_preferred_value(row, "organism_part"),
                "developmental_stage": get_preferred_value(row, "developmental_stage"),
                "genotype": get_preferred_value(row, "genotype"),
                "cultivar": get_preferred_value(row, "cultivar"),
                "treatment": get_preferred_value(row, "treatment"),
                "condition": get_preferred_value(row, "condition"),
                "assay_name": get_preferred_value(row, "assay_name"),
                "source_name": get_preferred_value(row, "source_name"),
                "sample_name": get_preferred_value(row, "sample_name"),
                "source_file": str(job.metadata_tsv),
                "source_file_sha256": job.metadata_sha256,
                "configuration_file": (
                    str(job.configuration_xml) if job.configuration_xml is not None else ""
                ),
                "configuration_file_sha256": job.configuration_sha256,
                "expression_file_sha256": job.expression_sha256,
            }
        )

        for field_name, value in row.items():
            value = value.strip()
            if value == "":
                continue
            long_records.append(
                make_long_record(
                    job=job,
                    sample_or_condition=sample_or_condition,
                    metadata_record_id=metadata_record_id,
                    metadata_field=field_name,
                    metadata_category_value=metadata_category(field_name),
                    metadata_value=value,
                )
            )

    return wide_records, long_records, metadata_records, mapped_group_records


def parse_vertical_condensed_metadata(
    job: MetadataJob,
    first_row: list[str],
    rows: Iterable[list[str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], int, int]:
    """Parse vertical key-value condensed SDRF metadata.

    The returned wide records include assay-level records keyed by SRR/GSM-like
    accessions and, when possible, inferred group-level records keyed by the
    expression matrix group labels g1/g2/...
    """

    all_rows = [first_row]
    all_rows.extend(list(rows))

    assay_order: list[str] = []
    assay_seen: set[str] = set()
    assay_fields: OrderedDict[str, dict[tuple[str, str], str]] = OrderedDict()
    assay_factors: OrderedDict[str, dict[str, str]] = OrderedDict()
    long_records: list[dict[str, object]] = []
    metadata_records = 0

    for row_index, raw_row in enumerate(all_rows, start=1):
        if not raw_row or not any(value.strip() for value in raw_row):
            continue
        if len(raw_row) < 6:
            raise ValueError(
                f"Condensed SDRF row {row_index} has {len(raw_row)} fields; expected at least 6"
            )
        experiment_accession = raw_row[0].strip()
        assay_id = raw_row[2].strip()
        category = raw_row[3].strip()
        field = raw_row[4].strip()
        value = raw_row[5].strip()
        if experiment_accession != job.experiment_accession:
            raise ValueError(
                f"Condensed SDRF row {row_index} has accession "
                f"{experiment_accession!r}; expected {job.experiment_accession!r}"
            )
        if not assay_id or not field or not value:
            continue

        metadata_records += 1
        if assay_id not in assay_seen:
            assay_seen.add(assay_id)
            assay_order.append(assay_id)
            assay_fields[assay_id] = {}
            assay_factors[assay_id] = {}

        category_norm = vertical_metadata_category(category)
        field_norm = normalise_key(field)
        key = (category_norm, field_norm)
        assay_fields[assay_id][key] = merge_metadata_value(
            assay_fields[assay_id].get(key, ""),
            value,
        )
        if category_norm == "factor_value":
            assay_factors[assay_id][field_norm] = merge_metadata_value(
                assay_factors[assay_id].get(field_norm, ""),
                value,
            )

        long_records.append(
            make_long_record(
                job=job,
                sample_or_condition=assay_id,
                metadata_record_id=f"{job.experiment_accession}:{assay_id}:{row_index}",
                metadata_field=field,
                metadata_category_value=category_norm,
                metadata_value=value,
            )
        )

    wide_records: list[dict[str, object]] = []
    for assay_id in assay_order:
        field_values: dict[str, str] = {}
        for (_category, field_norm), value in assay_fields[assay_id].items():
            field_values[field_norm] = merge_metadata_value(field_values.get(field_norm, ""), value)
        factor_condition = "; ".join(
            f"{field}={value}" for field, value in assay_factors[assay_id].items() if value
        )
        wide_records.append(
            field_values_to_wide_record(
                job=job,
                sample_or_condition=assay_id,
                metadata_record_id=f"{job.experiment_accession}:{assay_id}",
                field_values=field_values,
                source_file=str(job.metadata_tsv),
                condition_value=factor_condition,
                assay_ids=(assay_id,),
            )
        )

    mapped_group_records = 0
    group_labels = read_expression_group_labels(job.expression_tsv)
    if group_labels:
        if job.configuration_xml is None:
            raise ValueError(
                "Expression matrix group metadata requires the authoritative "
                "Expression Atlas configuration XML"
            )
        configuration_groups = read_configuration_groups(job.configuration_xml)
        matched_groups = validate_matrix_configuration_groups(
            group_labels,
            configuration_groups,
        )
        configured_assays = {assay_id for group in matched_groups for assay_id in group.assay_ids}
        missing_assays = sorted(configured_assays - set(assay_fields))
        if missing_assays:
            raise ValueError(
                "Configuration XML references assays absent from sample metadata: "
                f"{missing_assays!r}"
            )

        for assay_group in matched_groups:
            group_label = assay_group.group_id
            record_id = (
                f"{job.experiment_accession}:{group_label}:authoritative_configuration_group"
            )
            group_field_values: dict[str, str] = {}
            group_factor_values: dict[str, str] = {}
            for assay_id in assay_group.assay_ids:
                for (category_norm, field_norm), value in assay_fields[assay_id].items():
                    group_field_values[field_norm] = merge_metadata_value(
                        group_field_values.get(field_norm, ""),
                        value,
                    )
                    if category_norm == "factor_value":
                        group_factor_values[field_norm] = merge_metadata_value(
                            group_factor_values.get(field_norm, ""),
                            value,
                        )
            condition_value = "; ".join(
                f"{field}={value}" for field, value in group_factor_values.items() if value
            )
            wide_records.append(
                field_values_to_wide_record(
                    job=job,
                    sample_or_condition=group_label,
                    metadata_record_id=record_id,
                    field_values=group_field_values,
                    source_file=str(job.metadata_tsv),
                    condition_value=condition_value,
                    atlas_group_label=assay_group.label,
                    assay_ids=assay_group.assay_ids,
                )
            )
            mapped_group_records += 1

            long_records.append(
                make_long_record(
                    job=job,
                    sample_or_condition=group_label,
                    metadata_record_id=record_id,
                    metadata_field="metadata_mapping_method",
                    metadata_category_value="authoritative_group",
                    metadata_value="atlas_configuration_xml_assay_group",
                )
            )
            if assay_group.label:
                long_records.append(
                    make_long_record(
                        job=job,
                        sample_or_condition=group_label,
                        metadata_record_id=record_id,
                        metadata_field="atlas_group_label",
                        metadata_category_value="authoritative_group",
                        metadata_value=assay_group.label,
                    )
                )
            for field_norm, value in group_field_values.items():
                if not value:
                    continue
                long_records.append(
                    make_long_record(
                        job=job,
                        sample_or_condition=group_label,
                        metadata_record_id=record_id,
                        metadata_field=field_norm,
                        metadata_category_value="authoritative_group",
                        metadata_value=value,
                    )
                )

    return wide_records, long_records, metadata_records, mapped_group_records


def read_metadata_records(
    job: MetadataJob,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int, int]:
    """Read one metadata file into wide and long records."""

    with open_text(job.metadata_tsv) as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            first_row = next(reader)
        except StopIteration:
            return [], [], 0, 0

        remaining_rows = list(reader)

    if looks_like_vertical_condensed_row(first_row, job):
        return parse_vertical_condensed_metadata(
            job=job,
            first_row=first_row,
            rows=remaining_rows,
        )

    return parse_tabular_metadata(
        job=job,
        header=first_row,
        rows=remaining_rows,
    )


def wide_schema(
    metadata_sha256: str = "",
    configuration_sha256: str = "",
    expression_sha256: str = "",
) -> pa.Schema:
    """Return the sample metadata wide schema."""

    return pa.schema(
        [
            pa.field("source_database", pa.string()),
            pa.field("experiment_accession", pa.string()),
            pa.field("species_column", pa.string()),
            pa.field("sample_or_condition", pa.string()),
            pa.field("atlas_group_label", pa.string()),
            pa.field("assay_ids", pa.string()),
            pa.field("assay_count", pa.int32()),
            pa.field("metadata_record_id", pa.string()),
            pa.field("organism", pa.string()),
            pa.field("organism_part", pa.string()),
            pa.field("developmental_stage", pa.string()),
            pa.field("genotype", pa.string()),
            pa.field("cultivar", pa.string()),
            pa.field("treatment", pa.string()),
            pa.field("condition", pa.string()),
            pa.field("assay_name", pa.string()),
            pa.field("source_name", pa.string()),
            pa.field("sample_name", pa.string()),
            pa.field("source_file", pa.string()),
            pa.field("source_file_sha256", pa.string()),
            pa.field("configuration_file", pa.string()),
            pa.field("configuration_file_sha256", pa.string()),
            pa.field("expression_file_sha256", pa.string()),
        ],
        metadata={
            SCHEMA_VERSION_METADATA_KEY: METADATA_SCHEMA_VERSION.encode("ascii"),
            **(
                {METADATA_SHA256_METADATA_KEY: metadata_sha256.encode("ascii")}
                if metadata_sha256
                else {}
            ),
            **(
                {CONFIGURATION_SHA256_METADATA_KEY: configuration_sha256.encode("ascii")}
                if configuration_sha256
                else {}
            ),
            **(
                {EXPRESSION_SHA256_METADATA_KEY: expression_sha256.encode("ascii")}
                if expression_sha256
                else {}
            ),
        },
    )


def long_schema(
    metadata_sha256: str = "",
    configuration_sha256: str = "",
    expression_sha256: str = "",
) -> pa.Schema:
    """Return the sample metadata long schema."""

    return pa.schema(
        [
            pa.field("source_database", pa.string()),
            pa.field("experiment_accession", pa.string()),
            pa.field("species_column", pa.string()),
            pa.field("sample_or_condition", pa.string()),
            pa.field("metadata_record_id", pa.string()),
            pa.field("metadata_field", pa.string()),
            pa.field("metadata_category", pa.string()),
            pa.field("metadata_value", pa.string()),
            pa.field("source_file", pa.string()),
            pa.field("source_file_sha256", pa.string()),
            pa.field("configuration_file", pa.string()),
            pa.field("configuration_file_sha256", pa.string()),
            pa.field("expression_file_sha256", pa.string()),
        ],
        metadata={
            SCHEMA_VERSION_METADATA_KEY: METADATA_SCHEMA_VERSION.encode("ascii"),
            **(
                {METADATA_SHA256_METADATA_KEY: metadata_sha256.encode("ascii")}
                if metadata_sha256
                else {}
            ),
            **(
                {CONFIGURATION_SHA256_METADATA_KEY: configuration_sha256.encode("ascii")}
                if configuration_sha256
                else {}
            ),
            **(
                {EXPRESSION_SHA256_METADATA_KEY: expression_sha256.encode("ascii")}
                if expression_sha256
                else {}
            ),
        },
    )


def rows_to_table(rows: list[dict[str, object]], schema: pa.Schema) -> pa.Table:
    """Convert dictionaries into an Arrow table."""

    columns = {name: [] for name in schema.names}
    for row in rows:
        for name in schema.names:
            columns[name].append(row.get(name, ""))
    arrays = [pa.array(columns[name], type=schema.field(name).type) for name in schema.names]
    return pa.Table.from_arrays(arrays, schema=schema)


def parquet_row_count(path: Path) -> int:
    """Return the number of rows in a Parquet file."""

    if not path.exists() or path.stat().st_size == 0:
        return 0
    try:
        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        return 0


def parquet_has_current_schema(path: Path, expected_schema: pa.Schema) -> bool:
    """Return whether a Parquet file matches the current metadata contract."""

    if parquet_row_count(path) == 0:
        return False
    try:
        schema = pq.ParquetFile(path).schema_arrow
    except Exception:  # noqa: BLE001 - invalid Parquet must not be reused
        return False
    metadata = schema.metadata or {}
    expected_metadata = expected_schema.metadata or {}
    return set(expected_schema.names).issubset(schema.names) and all(
        metadata.get(key) == value for key, value in expected_metadata.items()
    )


def write_partitioned_metadata(job: MetadataJob, output_dir: Path, force: bool) -> MetadataResult:
    """Import one metadata file into wide and long Parquet datasets."""

    if not job.metadata_tsv.exists() or job.metadata_tsv.stat().st_size == 0:
        return MetadataResult(
            job.metadata_tsv,
            job.experiment_accession,
            job.species_column,
            job.metadata_file_kind,
            "skipped_missing_or_empty_input",
            False,
            0,
            0,
            0,
            0,
            "metadata file missing or empty",
        )

    try:
        job = replace(
            job,
            metadata_sha256=resolve_file_sha256(
                job.metadata_tsv,
                job.metadata_sha256,
                "Sample metadata source",
            ),
            configuration_sha256=resolve_file_sha256(
                job.configuration_xml,
                job.configuration_sha256,
                "Configuration source",
            ),
            expression_sha256=resolve_file_sha256(
                job.expression_tsv,
                job.expression_sha256,
                "Expression-matrix source",
            ),
        )
    except (OSError, ValueError) as error:
        return MetadataResult(
            job.metadata_tsv,
            job.experiment_accession,
            job.species_column,
            job.metadata_file_kind,
            "source_validation_failed",
            False,
            0,
            0,
            0,
            0,
            str(error),
        )

    current_wide_schema = wide_schema(
        job.metadata_sha256,
        job.configuration_sha256,
        job.expression_sha256,
    )
    current_long_schema = long_schema(
        job.metadata_sha256,
        job.configuration_sha256,
        job.expression_sha256,
    )

    wide_path = (
        output_dir
        / "parquet"
        / "atlas_sample_metadata_wide"
        / f"species_column={job.species_column}"
        / f"experiment_accession={job.experiment_accession}"
        / "sample_metadata.parquet"
    )
    long_path = (
        output_dir
        / "parquet"
        / "atlas_sample_metadata_long"
        / f"species_column={job.species_column}"
        / f"experiment_accession={job.experiment_accession}"
        / "sample_metadata.parquet"
    )

    if (
        not force
        and parquet_has_current_schema(wide_path, current_wide_schema)
        and parquet_has_current_schema(long_path, current_long_schema)
    ):
        return MetadataResult(
            job.metadata_tsv,
            job.experiment_accession,
            job.species_column,
            job.metadata_file_kind,
            "skipped_existing_non_empty_parquet",
            True,
            parquet_row_count(wide_path),
            parquet_row_count(wide_path),
            parquet_row_count(long_path),
            0,
            "existing metadata Parquet contained rows",
        )

    wide_path.parent.mkdir(parents=True, exist_ok=True)
    long_path.parent.mkdir(parents=True, exist_ok=True)
    wide_temp = make_closed_temp_path(
        parent_dir=wide_path.parent,
        suffix=".wide.parquet.partial",
    )
    long_temp = make_closed_temp_path(
        parent_dir=long_path.parent,
        suffix=".long.parquet.partial",
    )

    try:
        wide_records, long_records, metadata_records, mapped_group_records = read_metadata_records(
            job=job
        )

        wide_by_key: dict[str, dict[str, object]] = {}
        for record in wide_records:
            sample_key = str(record.get("sample_or_condition", "")).strip()
            if not sample_key:
                continue
            if sample_key not in wide_by_key:
                wide_by_key[sample_key] = record
            else:
                wide_by_key[sample_key] = merge_wide_record(
                    existing=wide_by_key[sample_key],
                    new_record=record,
                )

        expected_group_labels = (
            read_expression_group_labels(job.expression_tsv)
            if job.expression_tsv is not None
            else []
        )
        if expected_group_labels and job.configuration_xml is None:
            raise ValueError("Expression-matrix groups require an authoritative configuration XML")
        if expected_group_labels:
            validate_matrix_configuration_groups(
                expected_group_labels,
                read_configuration_groups(job.configuration_xml),
            )
        missing_group_labels = sorted(
            set(expected_group_labels) - set(wide_by_key),
            key=group_label_sort_key,
        )
        if missing_group_labels:
            raise ValueError(
                "Sample metadata did not produce records for expression "
                f"groups: {missing_group_labels!r}"
            )

        long_writer = pq.ParquetWriter(
            long_temp,
            current_long_schema,
            compression="snappy",
        )
        for start in range(0, len(long_records), 250000):
            chunk = long_records[start:start + 250000]
            if chunk:
                long_writer.write_table(rows_to_table(chunk, current_long_schema))
        long_writer.close()

        wide_writer = pq.ParquetWriter(
            wide_temp,
            current_wide_schema,
            compression="snappy",
        )
        wide_collapsed = list(wide_by_key.values())
        if wide_collapsed:
            wide_writer.write_table(rows_to_table(wide_collapsed, current_wide_schema))
        wide_writer.close()

    except Exception as error:  # noqa: BLE001
        for path in (wide_temp, long_temp):
            if path.exists():
                path.unlink()
        return MetadataResult(
            job.metadata_tsv,
            job.experiment_accession,
            job.species_column,
            job.metadata_file_kind,
            "import_failed",
            False,
            0,
            0,
            0,
            0,
            str(error),
        )

    wide_temp.replace(wide_path)
    long_temp.replace(long_path)
    wide_rows = parquet_row_count(wide_path)
    long_count = parquet_row_count(long_path)
    success = long_count > 0
    message = "metadata imported"
    if wide_rows == 0:
        message = (
            "metadata imported, but no non-empty sample_or_condition labels "
            "were available for joining"
        )
    elif mapped_group_records == 0 and job.expression_tsv is not None:
        message = "metadata imported, but no authoritative expression group mapping was created"

    return MetadataResult(
        job.metadata_tsv,
        job.experiment_accession,
        job.species_column,
        job.metadata_file_kind,
        "imported_to_parquet" if success else "imported_empty_parquet",
        success,
        metadata_records,
        wide_rows,
        long_count,
        mapped_group_records,
        message,
    )


def read_downloaded_manifest(path: Path) -> list[dict[str, str]]:
    """Read the downloaded-files manifest."""

    with path.open(mode="r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build_jobs(downloaded_files_tsv: Path) -> list[MetadataJob]:
    """Build one preferred metadata import job per species/experiment."""

    rows = read_downloaded_manifest(downloaded_files_tsv)
    best_rows: dict[tuple[str, str], dict[str, str]] = {}
    best_priorities: dict[tuple[str, str], tuple[int, str]] = {}
    expression_sources: dict[tuple[str, str], tuple[Path, str, str]] = {}
    configuration_sources: dict[tuple[str, str], tuple[Path, str]] = {}

    for row in rows:
        if not parse_bool(row.get("success"), default=False):
            continue
        species_column = (row.get("species_column") or "").strip()
        experiment_accession = (row.get("experiment_accession") or "").strip()
        local_path_text = (row.get("local_path") or "").strip()
        file_type = (row.get("file_type") or "").strip()
        source_sha256 = (row.get("sha256") or "").strip().lower()
        if not species_column or not experiment_accession or not local_path_text:
            continue
        key = (species_column, experiment_accession)

        if file_type in EXPRESSION_FILE_TYPES:
            candidate = Path(local_path_text)
            existing = expression_sources.get(key)
            candidate_source = (candidate, source_sha256, file_type)
            if existing is None:
                expression_sources[key] = candidate_source
            elif existing[2] == file_type and existing != candidate_source:
                raise ValueError(
                    "Downloaded-files manifest contains conflicting expression "
                    f"matrices for {key} and {file_type}: {existing[0]} and {candidate}"
                )
            elif existing[2] == "fpkms" and file_type == "tpms":
                expression_sources[key] = (candidate, source_sha256, file_type)

        if file_type == "configuration_xml":
            candidate = Path(local_path_text)
            existing = configuration_sources.get(key)
            candidate_source = (candidate, source_sha256)
            if existing is not None and existing != candidate_source:
                raise ValueError(
                    "Downloaded-files manifest contains multiple configuration "
                    f"XML files for {key}: {existing[0]} and {candidate}"
                )
            configuration_sources[key] = candidate_source

        if file_type not in METADATA_FILE_TYPES:
            continue

        priority = metadata_file_priority(local_path_text)
        file_name = Path(local_path_text).name
        current = best_priorities.get(key)
        candidate_priority = (priority, file_name)
        if current is None or candidate_priority < current:
            best_priorities[key] = candidate_priority
            best_rows[key] = row

    jobs: list[MetadataJob] = []
    for (species_column, experiment_accession), row in sorted(best_rows.items()):
        local_path = Path((row.get("local_path") or "").strip())
        source_database = (row.get("source_database") or "ExpressionAtlas").strip()
        metadata_sha256 = (row.get("sha256") or "").strip().lower()
        key = (species_column, experiment_accession)
        expression_source = expression_sources.get(key)
        configuration_source = configuration_sources.get(key)
        jobs.append(
            MetadataJob(
                metadata_tsv=local_path,
                experiment_accession=experiment_accession,
                species_column=species_column,
                source_database=source_database,
                metadata_file_kind=metadata_file_kind(local_path),
                expression_tsv=(expression_source[0] if expression_source is not None else None),
                configuration_xml=(
                    configuration_source[0] if configuration_source is not None else None
                ),
                metadata_sha256=metadata_sha256,
                expression_sha256=(expression_source[1] if expression_source is not None else ""),
                configuration_sha256=(
                    configuration_source[1] if configuration_source is not None else ""
                ),
            )
        )

    return jobs


def preflight_metadata_jobs(jobs: list[MetadataJob]) -> None:
    """Reject incomplete metadata authorities before importing any records.

    Every selected metadata experiment must be bound to a non-empty expression
    matrix and authoritative configuration XML.  This prevents a legacy SDRF
    from being published without a defensible ``gN``-to-assay mapping.

    Args:
        jobs: Preferred per-experiment metadata jobs.

    Raises:
        ValueError: If no jobs were selected or any required source is absent.
    """
    if not jobs:
        raise ValueError("Downloaded-files manifest selected no sample-metadata jobs")
    failures: list[str] = []
    for job in jobs:
        missing: list[str] = []
        if not job.metadata_tsv.is_file() or job.metadata_tsv.stat().st_size == 0:
            missing.append("sample_metadata")
        if (
            job.expression_tsv is None
            or not job.expression_tsv.is_file()
            or job.expression_tsv.stat().st_size == 0
        ):
            missing.append("tpms_or_fpkms")
        if (
            job.configuration_xml is None
            or not job.configuration_xml.is_file()
            or job.configuration_xml.stat().st_size == 0
        ):
            missing.append("configuration_xml")
        if missing:
            failures.append(
                f"{job.species_column} {job.experiment_accession}: {','.join(missing)}"
            )
    if failures:
        examples = "; ".join(failures[:3])
        raise ValueError(
            f"Preflight found {len(failures)}/{len(jobs)} incomplete metadata "
            f"authorities. Examples: {examples}. Prepare the legacy raw sources "
            "with 03_prepare_existing_atlas_downloads.sh before import."
        )


def write_summary(path: Path, results: list[MetadataResult]) -> None:
    """Write the metadata import summary."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "metadata_tsv",
        "experiment_accession",
        "species_column",
        "metadata_file_kind",
        "action",
        "success",
        "metadata_records",
        "wide_rows",
        "long_rows",
        "mapped_group_records",
        "message",
    ]
    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "metadata_tsv": str(result.metadata_tsv),
                    "experiment_accession": result.experiment_accession,
                    "species_column": result.species_column,
                    "metadata_file_kind": result.metadata_file_kind,
                    "action": result.action,
                    "success": "true" if result.success else "false",
                    "metadata_records": result.metadata_records,
                    "wide_rows": result.wide_rows,
                    "long_rows": result.long_rows,
                    "mapped_group_records": result.mapped_group_records,
                    "message": result.message,
                }
            )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Import Expression Atlas sample metadata to Parquet."
    )
    parser.add_argument("--downloaded_files_tsv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--force_import", default="false")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the sample metadata importer."""

    args = parse_args(argv)
    require_pyarrow()
    downloaded_files_tsv = Path(args.downloaded_files_tsv)
    output_dir = Path(args.output_dir)
    force = parse_bool(args.force_import, default=False)
    summary_path = output_dir / "manifests" / "atlas_sample_metadata_import_summary.tsv"

    if not downloaded_files_tsv.exists():
        raise SystemExit(f"Downloaded-files manifest does not exist: {downloaded_files_tsv}")

    jobs = build_jobs(downloaded_files_tsv=downloaded_files_tsv)
    try:
        preflight_metadata_jobs(jobs)
    except ValueError as error:
        raise SystemExit(f"ERROR: {error}") from error
    print(f"Python sample metadata importer found {len(jobs)} metadata jobs", flush=True)
    results: list[MetadataResult] = []
    for index, job in enumerate(jobs, start=1):
        if index == 1 or index % 25 == 0 or index == len(jobs):
            print(
                f"Importing metadata {index}/{len(jobs)}: "
                f"{job.species_column} {job.experiment_accession}",
                flush=True,
            )
        results.append(write_partitioned_metadata(job=job, output_dir=output_dir, force=force))

    write_summary(summary_path, results)
    success = sum(1 for item in results if item.success)
    long_rows = sum(item.long_rows for item in results if item.success)
    mapped_groups = sum(item.mapped_group_records for item in results if item.success)
    print(f"Wrote sample metadata import summary: {summary_path}", flush=True)
    print(f"Successful metadata imports: {success}/{len(jobs)}", flush=True)
    print(f"Total metadata long rows: {long_rows}", flush=True)
    print(f"Total authoritative expression-group metadata rows: {mapped_groups}", flush=True)
    if len(jobs) == 0 or success != len(jobs):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
