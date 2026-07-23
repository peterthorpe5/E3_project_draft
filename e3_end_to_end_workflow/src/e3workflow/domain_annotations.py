"""Resumable InterPro/Pfam annotation retrieval with auditable local caching."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from e3workflow.errors import StageError
from e3workflow.io_utils import sha256_file

LOGGER = logging.getLogger("e3workflow.domain_annotations")
CACHE_SCHEMA_VERSION = 1
USER_AGENT = "e3-end-to-end-workflow/0.6 (ARIA plant E3 research; cached API client)"


@dataclass(frozen=True)
class InterProSettings:
    """Network and cache settings for the InterPro client."""

    api_base_url: str
    cache_root: Path
    allow_network: bool
    workers: int
    request_timeout_seconds: float
    max_retries: int
    retry_delay_seconds: float


def utc_now() -> str:
    """Return one RFC 3339 UTC timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def cache_path(*, cache_root: Path, accession: str) -> Path:
    """Return a collision-resistant cache path for one protein accession."""
    cleaned = "".join(character for character in accession.upper() if character.isalnum())[:24]
    digest = hashlib.sha256(accession.upper().encode("utf-8")).hexdigest()[:16]
    return Path(cache_root).expanduser().resolve() / f"{cleaned or 'ACCESSION'}.{digest}.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON through an adjacent temporary file and atomically replace the target."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_cache(path: Path, accession: str) -> dict[str, Any] | None:
    """Return a valid cache payload or ``None`` for absent/incompatible content."""
    source = Path(path)
    if not source.is_file() or source.stat().st_size == 0:
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Ignoring unreadable InterPro cache file: %s", source)
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None
    if str(payload.get("requested_accession", "")).upper() != accession.upper():
        return None
    if payload.get("retrieval_status") not in {"ANNOTATED", "PROTEIN_WITHOUT_ENTRIES", "NOT_FOUND"}:
        return None
    return payload


class InterProClient:
    """Small defensive client for the public InterPro protein API."""

    def __init__(
        self,
        *,
        settings: InterProSettings,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialise the client with injectable I/O for deterministic tests."""
        self.settings = settings
        self.opener = opener
        self.sleeper = sleeper
        parsed = urllib.parse.urlparse(settings.api_base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise StageError("InterPro API base URL must be an absolute HTTPS URL")
        self._api_host = parsed.netloc.lower()

    def _validated_url(self, url: str) -> str:
        """Reject pagination URLs that leave the configured HTTPS API host."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != self._api_host:
            raise StageError(f"InterPro response supplied an unsafe pagination URL: {url}")
        return url

    def _request_json(self, url: str) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
        """Retrieve one JSON response with bounded retry/backoff."""
        safe_url = self._validated_url(url)
        last_error = "request did not run"
        for attempt in range(self.settings.max_retries + 1):
            request = urllib.request.Request(
                safe_url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                method="GET",
            )
            try:
                with self.opener(
                    request, timeout=self.settings.request_timeout_seconds
                ) as response:
                    status = int(getattr(response, "status", response.getcode()))
                    raw = response.read()
                    headers = {
                        "interpro_version": str(response.headers.get("InterPro-Version", "")),
                        "interpro_version_minor": str(
                            response.headers.get("InterPro-Version-Minor", "")
                        ),
                        "last_modified": str(response.headers.get("Last-Modified", "")),
                    }
                    if status == 204 or not raw:
                        return status, None, headers
                    parsed = json.loads(raw.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError("top-level JSON is not an object")
                    return status, parsed, headers
            except urllib.error.HTTPError as exc:
                if exc.code in {204, 404}:
                    return exc.code, None, {}
                last_error = f"HTTP {exc.code}: {exc.reason}"
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt >= self.settings.max_retries:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.settings.max_retries:
                    break
            delay = self.settings.retry_delay_seconds * (2**attempt)
            if delay > 0:
                self.sleeper(delay)
        raise StageError(f"InterPro request failed after retries: {safe_url}: {last_error}")

    def _entry_results(self, accession: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Retrieve all paginated InterPro entry results for one accession."""
        quoted = urllib.parse.quote(accession, safe="")
        next_url: str | None = (
            f"{self.settings.api_base_url}/entry/all/protein/uniprot/{quoted}/?page_size=200"
        )
        results: list[dict[str, Any]] = []
        release: dict[str, str] = {}
        visited: set[str] = set()
        while next_url is not None:
            if next_url in visited:
                raise StageError(f"InterPro pagination loop for accession {accession}")
            visited.add(next_url)
            status, payload, headers = self._request_json(next_url)
            release.update({key: value for key, value in headers.items() if value})
            if status in {204, 404} or payload is None:
                break
            supplied_results = payload.get("results", [])
            if not isinstance(supplied_results, list) or any(
                not isinstance(item, dict) for item in supplied_results
            ):
                raise StageError(f"InterPro returned malformed entry results for {accession}")
            results.extend(supplied_results)
            supplied_next = payload.get("next")
            if supplied_next is not None and not isinstance(supplied_next, str):
                raise StageError(f"InterPro returned malformed pagination for {accession}")
            next_url = supplied_next
        return results, release

    def _protein_metadata(self, accession: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Retrieve protein metadata to distinguish no entries from no protein record."""
        quoted = urllib.parse.quote(accession, safe="")
        url = f"{self.settings.api_base_url}/protein/uniprot/{quoted}/"
        status, payload, headers = self._request_json(url)
        if status in {204, 404} or payload is None:
            return None, headers
        metadata = payload.get("metadata", payload)
        if not isinstance(metadata, dict):
            raise StageError(f"InterPro returned malformed protein metadata for {accession}")
        return metadata, headers

    def retrieve(self, accession: str) -> tuple[dict[str, Any], Path | None, bool]:
        """Read or download one cached annotation payload.

        Returns:
            Payload, cache path when present, and whether a network request was used.
        """
        requested = accession.strip().upper()
        path = cache_path(cache_root=self.settings.cache_root, accession=requested)
        cached = _load_cache(path, requested)
        if cached is not None:
            return cached, path, False
        if not self.settings.allow_network:
            return (
                {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "requested_accession": requested,
                    "retrieval_status": "CACHE_UNAVAILABLE",
                    "retrieved_at_utc": "",
                    "api_base_url": self.settings.api_base_url,
                    "release": {},
                    "protein_metadata": None,
                    "results": [],
                    "error": "network disabled and no valid cache file exists",
                },
                None,
                False,
            )
        try:
            results, release = self._entry_results(requested)
            protein_metadata: dict[str, Any] | None = None
            if results:
                retrieval_status = "ANNOTATED"
            else:
                protein_metadata, protein_release = self._protein_metadata(requested)
                release.update(
                    {key: value for key, value in protein_release.items() if value}
                )
                retrieval_status = (
                    "PROTEIN_WITHOUT_ENTRIES" if protein_metadata is not None else "NOT_FOUND"
                )
            payload = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "requested_accession": requested,
                "retrieval_status": retrieval_status,
                "retrieved_at_utc": utc_now(),
                "api_base_url": self.settings.api_base_url,
                "release": release,
                "protein_metadata": protein_metadata,
                "results": results,
                "error": "",
            }
            _atomic_json(path, payload)
            return payload, path, True
        except StageError as exc:
            LOGGER.warning("Annotation unavailable for %s: %s", requested, exc)
            return (
                {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "requested_accession": requested,
                    "retrieval_status": "DOWNLOAD_ERROR",
                    "retrieved_at_utc": utc_now(),
                    "api_base_url": self.settings.api_base_url,
                    "release": {},
                    "protein_metadata": None,
                    "results": [],
                    "error": str(exc),
                },
                None,
                True,
            )


def retrieve_annotations(
    *, accessions: Iterable[str], settings: InterProSettings
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Retrieve unique accessions concurrently and return payload and cache inventories."""
    requested = sorted({item.strip().upper() for item in accessions if item.strip()})
    client = InterProClient(settings=settings)
    payloads: dict[str, dict[str, Any]] = {}
    inventory: list[dict[str, Any]] = []

    def complete(accession: str) -> tuple[str, dict[str, Any], Path | None, bool]:
        """Retrieve one accession for the executor."""
        payload, path, network_used = client.retrieve(accession)
        return accession, payload, path, network_used

    with ThreadPoolExecutor(max_workers=settings.workers) as executor:
        futures = {executor.submit(complete, accession): accession for accession in requested}
        for completed_count, future in enumerate(as_completed(futures), start=1):
            accession, payload, path, network_used = future.result()
            payloads[accession] = payload
            inventory.append(
                {
                    "candidate_accession": accession,
                    "retrieval_status": payload.get("retrieval_status", ""),
                    "network_used": network_used,
                    "cache_path": "" if path is None else str(path),
                    "cache_sha256": "" if path is None else sha256_file(path),
                    "retrieved_at_utc": payload.get("retrieved_at_utc", ""),
                    "interpro_version": payload.get("release", {}).get(
                        "interpro_version", ""
                    ),
                    "result_count": len(payload.get("results", [])),
                    "error": payload.get("error", ""),
                }
            )
            if completed_count % 100 == 0 or completed_count == len(requested):
                LOGGER.info("InterPro annotations resolved: %d/%d", completed_count, len(requested))
    return payloads, sorted(inventory, key=lambda row: row["candidate_accession"])


def flatten_interpro_results(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten InterPro and Pfam entries and their locations from one cached response."""
    flattened: list[dict[str, Any]] = []
    for result in payload.get("results", []):
        if not isinstance(result, dict):
            continue
        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        source_database = str(metadata.get("source_database", "")).lower()
        if source_database not in {"interpro", "pfam"}:
            continue
        proteins = result.get("proteins", [])
        if not isinstance(proteins, list):
            proteins = []
        base = {
            "source_database": source_database,
            "entry_accession": str(metadata.get("accession", "")),
            "entry_name": str(metadata.get("name", "") or ""),
            "entry_type": str(metadata.get("type", "") or ""),
            "integrated_interpro_accession": str(metadata.get("integrated", "") or ""),
        }
        emitted = False
        for protein in proteins:
            if not isinstance(protein, dict):
                continue
            locations = protein.get("entry_protein_locations", [])
            if not isinstance(locations, list):
                locations = []
            protein_base = {
                **base,
                "protein_length": protein.get("protein_length", ""),
                "protein_source_database": protein.get("source_database", ""),
                "organism_tax_id": protein.get("organism", ""),
                "in_alphafold": protein.get("in_alphafold", ""),
            }
            for location in locations:
                if not isinstance(location, dict):
                    continue
                fragments = location.get("fragments", [])
                if not isinstance(fragments, list) or not fragments:
                    fragments = [{}]
                for fragment in fragments:
                    if not isinstance(fragment, dict):
                        fragment = {}
                    flattened.append(
                        {
                            **protein_base,
                            "location_start": fragment.get("start", ""),
                            "location_end": fragment.get("end", ""),
                            "discontinuity_status": fragment.get("dc-status", ""),
                            "representative": location.get("representative", ""),
                            "model": location.get("model", ""),
                            "score": location.get("score", ""),
                        }
                    )
                    emitted = True
        if not emitted:
            flattened.append(
                {
                    **base,
                    "protein_length": "",
                    "protein_source_database": "",
                    "organism_tax_id": "",
                    "in_alphafold": "",
                    "location_start": "",
                    "location_end": "",
                    "discontinuity_status": "",
                    "representative": "",
                    "model": "",
                    "score": "",
                }
            )
    return flattened
