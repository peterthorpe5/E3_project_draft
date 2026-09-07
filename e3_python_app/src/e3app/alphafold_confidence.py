"""Defensive retrieval of residue-level AlphaFold Database confidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from e3app import __version__
from e3app.errors import AppError
from e3app.external_actions import normalise_uniprot_accession

LOGGER = logging.getLogger(__name__)
ALPHAFOLD_API_BASE_URL = "https://alphafold.ebi.ac.uk/api/prediction/"
ALPHAFOLD_HOST = "alphafold.ebi.ac.uk"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MODEL_BYTES = 100 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class AlphaFoldConfidence:
    """Residue confidence parsed from one exact AlphaFold Database model."""

    accession: str
    model_url: str
    quality_by_residue: tuple[tuple[str, float], ...]


HttpReader = Callable[[str, int], bytes]


def _read_https(url: str, maximum_bytes: int) -> bytes:
    """Read one bounded AlphaFold HTTPS response.

    Args:
        url: Approved AlphaFold Database URL.
        maximum_bytes: Maximum accepted response length.

    Returns:
        Response bytes.

    Raises:
        AppError: If the URL, response or transport is invalid.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALPHAFOLD_HOST:
        raise AppError("AlphaFold response supplied an unapproved model URL")
    request = Request(url, headers={"User-Agent": f"e3-python-app/{__version__}"})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read(maximum_bytes + 1)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise AppError(f"Could not retrieve AlphaFold confidence: {exc}") from exc
    if len(payload) > maximum_bytes:
        raise AppError("AlphaFold response exceeded the defensive size limit")
    return payload


def _metadata_model_url(payload: bytes, accession: str) -> str:
    """Return the exact PDB URL from AlphaFold prediction metadata."""
    try:
        records = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("AlphaFold metadata was not valid UTF-8 JSON") from exc
    if not isinstance(records, list):
        raise AppError("AlphaFold metadata did not contain a prediction list")
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and str(record.get("uniprotAccession", "")).upper() == accession
        and isinstance(record.get("pdbUrl"), str)
    ]
    if len(matching) != 1:
        raise AppError(
            f"AlphaFold Database returned no unique model for {accession}"
        )
    model_url = str(matching[0]["pdbUrl"])
    parsed = urlparse(model_url)
    if parsed.scheme != "https" or parsed.hostname != ALPHAFOLD_HOST:
        raise AppError("AlphaFold response supplied an unapproved model URL")
    return model_url


def parse_alphafold_pdb_confidence(payload: bytes) -> tuple[tuple[str, float], ...]:
    """Parse C-alpha B factors as pLDDT from an AlphaFold PDB file.

    Args:
        payload: UTF-8 PDB bytes from AlphaFold Database.

    Returns:
        Ordered residue labels and pLDDT scores.

    Raises:
        AppError: If no unique valid C-alpha confidence records are present.
    """
    try:
        document = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppError("AlphaFold model was not valid UTF-8 PDB text") from exc
    indexed: dict[str, float] = {}
    conflicts: set[str] = set()
    for line in document.splitlines():
        if not line.startswith("ATOM  ") or len(line) < 66:
            continue
        if line[12:16].strip() != "CA" or line[16:17] not in {" ", "A"}:
            continue
        residue = line[22:26].strip()
        try:
            score = float(line[60:66].strip())
        except ValueError:
            continue
        if not residue or not 0.0 <= score <= 100.0 or residue in conflicts:
            continue
        if residue in indexed and indexed[residue] != score:
            indexed.pop(residue)
            conflicts.add(residue)
            continue
        indexed[residue] = score
    if not indexed:
        raise AppError("AlphaFold model contained no usable C-alpha pLDDT values")
    return tuple(indexed.items())


def retrieve_alphafold_confidence(
    *, accession: object, reader: HttpReader = _read_https
) -> AlphaFoldConfidence:
    """Retrieve exact residue-level confidence for one UniProt accession.

    Args:
        accession: Canonical UniProt accession.
        reader: Bounded HTTPS reader, injectable for deterministic tests.

    Returns:
        Parsed AlphaFold confidence record.

    Raises:
        AppError: If the identifier or remote response is invalid.
    """
    canonical = normalise_uniprot_accession(value=accession)
    if canonical is None:
        raise AppError("AlphaFold confidence requires a canonical UniProt accession")
    metadata_url = f"{ALPHAFOLD_API_BASE_URL}{canonical}"
    metadata = reader(metadata_url, MAX_METADATA_BYTES)
    model_url = _metadata_model_url(metadata, canonical)
    model = reader(model_url, MAX_MODEL_BYTES)
    quality = parse_alphafold_pdb_confidence(model)
    LOGGER.info(
        "Retrieved AlphaFold confidence for %s (%d residues)",
        canonical,
        len(quality),
    )
    return AlphaFoldConfidence(
        accession=canonical,
        model_url=model_url,
        quality_by_residue=quality,
    )
