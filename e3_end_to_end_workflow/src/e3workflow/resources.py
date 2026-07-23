"""Controlled resource manifests for reusable expression and pocket evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Sequence

from e3workflow.errors import ManifestError
from e3workflow.io_utils import sha256_file, write_tsv
from e3workflow.manifests import SHA256_PATTERN, parse_boolean

RESOURCE_COLUMNS = (
    "resource_id",
    "resource_type",
    "species_column",
    "dataset",
    "path",
    "sha256",
    "include",
)

EXPRESSION_RESOURCE_TYPES = frozenset(
    {"atlas_expression_long", "atlas_sample_metadata_long", "atlas_sample_metadata_wide"}
)
LIGANDABILITY_DATASETS = frozenset(
    {
        "accession_status",
        "alphafold_metadata",
        "asset_manifest",
        "model_quality",
        "fpocket_pockets",
        "p2rank_pockets",
        "joined_pockets",
        "pocket_residue_mappings",
        "pocket_quality",
        "external_commands",
        "validation",
    }
)


def _species_partition(path: Path) -> str:
    """Return the Hive-style species value present in one resource path."""
    for part in path.parts:
        if part.startswith("species_column="):
            return part.split("=", maxsplit=1)[1]
    return ""


def resource_record(
    *,
    resource_id: str,
    resource_type: str,
    species_column: str,
    dataset: str,
    path: Path,
) -> dict[str, str]:
    """Build one checksum-bound resource record.

    Args:
        resource_id: Stable record identifier.
        resource_type: Broad resource class.
        species_column: Optional species partition.
        dataset: Logical dataset name.
        path: Existing resource file.

    Returns:
        Flat manifest record.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise ManifestError(f"Resource file is missing or empty: {source}")
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "species_column": species_column,
        "dataset": dataset,
        "path": str(source),
        "sha256": sha256_file(source),
        "include": "true",
    }


def build_expression_manifest(*, expression_root: Path, output_path: Path) -> Path:
    """Inventory Expression Atlas Parquet files with full checksums.

    Args:
        expression_root: Root containing the three Atlas Parquet dataset directories.
        output_path: Destination TSV manifest.

    Returns:
        Resolved output path.
    """
    root = Path(expression_root).expanduser().resolve()
    if not root.is_dir():
        raise ManifestError(f"Expression Parquet root does not exist: {root}")
    records: list[dict[str, str]] = []
    for resource_type in sorted(EXPRESSION_RESOURCE_TYPES):
        dataset_root = root / resource_type
        if not dataset_root.is_dir():
            continue
        for path in sorted(dataset_root.rglob("*.parquet")):
            species = _species_partition(path)
            if not species:
                raise ManifestError(
                    "Expression Parquet is not below a species_column partition: "
                    f"{path}"
                )
            relative = path.relative_to(root)
            records.append(
                resource_record(
                    resource_id=f"expression:{relative}",
                    resource_type=resource_type,
                    species_column=species,
                    dataset=path.stem,
                    path=path,
                )
            )
    if not records:
        raise ManifestError(f"No Expression Atlas Parquet files were found below {root}")
    if not any(row["resource_type"] == "atlas_expression_long" for row in records):
        raise ManifestError("Expression resource has no atlas_expression_long Parquet files")
    destination = Path(output_path).expanduser().resolve()
    write_tsv(destination, records, RESOURCE_COLUMNS)
    return destination


def build_ligandability_manifest(
    *, roots: Sequence[Path], output_path: Path
) -> Path:
    """Inventory standard ligandability Parquet tables across one or more runs.

    Args:
        roots: Existing ligandability run roots.
        output_path: Destination TSV manifest.

    Returns:
        Resolved output path.
    """
    if not roots:
        raise ManifestError("At least one ligandability root is required")
    records: list[dict[str, str]] = []
    seen: set[Path] = set()
    for root_index, supplied_root in enumerate(roots, start=1):
        root = Path(supplied_root).expanduser().resolve()
        if not root.is_dir():
            raise ManifestError(f"Ligandability root does not exist: {root}")
        candidates = sorted(root.glob("tables/parquet/*.parquet"))
        if not candidates:
            candidates = sorted(root.rglob("tables/parquet/*.parquet"))
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen or path.stem not in LIGANDABILITY_DATASETS:
                continue
            seen.add(resolved)
            records.append(
                resource_record(
                    resource_id=f"ligandability:{root_index}:{path.stem}",
                    resource_type="ligandability",
                    species_column="",
                    dataset=path.stem,
                    path=path,
                )
            )
    required = {"model_quality", "joined_pockets", "pocket_residue_mappings", "pocket_quality"}
    observed = {row["dataset"] for row in records}
    missing = sorted(required.difference(observed))
    if missing:
        raise ManifestError(
            "Ligandability roots lack required Parquet datasets: " + ", ".join(missing)
        )
    destination = Path(output_path).expanduser().resolve()
    write_tsv(destination, records, RESOURCE_COLUMNS)
    return destination


def build_domain_cache_manifest(*, cache_root: Path, output_path: Path) -> Path:
    """Inventory terminal InterPro API cache files for reproducible offline reuse.

    Transient download failures are deliberately not cached by the downloader and therefore cannot
    enter this manifest. Confirmed protein annotations, proteins without entries and confirmed
    absent accessions are retained so missingness remains auditable.
    """
    root = Path(cache_root).expanduser().resolve()
    if not root.is_dir():
        raise ManifestError(f"InterPro cache root does not exist: {root}")
    records: list[dict[str, str]] = []
    accessions: set[str] = set()
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"Unreadable InterPro cache JSON {path}: {exc}") from exc
        accession = str(payload.get("requested_accession", "")).strip().upper()
        status = str(payload.get("retrieval_status", ""))
        if not accession or accession in accessions:
            raise ManifestError(f"Empty or duplicate accession in InterPro cache: {path}")
        if status not in {"ANNOTATED", "PROTEIN_WITHOUT_ENTRIES", "NOT_FOUND"}:
            raise ManifestError(f"Non-terminal InterPro cache status {status!r}: {path}")
        accessions.add(accession)
        records.append(
            resource_record(
                resource_id=f"interpro:{accession}",
                resource_type="interpro_annotation_cache",
                species_column="",
                dataset=status,
                path=path,
            )
        )
    if not records:
        raise ManifestError(f"No terminal InterPro cache files were found below {root}")
    destination = Path(output_path).expanduser().resolve()
    write_tsv(destination, records, RESOURCE_COLUMNS)
    return destination


def read_resource_manifest(
    *,
    path: Path,
    allowed_resource_types: Iterable[str] | None = None,
    verify_checksums: bool = True,
) -> list[dict[str, str]]:
    """Validate and return included rows from one resource manifest.

    Args:
        path: Manifest TSV path.
        allowed_resource_types: Optional accepted type set.
        verify_checksums: Recalculate every included checksum.

    Returns:
        Included manifest rows with paths resolved to absolute strings.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ManifestError(f"Resource manifest does not exist: {source}")
    allowed = None if allowed_resource_types is None else set(allowed_resource_types)
    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != RESOURCE_COLUMNS:
            raise ManifestError(
                "Resource manifest columns must be "
                f"{RESOURCE_COLUMNS}; observed {reader.fieldnames}"
            )
        for line_number, row in enumerate(reader, start=2):
            resource_id = row["resource_id"].strip()
            resource_type = row["resource_type"].strip()
            if not resource_id or resource_id in seen_ids:
                raise ManifestError(
                    f"Empty or duplicate resource_id at {source}:{line_number}"
                )
            seen_ids.add(resource_id)
            if not parse_boolean(row["include"], f"{source}:{line_number} include"):
                continue
            if allowed is not None and resource_type not in allowed:
                raise ManifestError(
                    f"Unsupported resource_type {resource_type!r} at {source}:{line_number}"
                )
            resource_path = Path(row["path"]).expanduser()
            resource_path = (
                (source.parent / resource_path).resolve()
                if not resource_path.is_absolute()
                else resource_path.resolve()
            )
            if not resource_path.is_file() or resource_path.stat().st_size == 0:
                raise ManifestError(
                    f"Included resource is missing or empty at {source}:{line_number}: "
                    f"{resource_path}"
                )
            expected = row["sha256"].strip().lower()
            if not SHA256_PATTERN.fullmatch(expected):
                raise ManifestError(f"Invalid sha256 at {source}:{line_number}")
            if verify_checksums:
                observed = sha256_file(resource_path)
                if observed != expected:
                    raise ManifestError(
                        f"Resource checksum mismatch at {source}:{line_number}: "
                        f"{expected} != {observed}"
                    )
            record = dict(row)
            record["path"] = str(resource_path)
            records.append(record)
    if not records:
        raise ManifestError(f"Resource manifest selects no included files: {source}")
    return records


def paths_for_dataset(records: Iterable[dict[str, str]], dataset: str) -> list[Path]:
    """Return sorted paths for one logical dataset from validated records."""
    return sorted(Path(record["path"]) for record in records if record["dataset"] == dataset)
