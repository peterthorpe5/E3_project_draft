#!/usr/bin/env python3
"""Build a compact, auditable Expression Atlas diagnostic snapshot.

The utility copies manifests, sample metadata, methods, workflow Stage 07 audit
tables and bounded expression-matrix previews.  It can also retrieve a small,
explicit set of official experiment pages and FTP directory listings.  It is a
controlled snapshotter, not a recursive web crawler.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

LOGGER = logging.getLogger("expression_evidence_snapshot")
ACCESSION_PATTERN = re.compile(r"\bE-[A-Z0-9]{4,}-\d+\b")
MATRIX_SUFFIXES = (
    "-tpms.tsv",
    ".tpms.tsv",
    "-fpkms.tsv",
    ".fpkms.tsv",
    "-tpms.tsv.gz",
    ".tpms.tsv.gz",
    "-fpkms.tsv.gz",
    ".fpkms.tsv.gz",
)
METADATA_TOKENS = (
    "sdrf",
    "configuration",
    "experiment-design",
    "analysis-method",
)
REMOTE_PAGE_TEMPLATES = {
    "atlas_results": ("https://www.ebi.ac.uk/gxa/experiments/{accession}/Results"),
    "atlas_ftp_index": (
        "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/experiments/{accession}/"
    ),
    "biostudies_record": ("https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{accession}"),
}


@dataclass(frozen=True)
class SnapshotRecord:
    """One file included in the diagnostic snapshot.

    Args:
        category: Logical evidence category.
        source: Original local path or URL.
        relative_path: Path inside the snapshot root.
        size_bytes: Included file size.
        sha256: Included file checksum.
        note: Optional interpretation or retrieval note.
    """

    category: str
    source: str
    relative_path: str
    size_bytes: int
    sha256: str
    note: str = ""


def parse_boolean(value: str) -> bool:
    """Parse one explicit command-line Boolean.

    Args:
        value: Text supplied to a named command-line option.

    Returns:
        Parsed Boolean.

    Raises:
        argparse.ArgumentTypeError: If the text is not a recognised Boolean.
    """

    normalised = value.strip().lower()
    if normalised in {"true", "1", "yes", "y"}:
        return True
    if normalised in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected true or false; received {value!r}")


def sha256_file(path: Path) -> str:
    """Calculate a SHA-256 checksum without loading a file into memory.

    Args:
        path: Existing file.

    Returns:
        Lower-case hexadecimal digest.
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_tsv(
    path: Path,
    rows: Iterable[dict[str, object]],
    fields: Sequence[str],
) -> None:
    """Write records as tab-separated text.

    Args:
        path: Output path.
        rows: Record dictionaries.
        fields: Ordered columns.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def is_expression_matrix(path: Path) -> bool:
    """Return whether a path resembles an Atlas TPM/FPKM matrix.

    Args:
        path: Candidate file path.

    Returns:
        True for recognised gene-level matrix names.
    """

    lower_name = path.name.lower()
    return lower_name.endswith(MATRIX_SUFFIXES)


def open_text(path: Path):
    """Open plain or gzip-compressed text for streaming.

    Args:
        path: Text or gzip path.

    Returns:
        Context-managed text handle.
    """

    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def write_matrix_preview(
    source: Path,
    destination: Path,
    maximum_rows: int,
) -> None:
    """Write the header and a bounded number of matrix data rows.

    Args:
        source: Source TPM/FPKM matrix.
        destination: Plain TSV preview destination.
        maximum_rows: Maximum non-comment data rows after the header.

    Raises:
        ValueError: If maximum_rows is not positive.
    """

    if maximum_rows < 1:
        raise ValueError("maximum_rows must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    header_written = False
    data_rows = 0
    with (
        open_text(source) as input_handle,
        destination.open("w", encoding="utf-8", newline="") as output_handle,
    ):
        for line in input_handle:
            if line.startswith("#"):
                output_handle.write(line)
                continue
            if not header_written:
                output_handle.write(line)
                header_written = True
                continue
            if data_rows >= maximum_rows:
                break
            output_handle.write(line)
            data_rows += 1


def discover_accessions(expression_root: Path) -> tuple[str, ...]:
    """Discover experiment accessions from paths and small manifest files.

    Args:
        expression_root: Completed expression downloader output.

    Returns:
        Sorted unique accessions.
    """

    accessions: set[str] = set()
    for path in expression_root.rglob("*"):
        for match in ACCESSION_PATTERN.finditer(path.name):
            accessions.add(match.group(0))
    manifests = expression_root / "manifests"
    if manifests.is_dir():
        for path in manifests.glob("*.tsv"):
            if path.stat().st_size > 50 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            accessions.update(ACCESSION_PATTERN.findall(text))
    return tuple(sorted(accessions))


def copy_snapshot_file(
    *,
    source: Path,
    snapshot_root: Path,
    relative_path: Path,
    category: str,
    note: str = "",
) -> SnapshotRecord:
    """Copy one local file into the snapshot and describe it.

    Args:
        source: Existing source file.
        snapshot_root: Snapshot working root.
        relative_path: Destination path relative to the snapshot root.
        category: Manifest category.
        note: Optional note.

    Returns:
        Included-file record.
    """

    destination = snapshot_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return SnapshotRecord(
        category=category,
        source=str(source.resolve()),
        relative_path=relative_path.as_posix(),
        size_bytes=destination.stat().st_size,
        sha256=sha256_file(destination),
        note=note,
    )


def collect_local_evidence(
    *,
    expression_root: Path,
    workflow_run_root: Path | None,
    snapshot_root: Path,
    preview_rows: int,
) -> list[SnapshotRecord]:
    """Collect manifests, metadata, QC and bounded matrix previews.

    Args:
        expression_root: Completed downloader output.
        workflow_run_root: Optional completed end-to-end run.
        snapshot_root: Snapshot working root.
        preview_rows: Matrix rows to retain per file.

    Returns:
        Snapshot manifest records.
    """

    records: list[SnapshotRecord] = []
    manifests = expression_root / "manifests"
    if manifests.is_dir():
        for source in sorted(manifests.iterdir()):
            if source.is_file():
                records.append(
                    copy_snapshot_file(
                        source=source,
                        snapshot_root=snapshot_root,
                        relative_path=(Path("expression_manifests") / source.name),
                        category="expression_manifest",
                    )
                )
    downloads = expression_root / "downloads"
    if downloads.is_dir():
        for source in sorted(downloads.rglob("*")):
            if not source.is_file():
                continue
            lower_name = source.name.lower()
            if any(token in lower_name for token in METADATA_TOKENS):
                records.append(
                    copy_snapshot_file(
                        source=source,
                        snapshot_root=snapshot_root,
                        relative_path=Path("experiment_metadata") / source.relative_to(downloads),
                        category="sample_metadata_or_methods",
                    )
                )
            elif is_expression_matrix(source):
                preview_name = source.name.removesuffix(".gz") + ".preview.tsv"
                relative = (
                    Path("matrix_previews") / source.parent.relative_to(downloads) / preview_name
                )
                destination = snapshot_root / relative
                write_matrix_preview(source, destination, preview_rows)
                records.append(
                    SnapshotRecord(
                        category="expression_matrix_preview",
                        source=str(source.resolve()),
                        relative_path=relative.as_posix(),
                        size_bytes=destination.stat().st_size,
                        sha256=sha256_file(destination),
                        note=f"header plus at most {preview_rows} data rows",
                    )
                )
    if workflow_run_root is not None:
        candidates = (
            (workflow_run_root / "07_expression" / "tables", "stage_07_table"),
            (workflow_run_root / "07_expression" / "qc", "stage_07_qc"),
            (workflow_run_root / "00_plan", "workflow_plan"),
        )
        for root, category in candidates:
            if not root.is_dir():
                continue
            for source in sorted(root.rglob("*")):
                if not source.is_file():
                    continue
                if category == "workflow_plan" and source.suffix not in {
                    ".yaml",
                    ".yml",
                    ".json",
                    ".tsv",
                    ".txt",
                }:
                    continue
                if category == "stage_07_table" and source.suffix != ".tsv":
                    continue
                relative = Path("workflow_expression_audit") / source.relative_to(workflow_run_root)
                records.append(
                    copy_snapshot_file(
                        source=source,
                        snapshot_root=snapshot_root,
                        relative_path=relative,
                        category=category,
                    )
                )
    return records


def fetch_url(url: str, timeout_seconds: int) -> tuple[bytes, str]:
    """Retrieve one official page.

    Args:
        url: Explicit URL.
        timeout_seconds: Request timeout.

    Returns:
        Response body and content type.
    """

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "E3AtlasDuckplyr-expression-snapshot/0.5.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read(), response.headers.get_content_type()


def retrieve_remote_pages(
    *,
    accessions: Sequence[str],
    snapshot_root: Path,
    timeout_seconds: int,
    retries: int,
    delay_seconds: float,
    fetcher: Callable[[str, int], tuple[bytes, str]] = fetch_url,
) -> tuple[list[SnapshotRecord], list[dict[str, object]]]:
    """Retrieve bounded official pages for each experiment.

    Args:
        accessions: Validated Expression Atlas accessions.
        snapshot_root: Snapshot working root.
        timeout_seconds: Request timeout.
        retries: Retries after the first attempt.
        delay_seconds: Polite delay between requests.
        fetcher: Injectable retrieval function for tests.

    Returns:
        Included-file records and complete request audit rows.
    """

    records: list[SnapshotRecord] = []
    requests: list[dict[str, object]] = []
    for accession in accessions:
        if ACCESSION_PATTERN.fullmatch(accession) is None:
            raise ValueError(f"Invalid experiment accession: {accession}")
        for page_type, template in REMOTE_PAGE_TEMPLATES.items():
            url = template.format(accession=accession)
            error = ""
            body = b""
            content_type = ""
            attempts = 0
            for attempt in range(retries + 1):
                attempts = attempt + 1
                try:
                    body, content_type = fetcher(url, timeout_seconds)
                    break
                except (
                    OSError,
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                ) as exc:
                    error = str(exc)
                    if attempt < retries:
                        time.sleep(min(2.0, delay_seconds))
            relative = Path("remote_pages") / accession / f"{page_type}.html"
            if body:
                destination = snapshot_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body)
                checksum = sha256_file(destination)
                records.append(
                    SnapshotRecord(
                        category="official_remote_page",
                        source=url,
                        relative_path=relative.as_posix(),
                        size_bytes=len(body),
                        sha256=checksum,
                        note=content_type,
                    )
                )
            requests.append(
                {
                    "experiment_accession": accession,
                    "page_type": page_type,
                    "url": url,
                    "success": str(bool(body)).lower(),
                    "attempts": attempts,
                    "content_type": content_type,
                    "size_bytes": len(body),
                    "relative_path": relative.as_posix() if body else "",
                    "error": error if not body else "",
                }
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)
    return records, requests


def write_snapshot_documentation(
    *,
    snapshot_root: Path,
    expression_root: Path,
    workflow_run_root: Path | None,
) -> SnapshotRecord:
    """Write the archive interpretation boundary.

    Args:
        snapshot_root: Snapshot working root.
        expression_root: Original expression root.
        workflow_run_root: Optional workflow run.

    Returns:
        Documentation manifest record.
    """

    path = snapshot_root / "README.txt"
    workflow_text = str(workflow_run_root) if workflow_run_root else "not supplied"
    path.write_text(
        "ARIA E3 Expression Evidence Diagnostic Snapshot\n\n"
        "Purpose\n"
        "This compact archive supports identifier-mapping, tissue-metadata "
        "and app-display diagnosis. It is not a replacement for the full "
        "Expression "
        "Atlas download.\n\n"
        "Interpretation boundary\n"
        "NOT_MAPPED means no unique Atlas gene mapping was found. Zero count "
        "fields on such legacy rows do not mean measured biological zero "
        "expression.\n\n"
        f"Expression root: {expression_root}\n"
        f"Workflow run root: {workflow_text}\n"
        f"Created UTC: {dt.datetime.now(dt.timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return SnapshotRecord(
        category="documentation",
        source="generated",
        relative_path="README.txt",
        size_bytes=path.stat().st_size,
        sha256=sha256_file(path),
    )


def create_archive(snapshot_root: Path, output_archive: Path) -> None:
    """Create an atomic gzip-compressed tar archive.

    Args:
        snapshot_root: Completed snapshot directory.
        output_archive: Final ``.tar.gz`` path.
    """

    output_archive.parent.mkdir(parents=True, exist_ok=True)
    partial = output_archive.with_name(output_archive.name + ".partial")
    if partial.exists():
        partial.unlink()
    try:
        with tarfile.open(partial, mode="w:gz") as archive:
            archive.add(
                snapshot_root,
                arcname=snapshot_root.name,
                recursive=True,
            )
        os.replace(partial, output_archive)
    finally:
        if partial.exists():
            partial.unlink()


def build_snapshot(
    *,
    expression_root: Path,
    workflow_run_root: Path | None,
    output_archive: Path,
    fetch_pages: bool,
    preview_rows: int,
    timeout_seconds: int,
    retries: int,
    delay_seconds: float,
    overwrite: bool,
) -> Path:
    """Build and archive one complete diagnostic snapshot.

    Args:
        expression_root: Completed expression downloader output.
        workflow_run_root: Optional completed workflow run.
        output_archive: Destination ``.tar.gz``.
        fetch_pages: Whether to retrieve official web pages.
        preview_rows: Maximum rows per matrix preview.
        timeout_seconds: Request timeout.
        retries: Request retries.
        delay_seconds: Delay between requests.
        overwrite: Whether an existing archive may be replaced.

    Returns:
        Resolved output archive.
    """

    expression_root = expression_root.expanduser().resolve()
    output_archive = output_archive.expanduser().resolve()
    workflow_run_root = workflow_run_root.expanduser().resolve() if workflow_run_root else None
    if not expression_root.is_dir():
        raise FileNotFoundError(f"Expression root does not exist: {expression_root}")
    if workflow_run_root is not None and not workflow_run_root.is_dir():
        raise FileNotFoundError(f"Workflow run root does not exist: {workflow_run_root}")
    if not output_archive.name.endswith(".tar.gz"):
        raise ValueError("Output archive must end with .tar.gz")
    if output_archive.exists() and not overwrite:
        raise FileExistsError(f"Output archive already exists: {output_archive}")
    invalid_numbers = preview_rows < 1 or timeout_seconds < 1 or retries < 0 or delay_seconds < 0
    if invalid_numbers:
        raise ValueError("Preview, timeout, retry and delay values are outside valid ranges")

    with tempfile.TemporaryDirectory(
        prefix="e3_expression_snapshot_", dir=output_archive.parent
    ) as temporary_dir:
        snapshot_root = Path(temporary_dir) / "expression_evidence_snapshot"
        snapshot_root.mkdir()
        records = collect_local_evidence(
            expression_root=expression_root,
            workflow_run_root=workflow_run_root,
            snapshot_root=snapshot_root,
            preview_rows=preview_rows,
        )
        records.append(
            write_snapshot_documentation(
                snapshot_root=snapshot_root,
                expression_root=expression_root,
                workflow_run_root=workflow_run_root,
            )
        )
        request_rows: list[dict[str, object]] = []
        accessions = discover_accessions(expression_root)
        if fetch_pages:
            remote_records, request_rows = retrieve_remote_pages(
                accessions=accessions,
                snapshot_root=snapshot_root,
                timeout_seconds=timeout_seconds,
                retries=retries,
                delay_seconds=delay_seconds,
            )
            records.extend(remote_records)
        provenance = snapshot_root / "provenance"
        write_tsv(
            provenance / "remote_page_manifest.tsv",
            request_rows,
            (
                "experiment_accession",
                "page_type",
                "url",
                "success",
                "attempts",
                "content_type",
                "size_bytes",
                "relative_path",
                "error",
            ),
        )
        records.append(
            SnapshotRecord(
                category="provenance",
                source="generated",
                relative_path="provenance/remote_page_manifest.tsv",
                size_bytes=(provenance / "remote_page_manifest.tsv").stat().st_size,
                sha256=sha256_file(provenance / "remote_page_manifest.tsv"),
            )
        )
        write_tsv(
            provenance / "snapshot_manifest.tsv",
            (
                {
                    "category": record.category,
                    "source": record.source,
                    "relative_path": record.relative_path,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                    "note": record.note,
                }
                for record in records
            ),
            (
                "category",
                "source",
                "relative_path",
                "size_bytes",
                "sha256",
                "note",
            ),
        )
        create_archive(snapshot_root, output_archive)
    LOGGER.info("Created expression evidence snapshot: %s", output_archive)
    return output_archive


def build_parser() -> argparse.ArgumentParser:
    """Build the named-argument command-line interface.

    Returns:
        Configured parser.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expression-root", type=Path, required=True)
    parser.add_argument("--workflow-run-root", type=Path)
    parser.add_argument("--output-archive", type=Path, required=True)
    parser.add_argument("--fetch-pages", type=parse_boolean, default=True)
    parser.add_argument("--preview-rows", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--overwrite", type=parse_boolean, default=False)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command-line snapshot builder.

    Args:
        arguments: Optional named arguments for tests.

    Returns:
        Process exit code.
    """

    args = build_parser().parse_args(arguments)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    build_snapshot(
        expression_root=args.expression_root,
        workflow_run_root=args.workflow_run_root,
        output_archive=args.output_archive,
        fetch_pages=args.fetch_pages,
        preview_rows=args.preview_rows,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        delay_seconds=args.delay_seconds,
        overwrite=args.overwrite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
