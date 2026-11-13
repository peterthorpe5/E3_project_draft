"""Retrieve exact public protein records by accession for missing release sequences."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import logging
import os
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

from e3app.errors import AppError
from e3app.external_actions import normalise_uniprot_accession

from .common import ResearchError, fasta_records
from .providers import http_request

LOGGER = logging.getLogger(__name__)
NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
UNIPROT_FASTA = "https://rest.uniprot.org/uniprotkb/"
NCBI_ACCESSION = re.compile(r"(?:[A-Z]P_\d{5,12}|[A-Z]{3}(?:\d{5}|\d{7}))(?:\.[1-9]\d*)?")
_NCBI_REQUEST_LOCK = Lock()
_NCBI_NEXT_REQUEST = 0.0


@dataclass(frozen=True, kw_only=True)
class ProteinSequence:
    """An accession-resolved public protein sequence and its provider."""

    accession: str
    sequence: str
    source: str


def sequence_lookup_target(*, identifier: str) -> tuple[str, str] | None:
    """Identify an exact UniProt or NCBI protein accession without stripping isoforms.

    Args:
        identifier: Published raw or parsed protein identifier.

    Returns:
        Provider and requested accession, or None for an unsupported local ID.
    """
    text = identifier.strip().upper()
    if not text or not text.isascii() or not text.isprintable() or len(text) > 100:
        return None
    fields = text.split("|")
    if len(fields) > 4 and fields[0] == "GI" and fields[1].isdigit():
        fields = fields[2:]
    if len(fields) > 2 and fields[0] in {"SP", "TR", "REF", "GB", "EMB", "DBJ"}:
        text = fields[1]
    canonical, separator, isoform = text.partition("-")
    if normalise_uniprot_accession(value=canonical) and (
        not separator or re.fullmatch(r"[1-9]\d{0,4}", isoform)
    ):
        return "UniProt", text
    if NCBI_ACCESSION.fullmatch(text):
        return "NCBI Protein", text
    return None


def fetch_protein_sequence(*, identifier: str) -> ProteinSequence:
    """Fetch a single accession-matched public FASTA using the provider's protein endpoint.

    Args:
        identifier: Exact supported UniProt or NCBI protein accession or FASTA identifier.

    Returns:
        Validated sequence, returned accession (including any version) and its provider.

    Raises:
        AppError: If retrieval fails or the response does not identify the requested record.
    """
    target = sequence_lookup_target(identifier=identifier)
    if target is None:
        raise AppError("Use an exact UniProt or NCBI protein accession.")
    source, accession = target
    maximum_bytes = 1_000_000
    try:
        if source == "UniProt":
            payload = http_request(url=f"{UNIPROT_FASTA}{accession}.fasta",
                                   maximum_bytes=maximum_bytes)
        else:
            parameters = {
                "db": "protein", "id": accession, "rettype": "fasta", "retmode": "text",
                "tool": "e3_python_app",
            }
            if contact := os.environ.get("E3_NCBI_EMAIL", "").strip():
                parameters["email"] = contact
            # Limit request starts across all sessions without holding the lock over I/O.
            global _NCBI_NEXT_REQUEST
            with _NCBI_REQUEST_LOCK:
                now = monotonic()
                if now < _NCBI_NEXT_REQUEST:
                    raise ResearchError("Wait a moment, then retry the NCBI lookup.")
                _NCBI_NEXT_REQUEST = now + 0.35
            payload = http_request(
                url=NCBI_EFETCH, method="POST", body=urlencode(parameters).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                maximum_bytes=maximum_bytes,
            )
        records = list(fasta_records(lines=StringIO(payload.decode("utf-8"))))
        if len(records) != 1:
            raise ResearchError("The provider did not return one protein FASTA record.")
        returned = sequence_lookup_target(identifier=records[0][0])
        exact = returned == target
        versioned = (
            source == "NCBI Protein" and "." not in accession and returned is not None
            and returned[0] == source and returned[1].split(".")[0] == accession
        )
        if not (exact or versioned):
            raise ResearchError("The returned FASTA identifies a different accession.")
    except (ResearchError, UnicodeError) as exc:
        LOGGER.warning("Protein sequence retrieval failed for %s from %s: %s",
                       accession, source, exc)
        raise AppError(f"Could not retrieve {accession} from {source}. {exc}") from exc
    LOGGER.info("Retrieved %s from %s as %s", accession, source, returned[1])
    return ProteinSequence(accession=returned[1], sequence=records[0][1], source=source)
