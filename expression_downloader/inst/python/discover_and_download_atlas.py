#!/usr/bin/env python3
"""Discover and download Expression Atlas RNA-seq expression matrices.

This script is intentionally Python-first and R-light. It performs the parts
that were fragile in R: web queries, remote checks, retries, and incremental
file downloads. The downstream R package then consumes the generated
``atlas_downloaded_files.tsv`` manifest and converts TPM/FPKM matrices to
Parquet for duckplyr/Shiny querying.

The script avoids strict XML parsing. The historical ArrayExpress endpoint can
return XML, HTML error messages, or text depending on server/proxy behaviour.
For discovery we only need candidate experiment accessions, so the script
extracts accessions with a regular expression and then validates them by
checking the Expression Atlas FTP files.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional


ACCESSION_RE = re.compile(r"\bE-[A-Z0-9]{4,}-\d+\b")
DEFAULT_SEARCH_TERMS = (
    "RNA-seq",
    "RNA sequencing",
    "transcriptome",
    "baseline",
)
DEFAULT_EXPRESSION_TYPES = ("tpms", "fpkms")
DEFAULT_DOWNLOAD_TYPES = (
    "tpms",
    "fpkms",
    "sample_metadata",
    "analysis_methods",
    "r_object",
)
DEFAULT_OPTIONAL_EXTRA_TYPES = (
    "transcript_tpms",
    "tpms_markers",
    "fpkms_markers",
    "tpms_coexpressions",
    "fpkms_coexpressions",
    "tpms_bedgraph",
    "fpkms_bedgraph",
    "heatmap_pdf",
)
DEFAULT_FTP_INDEX_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/experiments/"
)


@dataclass(frozen=True)
class SpeciesRecord:
    """Species search configuration."""

    species_column: str
    scientific_name: str
    atlas_species_query: str
    include: bool = True
    priority: str = "unspecified"


@dataclass(frozen=True)
class CandidateExperiment:
    """Candidate Expression Atlas experiment."""

    species_column: str
    atlas_species_query: str
    search_term: str
    accession: str
    search_url: str
    source: str
    remote_file_names: str = ""


@dataclass(frozen=True)
class RemoteFile:
    """Expected Expression Atlas FTP file."""

    species_column: str
    atlas_species_query: str
    experiment_accession: str
    file_type: str
    file_name: str
    url: str
    local_path: Path


def parse_bool(value: object, default: bool = False) -> bool:
    """Parse a command-line boolean value.

    Parameters
    ----------
    value:
        Value to parse. Strings such as ``true``, ``1`` and ``yes`` are treated
        as true. Strings such as ``false``, ``0`` and ``no`` are treated as
        false.
    default:
        Value returned when ``value`` is ``None`` or an empty string.

    Returns
    -------
    bool
        Parsed boolean value.
    """

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    normalised = str(value).strip().lower()

    if normalised == "":
        return default

    if normalised in {"true", "t", "1", "yes", "y"}:
        return True

    if normalised in {"false", "f", "0", "no", "n"}:
        return False

    raise ValueError(f"Cannot parse boolean value: {value!r}")


def now_iso() -> str:
    """Return the current timestamp in ISO-8601 format."""

    return _dt.datetime.now().replace(microsecond=0).isoformat()


def log(message: str, log_file: Optional[Path] = None) -> None:
    """Write a progress message to stderr and optionally to a log file.

    Parameters
    ----------
    message:
        Message to print.
    log_file:
        Optional path to a persistent log file.
    """

    line = f"[{now_iso()}] {message}"
    print(line, file=sys.stderr, flush=True)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open(mode="a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def safe_bool_text(value: bool) -> str:
    """Format a boolean value as a lower-case text value for TSV files."""

    return "true" if value else "false"


def read_species_file(species_file: Path) -> list[SpeciesRecord]:
    """Read a simple newline-delimited species file.

    Parameters
    ----------
    species_file:
        Text file containing one species per line. Underscore-separated species
        such as ``Arabidopsis_thaliana`` are accepted.

    Returns
    -------
    list[SpeciesRecord]
        Parsed species records.
    """

    records: list[SpeciesRecord] = []

    with species_file.open(mode="r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            species_column = line.replace(" ", "_")
            scientific_name = species_column.replace("_", " ")
            records.append(
                SpeciesRecord(
                    species_column=species_column,
                    scientific_name=scientific_name,
                    atlas_species_query=scientific_name,
                    include=True,
                    priority="species_file",
                )
            )

    return records


def apply_species_overrides(
    records: list[SpeciesRecord],
    override_tsv: Optional[Path],
) -> list[SpeciesRecord]:
    """Apply manual species-name and include/exclude overrides.

    Parameters
    ----------
    records:
        Species records parsed from ``species.txt``.
    override_tsv:
        Optional TSV with columns such as ``species_column``,
        ``atlas_species_query`` and ``include``.

    Returns
    -------
    list[SpeciesRecord]
        Species records after overrides have been applied.
    """

    if override_tsv is None or not override_tsv.exists():
        return records

    overrides: dict[str, dict[str, str]] = {}

    with override_tsv.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            species_column = (row.get("species_column") or "").strip()
            if species_column:
                overrides[species_column] = row

    updated: list[SpeciesRecord] = []

    for record in records:
        row = overrides.get(record.species_column)

        if row is None:
            updated.append(record)
            continue

        scientific_name = row.get("scientific_name") or record.scientific_name
        atlas_query = row.get("atlas_species_query") or scientific_name
        include_text = row.get("include")
        include = parse_bool(include_text, default=record.include)
        priority = row.get("priority") or record.priority

        updated.append(
            SpeciesRecord(
                species_column=record.species_column,
                scientific_name=scientific_name,
                atlas_species_query=atlas_query,
                include=include,
                priority=priority,
            )
        )

    return updated


def write_tsv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    """Write dictionaries to a tab-separated file.

    Parameters
    ----------
    path:
        Output TSV path.
    rows:
        Iterable of row dictionaries.
    fieldnames:
        Ordered output column names.
    """

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def append_tsv(path: Path, row: dict[str, object], fieldnames: list[str]) -> None:
    """Append one row to a tab-separated file, creating the header if needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0

    with path.open(mode="a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def read_existing_download_manifest(manifest_path: Path) -> set[tuple[str, str]]:
    """Read existing successful downloads from a manifest.

    Parameters
    ----------
    manifest_path:
        Existing ``atlas_downloaded_files.tsv`` path.

    Returns
    -------
    set[tuple[str, str]]
        Set of ``(url, local_path)`` records that were previously successful.
    """

    if not manifest_path.exists() or manifest_path.stat().st_size == 0:
        return set()

    rows: set[tuple[str, str]] = set()

    with manifest_path.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if parse_bool(row.get("success"), default=False):
                rows.add((row.get("url", ""), row.get("local_path", "")))

    return rows


def request_text(url: str, timeout_seconds: int) -> str:
    """Download a URL as text.

    Parameters
    ----------
    url:
        URL to retrieve.
    timeout_seconds:
        Timeout in seconds.

    Returns
    -------
    str
        Decoded response text.
    """

    request = urllib.request.Request(
        url=url,
        headers={"User-Agent": "E3AtlasDuckplyr/0.2.1"},
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()

    return data.decode("utf-8", errors="replace")


def build_arrayexpress_search_urls(
    species_query: str,
    search_term: str,
) -> list[str]:
    """Build robust ArrayExpress/Atlas search URLs.

    Parameters
    ----------
    species_query:
        Species query, for example ``Arabidopsis thaliana``.
    search_term:
        Search term such as ``RNA-seq``.

    Returns
    -------
    list[str]
        Candidate API URLs to try.
    """

    params = {
        "keywords": search_term,
        "gxa": "true",
        "species": species_query,
    }
    encoded = urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)

    return [
        f"https://www.ebi.ac.uk/arrayexpress/xml/v2/experiments?{encoded}",
        f"https://www.ebi.ac.uk/arrayexpress/xml/v3/experiments?{encoded}",
    ]


def extract_accessions_from_text(text: str) -> list[str]:
    """Extract unique ArrayExpress-style experiment accessions from text.

    Parameters
    ----------
    text:
        XML, JSON, HTML or plain text response.

    Returns
    -------
    list[str]
        Unique accessions in first-seen order.
    """

    seen: set[str] = set()
    accessions: list[str] = []

    for match in ACCESSION_RE.finditer(text):
        accession = match.group(0)
        if accession not in seen:
            seen.add(accession)
            accessions.append(accession)

    return accessions


def extract_href_values(html_text: str) -> list[str]:
    """Extract href values from an HTML directory listing.

    Parameters
    ----------
    html_text:
        HTML text from a web or FTP directory listing.

    Returns
    -------
    list[str]
        Unique href values in first-seen order.
    """

    pattern = re.compile(r'href=["\']([^"\']+)["\']', flags=re.IGNORECASE)
    seen: set[str] = set()
    hrefs: list[str] = []

    for match in pattern.finditer(html_text):
        href = urllib.parse.unquote(match.group(1)).strip()
        if not href or href in {"../", "./"}:
            continue
        if href not in seen:
            seen.add(href)
            hrefs.append(href)

    return hrefs


def detect_atlas_file_type(file_name: str) -> Optional[str]:
    """Infer the Expression Atlas file type from a filename.

    Expression Atlas filenames are not fully standard across releases. This
    helper deliberately separates true gene-level expression matrices from
    optional extras such as marker files, coexpression files, bedGraph tracks
    and heatmap PDFs. This prevents optional files being mislabelled as TPM or
    FPKM matrices and then passed into the R/duckplyr Parquet import step.

    Parameters
    ----------
    file_name:
        Filename from an Expression Atlas FTP experiment directory.

    Returns
    -------
    Optional[str]
        One of the package file-type labels, or ``None`` when the file is not
        relevant to this workflow.
    """

    lower_name = file_name.lower()

    if "sdrf" in lower_name or "experiment-design" in lower_name:
        return "sample_metadata"

    if "analysis-method" in lower_name:
        return "analysis_methods"

    if "atlasexperimentsummary" in lower_name and lower_name.endswith(".rdata"):
        return "r_object"

    if "heatmap" in lower_name and lower_name.endswith(".pdf"):
        return "heatmap_pdf"

    if "coexpression" in lower_name:
        if "fpkm" in lower_name:
            return "fpkms_coexpressions"
        if "tpm" in lower_name:
            return "tpms_coexpressions"
        return None

    if "marker" in lower_name:
        if "fpkm" in lower_name:
            return "fpkms_markers"
        if "tpm" in lower_name:
            return "tpms_markers"
        return None

    if lower_name.endswith(".bedgraph"):
        if "fpkm" in lower_name:
            return "fpkms_bedgraph"
        if "tpm" in lower_name:
            return "tpms_bedgraph"
        return None

    if "transcript" in lower_name and "tpm" in lower_name and lower_name.endswith((".tsv", ".tsv.gz")):
        return "transcript_tpms"

    # True gene-level matrix files. These are the only file types imported
    # into long Parquet by the R layer.
    if lower_name.endswith((".tpms.tsv", "-tpms.tsv", ".tpms.tsv.gz", "-tpms.tsv.gz")):
        return "tpms"

    if lower_name.endswith((".fpkms.tsv", "-fpkms.tsv", ".fpkms.tsv.gz", "-fpkms.tsv.gz")):
        return "fpkms"

    return None


def list_experiment_ftp_files(
    accession: str,
    ftp_index_url: str,
    timeout_seconds: int,
    retries: int,
) -> dict[str, list[str]]:
    """List relevant files for one Expression Atlas FTP experiment.

    Parameters
    ----------
    accession:
        Expression Atlas experiment accession.
    ftp_index_url:
        Base Expression Atlas FTP experiments URL.
    timeout_seconds:
        Request timeout in seconds.
    retries:
        Number of retries.

    Returns
    -------
    dict[str, list[str]]
        Mapping from file type to one or more actual filenames observed in the
        experiment directory.
    """

    experiment_url = ftp_index_url.rstrip("/") + f"/{accession}/"
    index_text = fetch_optional_text(
        url=experiment_url,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )

    if not index_text:
        return {}

    files_by_type: dict[str, list[str]] = {}

    for href in extract_href_values(index_text):
        if href.endswith("/"):
            continue

        file_name = Path(urllib.parse.urlparse(href).path).name
        if not file_name:
            continue

        file_type = detect_atlas_file_type(file_name=file_name)
        if file_type is None:
            continue

        files_by_type.setdefault(file_type, [])
        if file_name not in files_by_type[file_type]:
            files_by_type[file_type].append(file_name)

    return files_by_type


def encode_remote_file_names(files_by_type: dict[str, list[str]]) -> str:
    """Encode actual FTP filenames for storage in a manifest/dataclass.

    Parameters
    ----------
    files_by_type:
        Mapping from file type to actual filenames.

    Returns
    -------
    str
        Compact JSON representation.
    """

    if not files_by_type:
        return ""

    return json.dumps(files_by_type, sort_keys=True)


def decode_remote_file_names(remote_file_names: str) -> dict[str, list[str]]:
    """Decode the actual FTP filename mapping stored on a candidate.

    Parameters
    ----------
    remote_file_names:
        JSON string produced by :func:`encode_remote_file_names`.

    Returns
    -------
    dict[str, list[str]]
        Mapping from file type to actual filenames.
    """

    if not remote_file_names:
        return {}

    try:
        raw = json.loads(remote_file_names)
    except json.JSONDecodeError:
        return {}

    decoded: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return decoded

    for key, value in raw.items():
        if isinstance(value, list):
            decoded[str(key)] = [str(item) for item in value]
        elif value:
            decoded[str(key)] = [str(value)]

    return decoded


def search_species_accessions(
    species_record: SpeciesRecord,
    search_terms: tuple[str, ...],
    timeout_seconds: int,
    retries: int,
    log_file: Optional[Path],
) -> list[CandidateExperiment]:
    """Search Expression Atlas/ArrayExpress for candidate experiments.

    Parameters
    ----------
    species_record:
        Species search configuration.
    search_terms:
        Search terms to issue for the species.
    timeout_seconds:
        Request timeout in seconds.
    retries:
        Number of retries per URL.
    log_file:
        Optional pipeline log path.

    Returns
    -------
    list[CandidateExperiment]
        Candidate experiments. These are not trusted until FTP TPM/FPKM files
        are found for the accession.
    """

    results: list[CandidateExperiment] = []
    seen: set[tuple[str, str]] = set()

    for search_term in search_terms:
        urls = build_arrayexpress_search_urls(
            species_query=species_record.atlas_species_query,
            search_term=search_term,
        )

        term_accessions: list[str] = []

        for url in urls:
            text = ""
            last_error = ""

            for attempt in range(1, retries + 2):
                try:
                    text = request_text(url=url, timeout_seconds=timeout_seconds)
                    break
                except Exception as error:  # noqa: BLE001 - command-line tool should keep going
                    last_error = str(error)
                    if attempt <= retries:
                        time.sleep(min(5, attempt))

            if text:
                accessions = extract_accessions_from_text(text=text)
                term_accessions.extend(accessions)
                log(
                    "Search term "
                    f"{search_term!r} for {species_record.species_column}: "
                    f"{len(accessions)} accessions from {url}",
                    log_file=log_file,
                )
            else:
                log(
                    "Search failed for "
                    f"{species_record.species_column} term {search_term!r}: "
                    f"{last_error}",
                    log_file=log_file,
                )

        for accession in term_accessions:
            key = (species_record.species_column, accession)
            if key in seen:
                continue

            seen.add(key)
            results.append(
                CandidateExperiment(
                    species_column=species_record.species_column,
                    atlas_species_query=species_record.atlas_species_query,
                    search_term=search_term,
                    accession=accession,
                    search_url=urls[0],
                    source="arrayexpress_xml_regex",
                )
            )

    return results




def normalise_species_name(value: str) -> str:
    """Normalise a species name for robust matching.

    Parameters
    ----------
    value:
        Species name or species-column style value.

    Returns
    -------
    str
        Lower-case species name with underscores converted to spaces and
        repeated whitespace collapsed.
    """

    normalised = value.replace("_", " ").strip().lower()
    normalised = re.sub(r"\s+", " ", normalised)
    return normalised


def species_matches_record(observed_species: str, species_record: SpeciesRecord) -> bool:
    """Return true when an observed metadata species matches a target record.

    Expression Atlas sometimes uses more specific names such as
    ``Zea mays subsp. mays`` while the project species list may contain
    ``Zea mays``. The match therefore allows exact matches and conservative
    prefix matches in either direction.

    Parameters
    ----------
    observed_species:
        Species value observed in Expression Atlas metadata.
    species_record:
        Target species record from ``species.txt``.

    Returns
    -------
    bool
        Whether the observed species should be assigned to this target species.
    """

    observed = normalise_species_name(observed_species)
    targets = {
        normalise_species_name(species_record.scientific_name),
        normalise_species_name(species_record.atlas_species_query),
        normalise_species_name(species_record.species_column),
    }

    for target in targets:
        if not target:
            continue
        if observed == target:
            return True
        if observed.startswith(target + " "):
            return True
        if target.startswith(observed + " "):
            return True

    return False


def list_ftp_accessions(
    ftp_index_url: str,
    timeout_seconds: int,
    retries: int,
    log_file: Optional[Path] = None,
) -> list[str]:
    """List Expression Atlas experiment accessions from the FTP index.

    This avoids the brittle ArrayExpress/XML search route. The FTP experiment
    index is a simple HTML directory listing, so a regular expression over the
    returned text is sufficient and robust.

    Parameters
    ----------
    ftp_index_url:
        URL of the Expression Atlas experiment FTP index.
    timeout_seconds:
        Request timeout in seconds.
    retries:
        Number of retries.
    log_file:
        Optional log file.

    Returns
    -------
    list[str]
        Unique experiment accessions in the order they appear.
    """

    text = ""
    last_error = ""

    for attempt in range(1, retries + 2):
        try:
            text = request_text(url=ftp_index_url, timeout_seconds=timeout_seconds)
            break
        except Exception as error:  # noqa: BLE001 - command-line workflow should continue cleanly
            last_error = str(error)
            if attempt <= retries:
                time.sleep(min(5, attempt))

    if not text:
        raise RuntimeError(f"Could not read FTP index {ftp_index_url}: {last_error}")

    accessions = extract_accessions_from_text(text=text)
    log(f"FTP index contained {len(accessions)} candidate accessions", log_file=log_file)
    return accessions


def fetch_optional_text(url: str, timeout_seconds: int, retries: int) -> str:
    """Fetch text from a URL, returning an empty string on failure.

    Parameters
    ----------
    url:
        URL to retrieve.
    timeout_seconds:
        Request timeout in seconds.
    retries:
        Number of retries.

    Returns
    -------
    str
        Response text, or an empty string when the URL could not be read.
    """

    last_error = ""
    for attempt in range(1, retries + 2):
        try:
            return request_text(url=url, timeout_seconds=timeout_seconds)
        except Exception as error:  # noqa: BLE001 - optional metadata read
            last_error = str(error)
            if attempt <= retries:
                time.sleep(min(5, attempt))
    _ = last_error
    return ""


def extract_species_from_sdrf_text(metadata_text: str) -> list[str]:
    """Extract organism/species values from an SDRF-style TSV.

    Parameters
    ----------
    metadata_text:
        Text content of an Expression Atlas condensed SDRF metadata file.

    Returns
    -------
    list[str]
        Unique species values.
    """

    if not metadata_text.strip():
        return []

    lines = metadata_text.splitlines()
    if not lines:
        return []

    reader = csv.reader(lines, delimiter="\t")
    try:
        header = next(reader)
    except StopIteration:
        return []

    organism_indices = [
        index for index, column in enumerate(header)
        if "organism" in column.lower() or "species" in column.lower()
    ]

    if not organism_indices:
        return []

    seen: set[str] = set()
    values: list[str] = []

    for row_number, row in enumerate(reader, start=1):
        for index in organism_indices:
            if index >= len(row):
                continue
            value = row[index].strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        if row_number >= 5000:
            break

    return values


def extract_species_from_experiment_page(page_text: str) -> list[str]:
    """Extract organism values from a rendered Expression Atlas page.

    Parameters
    ----------
    page_text:
        HTML or text from an Expression Atlas experiment page.

    Returns
    -------
    list[str]
        Unique organism strings detected on the page.
    """

    if not page_text:
        return []

    pattern = re.compile(r"Organism:\s*([^\n<]+)", flags=re.IGNORECASE)
    values: list[str] = []
    seen: set[str] = set()

    for match in pattern.finditer(page_text):
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)

    return values


def match_species_records(
    observed_species_values: list[str],
    species_records: list[SpeciesRecord],
) -> list[SpeciesRecord]:
    """Match observed Expression Atlas species values to target records.

    Parameters
    ----------
    observed_species_values:
        Species values extracted from metadata or an experiment page.
    species_records:
        Target species records.

    Returns
    -------
    list[SpeciesRecord]
        Matching species records.
    """

    matches: list[SpeciesRecord] = []
    seen: set[str] = set()

    for observed in observed_species_values:
        for record in species_records:
            if record.species_column in seen:
                continue
            if species_matches_record(observed_species=observed, species_record=record):
                matches.append(record)
                seen.add(record.species_column)

    return matches


def discover_candidates_by_ftp_scan(
    species_records: list[SpeciesRecord],
    output_dir: Path,
    ftp_index_url: str,
    expression_file_types: tuple[str, ...],
    timeout_seconds: int,
    retries: int,
    max_experiments_per_species: int,
    ftp_scan_max_accessions: int,
    log_file: Optional[Path],
) -> list[CandidateExperiment]:
    """Discover Expression Atlas candidates by scanning the FTP index.

    The workflow is:
    1. list experiment directories from the FTP index;
    2. check whether each experiment has a TPM/FPKM file;
    3. inspect metadata/page text to determine organism;
    4. retain only experiments matching the requested species list.

    Parameters
    ----------
    species_records:
        Target species records.
    output_dir:
        Root output directory.
    ftp_index_url:
        Expression Atlas FTP experiment index URL.
    expression_file_types:
        Expression matrices to require, usually ``tpms`` and ``fpkms``.
    timeout_seconds:
        Request timeout in seconds.
    retries:
        Number of retries.
    max_experiments_per_species:
        Optional cap per species. Zero means no cap.
    ftp_scan_max_accessions:
        Optional cap on FTP accessions scanned. Zero means no cap.
    log_file:
        Optional log file.

    Returns
    -------
    list[CandidateExperiment]
        Candidate experiments that have TPM/FPKM files and match requested
        species metadata.
    """

    accessions = list_ftp_accessions(
        ftp_index_url=ftp_index_url,
        timeout_seconds=timeout_seconds,
        retries=retries,
        log_file=log_file,
    )

    if ftp_scan_max_accessions and len(accessions) > ftp_scan_max_accessions:
        log(
            f"Limiting FTP scan from {len(accessions)} to {ftp_scan_max_accessions} accessions",
            log_file=log_file,
        )
        accessions = accessions[:ftp_scan_max_accessions]

    species_counts: dict[str, int] = {record.species_column: 0 for record in species_records}
    candidates: list[CandidateExperiment] = []

    for index, accession in enumerate(accessions, start=1):
        if index == 1 or index % 100 == 0:
            log(f"FTP scan progress: {index}/{len(accessions)} accessions", log_file=log_file)

        files_by_type = list_experiment_ftp_files(
            accession=accession,
            ftp_index_url=ftp_index_url,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )

        available_expression_types = [
            file_type for file_type in expression_file_types
            if files_by_type.get(file_type)
        ]

        if not available_expression_types:
            continue

        base_url = ftp_index_url.rstrip("/") + f"/{accession}/"
        page_url = f"https://www.ebi.ac.uk/gxa/experiments/{accession}"

        observed_species: list[str] = []
        for metadata_file_name in files_by_type.get("sample_metadata", []):
            metadata_url = base_url + urllib.parse.quote(metadata_file_name)
            metadata_text = fetch_optional_text(
                url=metadata_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
            )
            observed_species.extend(
                extract_species_from_sdrf_text(metadata_text=metadata_text)
            )

        # De-duplicate while preserving order.
        observed_species = list(dict.fromkeys(observed_species))

        if not observed_species:
            page_text = fetch_optional_text(
                url=page_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
            )
            observed_species = extract_species_from_experiment_page(page_text=page_text)

        matched_records = match_species_records(
            observed_species_values=observed_species,
            species_records=species_records,
        )

        if not matched_records:
            continue

        for matched_record in matched_records:
            current_count = species_counts.get(matched_record.species_column, 0)
            if max_experiments_per_species and current_count >= max_experiments_per_species:
                continue

            candidates.append(
                CandidateExperiment(
                    species_column=matched_record.species_column,
                    atlas_species_query=matched_record.atlas_species_query,
                    search_term="ftp_scan",
                    accession=accession,
                    search_url=ftp_index_url,
                    source="ftp_scan_metadata",
                    remote_file_names=encode_remote_file_names(files_by_type),
                )
            )
            species_counts[matched_record.species_column] = current_count + 1

    kept_summary = ", ".join(
        f"{species}={count}" for species, count in sorted(species_counts.items()) if count
    )
    log(
        "FTP scan retained "
        f"{len(candidates)} experiments matching requested species"
        + (f": {kept_summary}" if kept_summary else ""),
        log_file=log_file,
    )

    return candidates


def build_remote_files(
    candidate: CandidateExperiment,
    output_dir: Path,
    download_file_types: tuple[str, ...],
) -> list[RemoteFile]:
    """Build expected Expression Atlas FTP files for one experiment.

    Parameters
    ----------
    candidate:
        Candidate experiment.
    output_dir:
        Root output directory.
    download_file_types:
        File types to include.

    Returns
    -------
    list[RemoteFile]
        Expected files.
    """

    accession = candidate.accession
    base_url = (
        "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/"
        f"experiments/{accession}/"
    )

    fallback_names = {
        "tpms": [f"{accession}-tpms.tsv"],
        "fpkms": [f"{accession}-fpkms.tsv"],
        "transcript_tpms": [f"{accession}-transcript_tpms.tsv"],
        "sample_metadata": [f"{accession}.condensed-sdrf.tsv"],
        "analysis_methods": [f"{accession}-analysis-methods.tsv"],
        "r_object": [f"{accession}-atlasExperimentSummary.Rdata"],
        "transcript_tpms": [f"{accession}-transcript_tpms.tsv"],
    }

    actual_names = decode_remote_file_names(
        remote_file_names=candidate.remote_file_names
    )

    files: list[RemoteFile] = []

    for file_type in download_file_types:
        file_names = actual_names.get(file_type)

        if not file_names:
            file_names = fallback_names.get(file_type, [])

        for file_name in file_names:
            local_path = (
                output_dir
                / "downloads"
                / candidate.species_column
                / candidate.accession
                / file_name
            )

            files.append(
                RemoteFile(
                    species_column=candidate.species_column,
                    atlas_species_query=candidate.atlas_species_query,
                    experiment_accession=candidate.accession,
                    file_type=file_type,
                    file_name=file_name,
                    url=base_url + urllib.parse.quote(file_name),
                    local_path=local_path,
                )
            )

    return files


def local_file_is_usable(path: Path, minimum_bytes: int = 1) -> bool:
    """Return true when a local file exists and is non-empty."""

    try:
        return path.exists() and path.is_file() and path.stat().st_size >= minimum_bytes
    except OSError:
        return False


def check_remote_file(url: str, timeout_seconds: int) -> tuple[bool, bool, int | None, int | None, str]:
    """Check whether a remote file exists and appears non-empty.

    Parameters
    ----------
    url:
        Remote file URL.
    timeout_seconds:
        Request timeout in seconds.

    Returns
    -------
    tuple[bool, bool, int | None, int | None, str]
        ``remote_exists``, ``remote_non_empty``, ``status_code``,
        ``remote_bytes`` and ``check_method``.
    """

    request = urllib.request.Request(
        url=url,
        headers={"User-Agent": "E3AtlasDuckplyr/0.2.1"},
        method="HEAD",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            length_header = response.headers.get("Content-Length")
            remote_bytes = int(length_header) if length_header else None

            if status_code < 400 and remote_bytes is not None and remote_bytes > 0:
                return True, True, status_code, remote_bytes, "HEAD"

            if status_code >= 400:
                return False, False, status_code, remote_bytes, "HEAD"
    except urllib.error.HTTPError as error:
        return False, False, error.code, None, "HEAD"
    except Exception:
        pass

    request = urllib.request.Request(
        url=url,
        headers={
            "User-Agent": "E3AtlasDuckplyr/0.2.1",
            "Range": "bytes=0-0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = response.read(1)
            status_code = response.status
            return status_code < 400, status_code < 400 and bool(data), status_code, None, "GET_RANGE"
    except urllib.error.HTTPError as error:
        return False, False, error.code, None, "GET_RANGE"
    except Exception:
        return False, False, None, None, "GET_RANGE_FAILED"


def download_file(
    remote_file: RemoteFile,
    force_download: bool,
    timeout_seconds: int,
    retries: int,
    minimum_bytes: int,
) -> tuple[bool, str, int | None]:
    """Download one remote file with retries and atomic rename.

    Parameters
    ----------
    remote_file:
        File to download.
    force_download:
        Whether to overwrite existing usable local files.
    timeout_seconds:
        Request timeout in seconds.
    retries:
        Number of retries.
    minimum_bytes:
        Minimum local file size.

    Returns
    -------
    tuple[bool, str, int | None]
        Success flag, action string and local bytes.
    """

    if not force_download and local_file_is_usable(remote_file.local_path, minimum_bytes):
        return True, "skipped_existing_local_file", remote_file.local_path.stat().st_size

    remote_file.local_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=remote_file.local_path.name + ".",
        suffix=".partial",
        dir=str(remote_file.local_path.parent),
    )
    os.close(temporary_fd)
    temporary_path = Path(temporary_name)

    last_error = ""

    for attempt in range(1, retries + 2):
        try:
            request = urllib.request.Request(
                url=remote_file.url,
                headers={"User-Agent": "E3AtlasDuckplyr/0.2.1"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                with temporary_path.open(mode="wb") as handle:
                    shutil.copyfileobj(response, handle)

            if local_file_is_usable(temporary_path, minimum_bytes):
                temporary_path.replace(remote_file.local_path)
                return True, "downloaded", remote_file.local_path.stat().st_size

            last_error = "downloaded_file_empty"
        except Exception as error:  # noqa: BLE001 - command-line downloader should keep going
            last_error = str(error)

        if attempt <= retries:
            time.sleep(min(5, attempt))

    if temporary_path.exists():
        temporary_path.unlink()

    return False, f"download_failed: {last_error}", None


def parse_csv_option(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse a comma-separated command-line option."""

    if value is None or value.strip() == "":
        return default

    return tuple(item.strip() for item in value.split(",") if item.strip())


def main(argv: Optional[list[str]] = None) -> int:
    """Run Python-first Expression Atlas discovery and download."""

    parser = argparse.ArgumentParser(
        description="Discover and download Expression Atlas TPM/FPKM files.",
    )
    parser.add_argument("--species_file", required=True, help="Path to data/species.txt")
    parser.add_argument("--override_tsv", default=None, help="Optional species overrides TSV")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--search_terms", default=",".join(DEFAULT_SEARCH_TERMS))
    parser.add_argument("--expression_file_types", default=",".join(DEFAULT_EXPRESSION_TYPES))
    parser.add_argument("--download_file_types", default=",".join(DEFAULT_DOWNLOAD_TYPES))
    parser.add_argument(
        "--include_optional_extras",
        default="false",
        help=(
            "When true, also download optional Atlas extras such as marker, "
            "coexpression, bedGraph and heatmap files. These files are kept "
            "but are not imported as expression matrices."
        ),
    )
    parser.add_argument("--force_download", default="false")
    parser.add_argument("--timeout_seconds", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--minimum_bytes", type=int, default=1)
    parser.add_argument("--max_experiments_per_species", type=int, default=0)
    parser.add_argument("--manual_experiment_tsv", default=None)
    parser.add_argument(
        "--discovery_backend",
        default="ftp_scan",
        choices=("ftp_scan", "arrayexpress_api"),
        help="Discovery backend. ftp_scan is the robust default.",
    )
    parser.add_argument("--ftp_index_url", default=DEFAULT_FTP_INDEX_URL)
    parser.add_argument(
        "--ftp_scan_max_accessions",
        type=int,
        default=0,
        help="Optional cap on FTP accessions scanned for smoke tests. Zero means no cap.",
    )
    args = parser.parse_args(argv)

    species_file = Path(args.species_file)
    override_tsv = Path(args.override_tsv) if args.override_tsv else None
    output_dir = Path(args.output_dir)
    manifest_dir = output_dir / "manifests"
    log_file = manifest_dir / "python_atlas_pipeline.log"

    search_terms = parse_csv_option(args.search_terms, DEFAULT_SEARCH_TERMS)
    expression_file_types = parse_csv_option(args.expression_file_types, DEFAULT_EXPRESSION_TYPES)
    download_file_types = parse_csv_option(args.download_file_types, DEFAULT_DOWNLOAD_TYPES)
    include_optional_extras = parse_bool(args.include_optional_extras, default=False)
    if include_optional_extras:
        download_file_types = tuple(
            dict.fromkeys(download_file_types + DEFAULT_OPTIONAL_EXTRA_TYPES)
        )
    force_download = parse_bool(args.force_download, default=False)

    manifest_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "downloads").mkdir(parents=True, exist_ok=True)
    (output_dir / "parquet").mkdir(parents=True, exist_ok=True)

    species_records = apply_species_overrides(
        records=read_species_file(species_file=species_file),
        override_tsv=override_tsv,
    )
    species_records = [record for record in species_records if record.include]

    species_registry_tsv = manifest_dir / "species_registry.tsv"
    write_tsv(
        path=species_registry_tsv,
        rows=[
            {
                "species_column": record.species_column,
                "scientific_name": record.scientific_name,
                "atlas_species_query": record.atlas_species_query,
                "include": safe_bool_text(record.include),
                "priority": record.priority,
            }
            for record in species_records
        ],
        fieldnames=[
            "species_column",
            "scientific_name",
            "atlas_species_query",
            "include",
            "priority",
        ],
    )

    candidate_path = manifest_dir / "atlas_candidate_experiments.tsv"
    availability_path = manifest_dir / "atlas_expression_matrix_availability.tsv"
    checked_path = manifest_dir / "atlas_checked_file_manifest.tsv"
    selected_path = manifest_dir / "atlas_selected_checked_file_manifest.tsv"
    downloaded_path = manifest_dir / "atlas_downloaded_files.tsv"
    summary_path = manifest_dir / "atlas_python_summary.tsv"

    # Remove old manifests for this run to avoid mixing stale rows.
    for path in [candidate_path, availability_path, checked_path, selected_path, downloaded_path, summary_path]:
        if path.exists():
            path.unlink()

    log("Starting Python-first Expression Atlas discovery", log_file=log_file)
    log(f"Species records to search: {len(species_records)}", log_file=log_file)

    candidates: list[CandidateExperiment] = []

    if args.discovery_backend == "ftp_scan":
        log("Using robust FTP-scan discovery backend", log_file=log_file)
        candidates = discover_candidates_by_ftp_scan(
            species_records=species_records,
            output_dir=output_dir,
            ftp_index_url=args.ftp_index_url,
            expression_file_types=expression_file_types,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            max_experiments_per_species=args.max_experiments_per_species,
            ftp_scan_max_accessions=args.ftp_scan_max_accessions,
            log_file=log_file,
        )
    else:
        log("Using legacy ArrayExpress API discovery backend", log_file=log_file)
        for species_record in species_records:
            log(
                f"Searching {species_record.species_column} using query "
                f"{species_record.atlas_species_query!r}",
                log_file=log_file,
            )
            species_candidates = search_species_accessions(
                species_record=species_record,
                search_terms=search_terms,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                log_file=log_file,
            )

            if args.max_experiments_per_species and len(species_candidates) > args.max_experiments_per_species:
                log(
                    f"Limiting {species_record.species_column} from "
                    f"{len(species_candidates)} to {args.max_experiments_per_species} experiments",
                    log_file=log_file,
                )
                species_candidates = species_candidates[: args.max_experiments_per_species]

            candidates.extend(species_candidates)
            log(
                f"Candidate experiments for {species_record.species_column}: "
                f"{len(species_candidates)}",
                log_file=log_file,
            )

    if args.manual_experiment_tsv:
        manual_path = Path(args.manual_experiment_tsv)
        if manual_path.exists():
            with manual_path.open(mode="r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                for row in reader:
                    accession = (row.get("experiment_accession") or row.get("accession") or "").strip()
                    species_column = (row.get("species_column") or "manual_species").strip()
                    species_query = (row.get("atlas_species_query") or species_column.replace("_", " ")).strip()
                    if accession:
                        candidates.append(
                            CandidateExperiment(
                                species_column=species_column,
                                atlas_species_query=species_query,
                                search_term="manual",
                                accession=accession,
                                search_url="manual_experiment_tsv",
                                source="manual_experiment_tsv",
                            )
                        )

    # Deduplicate across search terms.
    deduped: dict[tuple[str, str], CandidateExperiment] = {}
    for candidate in candidates:
        deduped.setdefault((candidate.species_column, candidate.accession), candidate)
    candidates = list(deduped.values())

    write_tsv(
        path=candidate_path,
        rows=[
            {
                "species_column": candidate.species_column,
                "atlas_species_query": candidate.atlas_species_query,
                "search_term": candidate.search_term,
                "experiment_accession": candidate.accession,
                "search_url": candidate.search_url,
                "source": candidate.source,
                "remote_file_names": candidate.remote_file_names,
            }
            for candidate in candidates
        ],
        fieldnames=[
            "species_column",
            "atlas_species_query",
            "search_term",
            "experiment_accession",
            "search_url",
            "source",
            "remote_file_names",
        ],
    )

    log(f"Total unique candidate experiments: {len(candidates)}", log_file=log_file)

    checked_fields = [
        "species_column",
        "atlas_species_query",
        "experiment_accession",
        "file_type",
        "file_name",
        "url",
        "local_path",
        "remote_exists",
        "remote_non_empty",
        "status_code",
        "remote_bytes",
        "check_method",
    ]
    availability_fields = [
        "species_column",
        "atlas_species_query",
        "experiment_accession",
        "has_expression_matrix",
        "available_expression_file_types",
    ]

    remote_file_records: list[RemoteFile] = []
    candidate_available_types: dict[tuple[str, str], set[str]] = {}

    for index, candidate in enumerate(candidates, start=1):
        if index % 25 == 0:
            log(f"Checked remote files for {index}/{len(candidates)} experiments", log_file=log_file)

        files = build_remote_files(
            candidate=candidate,
            output_dir=output_dir,
            download_file_types=download_file_types,
        )

        for remote_file in files:
            exists, non_empty, status_code, remote_bytes, check_method = check_remote_file(
                url=remote_file.url,
                timeout_seconds=args.timeout_seconds,
            )

            append_tsv(
                path=checked_path,
                row={
                    "species_column": remote_file.species_column,
                    "atlas_species_query": remote_file.atlas_species_query,
                    "experiment_accession": remote_file.experiment_accession,
                    "file_type": remote_file.file_type,
                    "file_name": remote_file.file_name,
                    "url": remote_file.url,
                    "local_path": str(remote_file.local_path),
                    "remote_exists": safe_bool_text(exists),
                    "remote_non_empty": safe_bool_text(non_empty),
                    "status_code": "" if status_code is None else status_code,
                    "remote_bytes": "" if remote_bytes is None else remote_bytes,
                    "check_method": check_method,
                },
                fieldnames=checked_fields,
            )

            if exists and non_empty:
                remote_file_records.append(remote_file)
                if remote_file.file_type in expression_file_types:
                    key = (candidate.species_column, candidate.accession)
                    candidate_available_types.setdefault(key, set()).add(remote_file.file_type)

    selected_keys = {
        key for key, available_types in candidate_available_types.items() if available_types
    }

    for candidate in candidates:
        key = (candidate.species_column, candidate.accession)
        available_types = sorted(candidate_available_types.get(key, set()))
        append_tsv(
            path=availability_path,
            row={
                "species_column": candidate.species_column,
                "atlas_species_query": candidate.atlas_species_query,
                "experiment_accession": candidate.accession,
                "has_expression_matrix": safe_bool_text(bool(available_types)),
                "available_expression_file_types": ",".join(available_types),
            },
            fieldnames=availability_fields,
        )

    selected_remote_files = [
        remote_file for remote_file in remote_file_records
        if (remote_file.species_column, remote_file.experiment_accession) in selected_keys
    ]

    write_tsv(
        path=selected_path,
        rows=[
            {
                "species_column": remote_file.species_column,
                "atlas_species_query": remote_file.atlas_species_query,
                "experiment_accession": remote_file.experiment_accession,
                "file_type": remote_file.file_type,
                "file_name": remote_file.file_name,
                "url": remote_file.url,
                "local_path": str(remote_file.local_path),
            }
            for remote_file in selected_remote_files
        ],
        fieldnames=[
            "species_column",
            "atlas_species_query",
            "experiment_accession",
            "file_type",
            "file_name",
            "url",
            "local_path",
        ],
    )

    log(
        f"Experiments with TPM/FPKM matrices: {len(selected_keys)}; "
        f"selected remote files: {len(selected_remote_files)}",
        log_file=log_file,
    )

    download_fields = [
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
        "checked_at",
    ]

    # Always create the downloaded-files manifest, even when no downloads were
    # selected. This lets downstream wrapper scripts detect an empty result
    # cleanly instead of failing because the file is absent.
    write_tsv(
        path=downloaded_path,
        rows=[],
        fieldnames=download_fields,
    )

    for index, remote_file in enumerate(selected_remote_files, start=1):
        if index % 25 == 0:
            log(f"Downloaded/checked {index}/{len(selected_remote_files)} selected files", log_file=log_file)

        success, action, local_bytes = download_file(
            remote_file=remote_file,
            force_download=force_download,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            minimum_bytes=args.minimum_bytes,
        )

        append_tsv(
            path=downloaded_path,
            row={
                "species_column": remote_file.species_column,
                "atlas_species_query": remote_file.atlas_species_query,
                "experiment_accession": remote_file.experiment_accession,
                "file_type": remote_file.file_type,
                "file_name": remote_file.file_name,
                "url": remote_file.url,
                "local_path": str(remote_file.local_path),
                "action": action,
                "success": safe_bool_text(success),
                "local_bytes": "" if local_bytes is None else local_bytes,
                "checked_at": now_iso(),
            },
            fieldnames=download_fields,
        )

    expression_downloads = 0
    if downloaded_path.exists():
        with downloaded_path.open(mode="r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                if row.get("file_type") in expression_file_types and parse_bool(row.get("success"), default=False):
                    expression_downloads += 1

    summary_rows = [
        {
            "metric": "species_searched",
            "value": len(species_records),
        },
        {
            "metric": "candidate_experiments",
            "value": len(candidates),
        },
        {
            "metric": "experiments_with_expression_matrix",
            "value": len(selected_keys),
        },
        {
            "metric": "selected_remote_files",
            "value": len(selected_remote_files),
        },
        {
            "metric": "successful_expression_matrix_downloads",
            "value": expression_downloads,
        },
    ]

    write_tsv(
        path=summary_path,
        rows=summary_rows,
        fieldnames=["metric", "value"],
    )

    log("Python-first Expression Atlas discovery/download finished", log_file=log_file)
    log(f"Species registry: {species_registry_tsv}", log_file=log_file)
    log(f"Candidate manifest: {candidate_path}", log_file=log_file)
    log(f"Availability manifest: {availability_path}", log_file=log_file)
    log(f"Downloaded files manifest: {downloaded_path}", log_file=log_file)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
