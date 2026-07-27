"""General IO helpers used by the E3 source rebuild scripts."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Iterable, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

HIDDEN_FILE_NAMES = {".DS_Store"}
HIDDEN_PREFIXES = ("._",)
FASTA_SUFFIXES = {".fa", ".faa", ".fasta", ".fna"}
TABULAR_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
TEXT_SUFFIXES = {".txt", ".sql", ".md"}
PARQUET_SUFFIXES = {".parquet"}
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}

# These aliases are used only for the derived output layout and DuckDB view
# names. The original inherited paths are still carried in _source_file fields
# and in the source manifest.
CANONICAL_PATH_PREFIXES = (
    ("Main_folder/E3_database", "curated_e3_database"),
    ("Main_folder/Reports", "inherited_reports"),
    ("Main_folder/Other_people_data", "literature_reference_datasets"),
    (
        "Other_things/Denbi/denbi_data/E3_discovery_engine",
        "deepclust_discovery_engine",
    ),
    (
        "Other_things/Denbi/denbi_data/E3_ligase_eukaryote_db",
        "eukaryote_reference_e3_database",
    ),
    ("Other_things/Drost_lab_E3_ligases", "e3_ligase_discovery_inputs"),
    ("Other_things/Drost_lab_ligandability", "ligandability_inputs"),
    ("Other_things/Drost_lab_proteomes", "proteome_source_inputs"),
    ("Other_things/downloaded_datasets", "downloaded_reference_datasets"),
    ("Other_things/Desktop", "inherited_desktop_outputs"),
    ("Other_things", "misc_inherited_support_files"),
)


def normalise_relative_path(path: Path | str) -> str:
    """Return a POSIX-style relative path string."""
    if isinstance(path, Path):
        value = path.as_posix()
    else:
        value = str(path).replace("\\", "/")
    return value.lstrip("./")


def canonical_relative_path(relative_path: Path | str) -> str:
    """Return a clearer derived path while preserving source traceability.

    The inherited project contains vague top-level names such as
    ``Main_folder`` and ``Other_things``. This function maps those to more
    explicit names for *derived outputs*. It deliberately does not change the
    source manifest or provenance columns.
    """
    normalised = normalise_relative_path(relative_path)
    for old_prefix, new_prefix in CANONICAL_PATH_PREFIXES:
        if normalised == old_prefix:
            return new_prefix
        if normalised.startswith(f"{old_prefix}/"):
            return f"{new_prefix}/{normalised[len(old_prefix) + 1:]}"
    return normalised


def is_hidden_or_macos_sidecar(path: Path) -> bool:
    """Return true for hidden/macOS resource-fork sidecar files."""
    name = path.name
    if name in HIDDEN_FILE_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in HIDDEN_PREFIXES)


def path_has_hidden_or_macos_sidecar_part(path: Path) -> bool:
    """Return true if any path component is hidden or an AppleDouble sidecar."""
    return any(is_hidden_or_macos_sidecar(Path(part)) for part in path.parts)


def sha256_file(path: Path, chunk_size: int = 1_048_576) -> str:
    """Return the SHA256 checksum for a file using chunked reads."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_name(value: str, max_length: int = 180) -> str:
    """Create a filesystem-safe identifier from an arbitrary string."""
    value = value.strip().replace("\\", "/")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    if not value:
        value = "unnamed"
    return value[:max_length]


def safe_path_from_relative(relative_path: Path | str) -> Path:
    """Create a safe nested path from a relative POSIX path."""
    normalised = normalise_relative_path(relative_path)
    parts = [safe_name(part) for part in normalised.split("/") if part]
    if not parts:
        return Path("unnamed")
    return Path(*parts)


def derived_output_path(
    base_dir: Path,
    relative_path: Path | str,
    suffix: str = ".parquet",
    sheet_name: str = "",
) -> Path:
    """Return a clear, nested derived output path for a source file."""
    canonical = canonical_relative_path(relative_path)
    safe_path = safe_path_from_relative(canonical)
    parent = safe_path.parent
    file_name = safe_path.name

    if sheet_name:
        stem = Path(file_name).stem
        file_name = f"{stem}__sheet__{safe_name(sheet_name)}"

    if suffix and not file_name.endswith(suffix):
        file_name = f"{file_name}{suffix}"

    return base_dir / parent / file_name


def table_name_from_relative_path(relative_path: Path | str, sheet_name: str = "") -> str:
    """Return a stable table/view identifier from a derived relative path."""
    canonical = canonical_relative_path(relative_path)
    base = safe_name(canonical.replace("/", "__"))
    if sheet_name:
        base = f"{base}__sheet__{safe_name(sheet_name)}"
    return base


def guess_file_format(path: Path) -> str:
    """Classify a file format using its suffix."""
    suffix = path.suffix.lower()
    if suffix in FASTA_SUFFIXES:
        return "fasta"
    if suffix in TABULAR_SUFFIXES:
        return suffix.lstrip(".")
    if suffix in TEXT_SUFFIXES:
        return suffix.lstrip(".")
    if suffix in PARQUET_SUFFIXES:
        return "parquet"
    if suffix in SQLITE_SUFFIXES:
        return "sqlite"
    return suffix.lstrip(".") or "unknown"


def guess_logical_role(relative_path: str) -> str:
    """Guess the likely biological/computational role of a source file."""
    lower_path = relative_path.lower()
    role_checks = [
        ("orthofinder", "orthology"),
        ("orthogroup", "orthology"),
        ("hog", "orthology"),
        ("deepclust", "deepclust"),
        ("pocket", "ligandability"),
        ("fpocket", "ligandability"),
        ("p2rank", "ligandability"),
        ("prank", "ligandability"),
        ("ligandability", "ligandability"),
        ("druggability", "ligandability"),
        ("alphafold", "structure"),
        ("plddt", "structure_confidence"),
        ("conservation", "conservation"),
        ("e3_ligase", "e3_ligase_source"),
        ("e3_ligases", "e3_ligase_source"),
        ("go", "go_terms"),
        ("keyword", "keyword_search"),
        ("uniprot", "uniprot"),
        ("paper", "literature"),
        ("publication", "literature"),
        ("mapped_data", "literature_mapping"),
        ("idmapping", "identifier_mapping"),
        ("sequence", "sequence"),
        ("fasta", "sequence"),
        ("sql_queries", "sql_query"),
        ("query", "query_or_candidate"),
        ("candidate", "candidate_list"),
        ("organism", "organism_metadata"),
        ("taxonomy", "organism_metadata"),
        ("schema", "documentation"),
        ("readme", "documentation"),
    ]
    for needle, role in role_checks:
        if needle in lower_path:
            return role
    return "unclassified"


def write_tsv(records: Sequence[Mapping[str, object]], output_path: Path) -> None:
    """Write records to a tab-separated file.

    Records produced during auditing often accumulate optional diagnostic
    fields as a run progresses.  The writer therefore uses the ordered union of
    all keys, rather than only the keys present in the first record.  This keeps
    partially failed debug reports writable, which is important for diagnosing
    inherited-data edge cases.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record.keys():
            if key not in seen:
                fieldnames.append(str(key))
                seen.add(str(key))

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def maybe_write_parquet(records: Sequence[Mapping[str, object]], output_path: Path) -> bool:
    """Write records to Parquet if pandas and pyarrow are available.

    Returns true when a Parquet file was written. Returns false when the
    optional dependency is unavailable.
    """
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return False

    if not records:
        return False
    try:
        dataframe = pd.DataFrame.from_records(records)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_parquet(output_path, index=False)
        return True
    except ImportError:
        return False


def json_dumps_compact(value: object) -> str:
    """Return deterministic compact JSON for audit columns."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def iter_source_files(root: Path, include_hidden: bool = False) -> Iterable[Path]:
    """Yield source files under root in deterministic order."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not include_hidden and path_has_hidden_or_macos_sidecar_part(path):
            continue
        yield path


def is_probable_parquet_file(path: Path) -> bool:
    """Return true if a file has a Parquet-like PAR1 header and footer."""
    if path.suffix.lower() != ".parquet":
        return False
    if path_has_hidden_or_macos_sidecar_part(path):
        return False
    try:
        if path.stat().st_size < 8:
            return False
        with path.open("rb") as handle:
            header = handle.read(4)
            handle.seek(-4, 2)
            footer = handle.read(4)
        return header == b"PAR1" and footer == b"PAR1"
    except OSError as exc:
        LOGGER.warning("Could not inspect Parquet file %s: %s", path, exc)
        return False
