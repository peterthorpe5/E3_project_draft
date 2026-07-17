"""AlphaFold Database metadata retrieval and validated file materialisation."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .io_utils import sha256_file, validate_accession


_LOGGER = logging.getLogger("e3ligandability.alphafold")


class AlphaFoldNotFoundError(RuntimeError):
    """Raised when AlphaFold Database has no prediction for an accession."""


class DownloadValidationError(RuntimeError):
    """Raised when a downloaded or supplied file fails content validation."""


def build_retry_session(
    retry_total: int,
    backoff_seconds: float,
) -> requests.Session:
    """Build one reusable HTTP session with bounded retry behaviour.

    Args:
        retry_total: Maximum retries for connection, read and HTTP failures.
        backoff_seconds: Exponential backoff factor.

    Returns:
        Configured requests session.
    """

    retry = Retry(
        total=retry_total,
        connect=retry_total,
        read=retry_total,
        status=retry_total,
        backoff_factor=backoff_seconds,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "e3-ligandability-pipeline/0.1.0 "
                "(ARIA plant E3 research workflow)"
            )
        }
    )
    return session


def query_prediction_metadata(
    session: requests.Session,
    api_base_url: str,
    accession: str,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Retrieve all AlphaFold Database prediction metadata for an accession.

    Args:
        session: Configured HTTP session.
        api_base_url: API route excluding the accession suffix.
        accession: Protein accession.
        timeout_seconds: Per-request timeout.

    Returns:
        Non-empty list of metadata dictionaries.

    Raises:
        AlphaFoldNotFoundError: If the API returns 404 or an empty list.
        requests.HTTPError: For other unsuccessful HTTP responses.
        ValueError: If the API payload has an unexpected structure.
    """

    safe_accession = validate_accession(accession)
    url = f"{api_base_url.rstrip('/')}/{safe_accession}"
    response = session.get(url, timeout=timeout_seconds)
    if response.status_code == 404:
        raise AlphaFoldNotFoundError(
            f"No AlphaFold Database prediction for {safe_accession}"
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(
            "AlphaFold API response must be a list; received "
            f"{type(payload).__name__}."
        )
    if not payload:
        raise AlphaFoldNotFoundError(
            f"No AlphaFold Database prediction for {safe_accession}"
        )
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("AlphaFold API list contains a non-object item.")
    return payload


def select_prediction(
    predictions: list[dict[str, Any]],
    accession: str,
) -> dict[str, Any]:
    """Select one monomeric AlphaFold prediction deterministically.

    Current AlphaFold Database responses may include more than one entry. The
    structural workflow is designed for a single protein chain, so records with
    the canonical ``AF-<accession>-F1-model_vN.cif`` filename are preferred.
    Within that set, an exact ``uniprotAccession`` match and the highest numeric
    model version are preferred. If canonical filename metadata is unavailable,
    exact accession records are used before a documented final fallback.

    Args:
        predictions: Non-empty API metadata records.
        accession: Requested accession.

    Returns:
        Selected metadata record with selection provenance fields added.

    Raises:
        ValueError: If predictions are empty.
    """

    if not predictions:
        raise ValueError("At least one AlphaFold prediction is required.")
    safe_accession = validate_accession(accession)
    exact_candidates = [
        item
        for item in predictions
        if str(item.get("uniprotAccession", "")).strip() == safe_accession
    ]
    canonical_prefix = f"AF-{safe_accession}-F1-model_v"
    monomer_candidates = [
        item
        for item in predictions
        if Path(urlparse(str(item.get("cifUrl", ""))).path).name.startswith(
            canonical_prefix
        )
    ]
    exact_monomers = [
        item for item in monomer_candidates if item in exact_candidates
    ]
    if exact_monomers:
        candidates = exact_monomers
        selection_rule = "exact_accession_canonical_monomer_highest_version"
    elif monomer_candidates:
        candidates = monomer_candidates
        selection_rule = "canonical_monomer_highest_version"
    elif exact_candidates:
        candidates = exact_candidates
        selection_rule = "exact_accession_highest_model_version"
    else:
        candidates = list(predictions)
        selection_rule = "fallback_highest_model_version"

    def version_key(record: dict[str, Any]) -> tuple[int, str]:
        """Return a stable model-version sort key for one API record."""

        cif_url = str(record.get("cifUrl", ""))
        name = Path(urlparse(cif_url).path).name
        version = -1
        if "_v" in name:
            suffix = name.rsplit("_v", maxsplit=1)[-1].split(".", maxsplit=1)[0]
            if suffix.isdigit():
                version = int(suffix)
        return version, cif_url

    selected = dict(max(candidates, key=version_key))
    selected["selection_prediction_count"] = len(predictions)
    selected["selection_exact_accession_count"] = len(exact_candidates)
    selected["selection_canonical_monomer_count"] = len(monomer_candidates)
    selected["selection_rule"] = selection_rule
    return selected


def normalise_prediction_metadata(
    accession: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Normalise API metadata into a stable flat schema.

    Args:
        accession: Requested accession.
        metadata: Selected API metadata object.

    Returns:
        Flat metadata dictionary used by manifests and outputs.
    """

    safe_accession = validate_accession(accession)
    confident = metadata.get("fractionPlddtConfident")
    very_high = metadata.get("fractionPlddtVeryHigh")
    fraction_ge_70: float | None = None
    if confident is not None and very_high is not None:
        fraction_ge_70 = float(confident) + float(very_high)

    return {
        "accession": safe_accession,
        "entry_id": metadata.get("entryId"),
        "uniprot_accession": metadata.get("uniprotAccession"),
        "global_metric_value": metadata.get("globalMetricValue"),
        "fraction_plddt_very_low": metadata.get("fractionPlddtVeryLow"),
        "fraction_plddt_low": metadata.get("fractionPlddtLow"),
        "fraction_plddt_confident": confident,
        "fraction_plddt_very_high": very_high,
        "api_fraction_residues_ge_70": fraction_ge_70,
        "cif_url": metadata.get("cifUrl"),
        "pae_url": metadata.get("paeDocUrl"),
        "msa_url": metadata.get("msaUrl"),
        "plddt_url": metadata.get("plddtDocUrl"),
        "model_created_date": metadata.get("modelCreatedDate"),
        "latest_version": metadata.get("latestVersion"),
        "selection_prediction_count": metadata.get(
            "selection_prediction_count"
        ),
        "selection_exact_accession_count": metadata.get(
            "selection_exact_accession_count"
        ),
        "selection_canonical_monomer_count": metadata.get(
            "selection_canonical_monomer_count"
        ),
        "selection_rule": metadata.get("selection_rule"),
    }


def validate_cif_file(path: Path) -> None:
    """Validate that a file resembles a non-empty macromolecular CIF model.

    Args:
        path: Candidate CIF file.

    Raises:
        DownloadValidationError: If required CIF markers are absent.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size < 128:
        raise DownloadValidationError(f"CIF file is missing or too small: {source}")
    with source.open("r", encoding="utf-8", errors="strict") as handle:
        prefix = handle.read(1024 * 1024)
    if not prefix.lstrip().startswith("data_"):
        raise DownloadValidationError(f"CIF lacks a data_ block: {source}")
    if "_atom_site." not in prefix:
        raise DownloadValidationError(f"CIF lacks _atom_site data: {source}")


def validate_json_file(path: Path) -> None:
    """Validate that a file contains non-empty JSON data.

    Args:
        path: Candidate JSON file.

    Raises:
        DownloadValidationError: If JSON cannot be parsed or is empty.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size < 2:
        raise DownloadValidationError(f"JSON file is missing or empty: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DownloadValidationError(f"Invalid JSON file: {source}") from error
    if payload in ({}, [], None):
        raise DownloadValidationError(f"JSON payload is empty: {source}")


def validate_a3m_file(path: Path) -> None:
    """Validate that an A3M file contains at least one FASTA-style record.

    Args:
        path: Candidate A3M file.

    Raises:
        DownloadValidationError: If the file is absent, empty or malformed.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise DownloadValidationError(f"A3M file is missing or empty: {source}")
    text = source.read_text(encoding="utf-8", errors="strict")
    if not any(line.startswith(">") for line in text.splitlines()):
        raise DownloadValidationError(f"A3M lacks a FASTA header: {source}")


def _url_filename(url: str, fallback: str) -> str:
    """Extract a safe filename from a URL.

    Args:
        url: Source URL.
        fallback: Filename used when the URL path has no basename.

    Returns:
        Safe basename.
    """

    name = Path(urlparse(url).path).name
    return name if name else fallback


def download_atomic(
    session: requests.Session,
    url: str,
    destination: Path,
    timeout_seconds: float,
    validator: Callable[[Path], None],
) -> dict[str, Any]:
    """Download a file to a temporary path, validate it and publish atomically.

    Args:
        session: Configured HTTP session.
        url: HTTP(S) source URL.
        destination: Final local path.
        timeout_seconds: Per-request timeout.
        validator: Content validator called before publication.

    Returns:
        File manifest record.

    Raises:
        ValueError: If URL is not HTTP(S).
        requests.HTTPError: If the server returns an unsuccessful status.
        DownloadValidationError: If downloaded content is invalid.
    """

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported download URL scheme: {url}")

    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.",
        suffix=".part",
        dir=target.parent,
        delete=False,
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()

    try:
        with session.get(url, timeout=timeout_seconds, stream=True) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as handle:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    if block:
                        handle.write(block)
                handle.flush()
        validator(temporary_path)
        temporary_path.replace(target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return {
        "path": str(target),
        "url": url,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "action": "downloaded",
    }


def copy_atomic(
    source: Path,
    destination: Path,
    validator: Callable[[Path], None],
) -> dict[str, Any]:
    """Copy, validate and atomically publish a local file.

    Args:
        source: Existing local file.
        destination: Final copied path.
        validator: Content validator called before publication.

    Returns:
        File manifest record.
    """

    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.copying")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copy2(source_path, temporary)
        validator(temporary)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "path": str(target),
        "source_path": str(source_path),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "action": "copied",
    }


def reuse_valid_file(
    path: Path,
    validator: Callable[[Path], None],
) -> dict[str, Any] | None:
    """Return a manifest record when an existing file passes validation.

    Args:
        path: Candidate existing file.
        validator: Content validator.

    Returns:
        Manifest record, or ``None`` when no existing file is present.

    Raises:
        DownloadValidationError: If a present file fails validation.
    """

    target = Path(path).expanduser().resolve()
    if not target.exists():
        return None
    validator(target)
    return {
        "path": str(target),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "action": "reused",
    }


def materialise_model_assets(
    accession: str,
    input_record: dict[str, str],
    metadata: dict[str, Any],
    output_directory: Path,
    session: requests.Session,
    timeout_seconds: float,
    reuse_existing: bool,
    download_pae: bool,
    download_msa: bool,
    download_plddt_json: bool,
) -> tuple[Path, list[dict[str, Any]]]:
    """Create a validated local AlphaFold asset set for one accession.

    A user-supplied ``model_path`` takes precedence over API URLs. Optional
    supporting assets are downloaded only when requested and available.

    Args:
        accession: Protein accession.
        input_record: Source input row.
        metadata: Normalised AlphaFold metadata.
        output_directory: Run-level models directory.
        session: Configured HTTP session.
        timeout_seconds: Per-request timeout.
        reuse_existing: Reuse present validated files.
        download_pae: Download PAE JSON when available.
        download_msa: Download A3M when available.
        download_plddt_json: Download pLDDT JSON when available.

    Returns:
        Model CIF path and asset manifest records.

    Raises:
        ValueError: If neither a local model nor CIF URL is available.
    """

    safe_accession = validate_accession(accession)
    accession_directory = Path(output_directory).resolve() / safe_accession
    accession_directory.mkdir(parents=True, exist_ok=True)
    manifests: list[dict[str, Any]] = []

    supplied_model = input_record.get("model_path", "").strip()
    cif_url = str(
        input_record.get("cif_url", "").strip() or metadata.get("cif_url") or ""
    )
    if supplied_model:
        source_model = Path(supplied_model).expanduser().resolve()
        model_name = source_model.name
        model_path = accession_directory / model_name
        reused = (
            reuse_valid_file(model_path, validate_cif_file)
            if reuse_existing
            else None
        )
        manifests.append(
            reused
            if reused is not None
            else copy_atomic(source_model, model_path, validate_cif_file)
        )
    elif cif_url:
        model_name = _url_filename(cif_url, f"AF-{safe_accession}-F1-model.cif")
        model_path = accession_directory / model_name
        reused = (
            reuse_valid_file(model_path, validate_cif_file)
            if reuse_existing
            else None
        )
        manifests.append(
            reused
            if reused is not None
            else download_atomic(
                session,
                cif_url,
                model_path,
                timeout_seconds,
                validate_cif_file,
            )
        )
    else:
        raise ValueError(
            "No local model_path or AlphaFold CIF URL is available for "
            f"{safe_accession}."
        )

    optional_assets = [
        (
            "pae_url",
            "pae_url",
            download_pae,
            validate_json_file,
            f"AF-{safe_accession}-F1-pae.json",
        ),
        (
            "msa_url",
            "msa_url",
            download_msa,
            validate_a3m_file,
            f"AF-{safe_accession}-F1-msa.a3m",
        ),
        (
            "plddt_url",
            "plddt_url",
            download_plddt_json,
            validate_json_file,
            f"AF-{safe_accession}-F1-confidence.json",
        ),
    ]
    for input_key, metadata_key, enabled, validator, fallback in optional_assets:
        if not enabled:
            continue
        url = str(
            input_record.get(input_key, "").strip()
            or metadata.get(metadata_key)
            or ""
        )
        if not url:
            _LOGGER.warning(
                "Optional AlphaFold asset URL missing for %s: %s",
                safe_accession,
                metadata_key,
            )
            continue
        asset_path = accession_directory / _url_filename(url, fallback)
        reused = reuse_valid_file(asset_path, validator) if reuse_existing else None
        manifests.append(
            reused
            if reused is not None
            else download_atomic(
                session,
                url,
                asset_path,
                timeout_seconds,
                validator,
            )
        )

    for record in manifests:
        record["accession"] = safe_accession
    return model_path, manifests
