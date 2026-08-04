#!/usr/bin/env python3
"""Prepare legacy Expression Atlas downloads for the strict importer.

The historical download manifest used working-directory-relative paths and did
not record SHA-256 digests or Expression Atlas configuration XML files.  This
utility treats that manifest as a catalogue only.  It resolves every retained
file against an explicit raw-download root, verifies any existing checksum,
downloads missing configuration XML files into a separate supplement root,
and atomically publishes a new manifest containing absolute paths and observed
checksums.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


ACCESSION_PATTERN = re.compile(r"^E-[A-Z0-9]+-[0-9]+$")
COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPRESSION_TYPES = frozenset({"tpms", "fpkms"})
REQUIRED_SOURCE_TYPES = frozenset({"sample_metadata"})
OUTPUT_FIELDS = (
    "species_column",
    "atlas_species_query",
    "experiment_accession",
    "file_type",
    "file_name",
    "url",
    "local_path",
    "action",
    "success",
    "local_bytes",
    "sha256",
    "checked_at",
)


@dataclass(frozen=True)
class PreparedSource:
    """One validated raw source for the prepared manifest."""

    species_column: str
    atlas_species_query: str
    experiment_accession: str
    file_type: str
    file_name: str
    url: str
    local_path: Path
    action: str
    local_bytes: int
    sha256: str


def parse_bool(value: object, *, default: bool = False) -> bool:
    """Parse a command-line boolean.

    Args:
        value: Value to parse.
        default: Result for ``None`` or an empty string.

    Returns:
        Parsed Boolean value.

    Raises:
        ValueError: If the value is not recognisably true or false.
    """
    if value is None or str(value).strip() == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    raise ValueError(f"Cannot parse Boolean value: {value!r}")


def now_iso() -> str:
    """Return a timezone-aware ISO-8601 timestamp."""
    return dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a file's SHA-256 digest.

    Args:
        path: Existing regular file.
        chunk_size: Bytes read per update.

    Returns:
        Lower-case hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> list[dict[str, str]]:
    """Read and validate a legacy downloaded-files manifest.

    Args:
        path: Tab-separated manifest path.

    Returns:
        Manifest rows.

    Raises:
        ValueError: If the file is empty, comma-separated or lacks required
            columns.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Source manifest is missing or empty: {path}")
    with path.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = reader.fieldnames or []
        required = {
            "species_column",
            "experiment_accession",
            "file_type",
            "local_path",
            "success",
        }
        missing = sorted(required - set(fieldnames))
        if missing:
            raise ValueError(
                "Source manifest lacks required tab-separated columns: "
                + ", ".join(missing)
            )
        rows = list(reader)
    if not rows:
        raise ValueError(f"Source manifest contains no data rows: {path}")
    return rows


def validate_component(value: str, *, label: str, pattern: re.Pattern[str]) -> str:
    """Validate a path or identifier component.

    Args:
        value: Component text.
        label: User-facing field label.
        pattern: Complete-match validation pattern.

    Returns:
        Stripped component.

    Raises:
        ValueError: If the component is empty or unsafe.
    """
    text = value.strip()
    if not pattern.fullmatch(text):
        raise ValueError(f"Invalid {label}: {value!r}")
    return text


def row_file_name(row: dict[str, str]) -> str:
    """Return a safe basename from a manifest row.

    Args:
        row: Manifest row.

    Returns:
        Validated file basename.

    Raises:
        ValueError: If no safe basename is available.
    """
    file_name = (row.get("file_name") or "").strip()
    if not file_name:
        file_name = Path((row.get("local_path") or "").strip()).name
    if not file_name or file_name in {".", ".."} or Path(file_name).name != file_name:
        raise ValueError(f"Invalid source filename: {file_name!r}")
    if any(character in file_name for character in ("/", "\\", "\x00")):
        raise ValueError(f"Unsafe source filename: {file_name!r}")
    return file_name


def metadata_priority(row: dict[str, str]) -> tuple[int, str]:
    """Return the deterministic preference for an Atlas metadata source.

    Args:
        row: Sample-metadata manifest row.

    Returns:
        Priority and filename; lower values are preferred.
    """
    name = row_file_name(row).lower()
    if "condensed-sdrf" in name and not name.endswith(".bak"):
        priority = 0
    elif name.endswith(".sdrf.txt"):
        priority = 1
    elif name.endswith(".bak"):
        priority = 9
    else:
        priority = 5
    return priority, name


def source_path(*, raw_root: Path, row: dict[str, str]) -> Path:
    """Resolve one legacy source against the explicit raw root.

    Args:
        raw_root: Existing Expression Atlas source root.
        row: Manifest row.

    Returns:
        Absolute source path under ``raw_root/downloads``.
    """
    species = validate_component(
        row.get("species_column") or "",
        label="species_column",
        pattern=COMPONENT_PATTERN,
    )
    accession = validate_component(
        row.get("experiment_accession") or "",
        label="experiment_accession",
        pattern=ACCESSION_PATTERN,
    )
    return (raw_root / "downloads" / species / accession / row_file_name(row)).resolve()


def validate_source(*, path: Path, expected_sha256: str) -> tuple[int, str]:
    """Validate a raw source and optional legacy checksum.

    Args:
        path: Expected source path.
        expected_sha256: Optional checksum from the legacy manifest.

    Returns:
        File size and observed digest.

    Raises:
        ValueError: If the file is missing, empty or checksum-inconsistent.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Raw source is missing or empty: {path}")
    expected = expected_sha256.strip().lower()
    if expected and not SHA256_PATTERN.fullmatch(expected):
        raise ValueError(f"Malformed source SHA-256 for {path}: {expected!r}")
    observed = sha256_file(path)
    if expected and observed != expected:
        raise ValueError(
            f"Source SHA-256 mismatch for {path}: manifest={expected}, observed={observed}"
        )
    return path.stat().st_size, observed


def configuration_url(accession: str, experiment_rows: Iterable[dict[str, str]]) -> str:
    """Derive the official configuration-XML URL.

    Args:
        accession: Expression Atlas experiment accession.
        experiment_rows: Legacy rows for that experiment.

    Returns:
        HTTPS URL for the official configuration XML.
    """
    file_name = f"{accession}-configuration.xml"
    for row in experiment_rows:
        url = (row.get("url") or "").strip()
        if url.startswith("https://"):
            return urllib.parse.urljoin(url, urllib.parse.quote(file_name))
    return (
        "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/experiments/"
        f"{accession}/{urllib.parse.quote(file_name)}"
    )


def download_atomic(
    *,
    url: str,
    destination: Path,
    timeout_seconds: int,
    retries: int,
) -> str:
    """Download a non-empty source using an atomic rename.

    Args:
        url: HTTPS source URL.
        destination: Final local path.
        timeout_seconds: Per-request timeout.
        retries: Number of retries after the first attempt.

    Returns:
        ``downloaded`` or ``reused_existing_supplement``.

    Raises:
        ValueError: If the URL is not HTTPS or all attempts fail.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"Configuration source must be an HTTPS URL: {url}")
    if destination.is_file() and destination.stat().st_size > 0:
        return "reused_existing_supplement"

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".partial",
        dir=str(destination.parent),
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    last_error = "unknown error"
    try:
        for attempt in range(retries + 1):
            try:
                request = urllib.request.Request(
                    url=url,
                    headers={"User-Agent": "E3AtlasDuckplyr/0.5.1"},
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    with temporary_path.open(mode="wb") as handle:
                        shutil.copyfileobj(response, handle)
                if temporary_path.stat().st_size == 0:
                    raise ValueError("downloaded file was empty")
                temporary_path.replace(destination)
                return "downloaded"
            except (OSError, ValueError, urllib.error.URLError) as error:
                last_error = str(error)
                if attempt < retries:
                    time.sleep(min(5, attempt + 1))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    raise ValueError(f"Failed to download {url}: {last_error}")


def prepare_existing_sources(
    *,
    source_manifest: Path,
    raw_root: Path,
    supplement_root: Path,
    download_missing_configuration: bool,
    timeout_seconds: int,
    retries: int,
) -> list[PreparedSource]:
    """Prepare strict, checksum-recorded sources from a legacy manifest.

    Args:
        source_manifest: Historical downloaded-files manifest.
        raw_root: Root containing its ``downloads`` tree.
        supplement_root: New root for missing configuration XML files.
        download_missing_configuration: Whether missing XML may be fetched.
        timeout_seconds: Per-request timeout.
        retries: Retry count for XML acquisition.

    Returns:
        Validated prepared sources.

    Raises:
        ValueError: If any claimed source or required experiment component is
            missing, duplicated or invalid.
    """
    raw_root = raw_root.resolve()
    supplement_root = supplement_root.resolve()
    if not raw_root.is_dir():
        raise ValueError(f"Raw root does not exist: {raw_root}")
    rows = read_manifest(source_manifest)
    successful_rows = [
        row for row in rows if parse_bool(row.get("success"), default=False)
    ]
    expression_rows = [
        row for row in successful_rows if (row.get("file_type") or "").strip() in EXPRESSION_TYPES
    ]
    if not expression_rows:
        raise ValueError("Source manifest contains no successful TPM/FPKM rows")

    selected_keys = {
        (
            validate_component(
                row.get("species_column") or "",
                label="species_column",
                pattern=COMPONENT_PATTERN,
            ),
            validate_component(
                row.get("experiment_accession") or "",
                label="experiment_accession",
                pattern=ACCESSION_PATTERN,
            ),
        )
        for row in expression_rows
    }
    preferred_metadata: dict[tuple[str, str], dict[str, str]] = {}
    for row in successful_rows:
        if (row.get("file_type") or "").strip() != "sample_metadata":
            continue
        key = (
            (row.get("species_column") or "").strip(),
            (row.get("experiment_accession") or "").strip(),
        )
        if key not in selected_keys:
            continue
        current = preferred_metadata.get(key)
        if current is None or metadata_priority(row) < metadata_priority(current):
            preferred_metadata[key] = row

    scientific_rows = [
        row
        for row in successful_rows
        if (
            (row.get("file_type") or "").strip() in EXPRESSION_TYPES
            or (row.get("file_type") or "").strip() == "configuration_xml"
            or row is preferred_metadata.get(
                (
                    (row.get("species_column") or "").strip(),
                    (row.get("experiment_accession") or "").strip(),
                )
            )
        )
    ]
    prepared: dict[tuple[str, str, str, str], PreparedSource] = {}
    available_types: dict[tuple[str, str], set[str]] = {key: set() for key in selected_keys}
    rows_by_experiment: dict[tuple[str, str], list[dict[str, str]]] = {
        key: [] for key in selected_keys
    }

    for index, row in enumerate(scientific_rows, start=1):
        if index == 1 or index % 50 == 0 or index == len(scientific_rows):
            print(
                f"Verifying retained raw source {index}/{len(scientific_rows)}",
                flush=True,
            )
        species = (row.get("species_column") or "").strip()
        accession = (row.get("experiment_accession") or "").strip()
        key = (species, accession)
        if key not in selected_keys:
            continue
        rows_by_experiment[key].append(row)
        file_type = (row.get("file_type") or "").strip()
        if not file_type:
            raise ValueError(f"Manifest row has an empty file_type for {species} {accession}")
        file_name = row_file_name(row)
        path = source_path(raw_root=raw_root, row=row)
        local_bytes, digest = validate_source(
            path=path,
            expected_sha256=row.get("sha256") or "",
        )
        source = PreparedSource(
            species_column=species,
            atlas_species_query=(row.get("atlas_species_query") or "").strip(),
            experiment_accession=accession,
            file_type=file_type,
            file_name=file_name,
            url=(row.get("url") or "").strip(),
            local_path=path,
            action="verified_existing_raw_source",
            local_bytes=local_bytes,
            sha256=digest,
        )
        source_key = (species, accession, file_type, file_name)
        existing = prepared.get(source_key)
        if existing is not None and existing != source:
            raise ValueError(f"Conflicting legacy source rows for {source_key!r}")
        prepared[source_key] = source
        available_types[key].add(file_type)

    ordered_keys = sorted(selected_keys)
    for index, (species, accession) in enumerate(ordered_keys, start=1):
        key = (species, accession)
        if "configuration_xml" in available_types[key]:
            continue
        if index == 1 or index % 25 == 0 or index == len(ordered_keys):
            print(
                f"Acquiring configuration XML {index}/{len(ordered_keys)}: "
                f"{species} {accession}",
                flush=True,
            )
        if not download_missing_configuration:
            raise ValueError(
                f"Configuration XML is absent for {species} {accession}; "
                "rerun with --download_missing_configuration true"
            )
        file_name = f"{accession}-configuration.xml"
        destination = (
            supplement_root / "downloads" / species / accession / file_name
        ).resolve()
        url = configuration_url(accession, rows_by_experiment[key])
        action = download_atomic(
            url=url,
            destination=destination,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
        local_bytes, digest = validate_source(path=destination, expected_sha256="")
        source = PreparedSource(
            species_column=species,
            atlas_species_query=(
                rows_by_experiment[key][0].get("atlas_species_query") or ""
            ).strip(),
            experiment_accession=accession,
            file_type="configuration_xml",
            file_name=file_name,
            url=url,
            local_path=destination,
            action=action,
            local_bytes=local_bytes,
            sha256=digest,
        )
        prepared[(species, accession, "configuration_xml", file_name)] = source
        available_types[key].add("configuration_xml")

    incomplete: list[str] = []
    for key, file_types in sorted(available_types.items()):
        missing = set(REQUIRED_SOURCE_TYPES) - file_types
        if not (file_types & EXPRESSION_TYPES):
            missing.add("tpms_or_fpkms")
        if "configuration_xml" not in file_types:
            missing.add("configuration_xml")
        if missing:
            incomplete.append(f"{key[0]} {key[1]}: {','.join(sorted(missing))}")
    if incomplete:
        raise ValueError(
            "Prepared source contract is incomplete:\n" + "\n".join(incomplete)
        )
    return [prepared[key] for key in sorted(prepared)]


def write_manifest_atomic(*, path: Path, sources: Iterable[PreparedSource]) -> None:
    """Atomically write the prepared tab-separated manifest.

    Args:
        path: Destination manifest.
        sources: Validated sources to publish.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".partial",
        dir=str(path.parent),
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    checked_at = now_iso()
    try:
        with temporary_path.open(mode="w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
            writer.writeheader()
            for source in sources:
                writer.writerow(
                    {
                        "species_column": source.species_column,
                        "atlas_species_query": source.atlas_species_query,
                        "experiment_accession": source.experiment_accession,
                        "file_type": source.file_type,
                        "file_name": source.file_name,
                        "url": source.url,
                        "local_path": str(source.local_path),
                        "action": source.action,
                        "success": "true",
                        "local_bytes": source.local_bytes,
                        "sha256": source.sha256,
                        "checked_at": checked_at,
                    }
                )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Prepare legacy Expression Atlas downloads for strict import.",
    )
    parser.add_argument("--source_manifest", required=True)
    parser.add_argument("--raw_root", required=True)
    parser.add_argument("--supplement_root", required=True)
    parser.add_argument("--output_manifest", required=True)
    parser.add_argument("--download_missing_configuration", default="true")
    parser.add_argument("--timeout_seconds", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Prepare and publish a strict downloaded-files manifest."""
    args = parse_args(argv)
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout_seconds must be at least 1")
    if args.retries < 0:
        raise SystemExit("--retries cannot be negative")
    output_manifest = Path(args.output_manifest)
    try:
        sources = prepare_existing_sources(
            source_manifest=Path(args.source_manifest),
            raw_root=Path(args.raw_root),
            supplement_root=Path(args.supplement_root),
            download_missing_configuration=parse_bool(
                args.download_missing_configuration,
                default=True,
            ),
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        write_manifest_atomic(path=output_manifest, sources=sources)
    except (OSError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    experiment_count = len(
        {(source.species_column, source.experiment_accession) for source in sources}
    )
    print(f"Prepared sources: {len(sources)}", flush=True)
    print(f"Complete experiments: {experiment_count}", flush=True)
    print(f"Wrote strict downloaded-files manifest: {output_manifest}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
