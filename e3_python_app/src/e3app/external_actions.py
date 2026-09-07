"""Safe external analysis actions for selected E3 protein pairs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Sequence
from urllib.parse import urlencode

import pandas as pd

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

EMERALD_BASE_URL = "https://algbio.github.io/emerald-ui/"
MOLSTAR_VIEWER_BASE_URL = "https://molstar.org/viewer/"
RCSB_PAIRWISE_ALIGNMENT_BASE_URL = "https://www.rcsb.org/alignment"
ALPHAFOLD_ENTRY_BASE_URL = "https://alphafold.ebi.ac.uk/entry/"

_UNIPROT_ACCESSION_PATTERN = re.compile(
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|"
    r"[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
)
_AMINO_ACID_PATTERN = re.compile(r"[ABCDEFGHIKLMNPQRSTVWXYZOUJ]+")
_SEQUENCE_COLUMN_PREFERENCE = (
    "amino_acid_sequence",
    "protein_sequence",
    "aligned_sequence",
)


@dataclass(frozen=True)
class ExternalPairActions:
    """Validated URLs available for one selected protein pair.

    Attributes:
        reference_accession: Original reference identifier shown in the app.
        comparison_accession: Original comparison identifier shown in the app.
        emerald_url: Pre-populated EMERALD URL, or ``None`` for non-UniProt IDs.
        reference_alphafold_url: AlphaFold record URL for a valid reference.
        comparison_alphafold_url: AlphaFold record URL for a valid comparison.
        reference_molstar_url: Exact AlphaFold model in the Mol* viewer.
        comparison_molstar_url: Exact AlphaFold model in the Mol* viewer.
        rcsb_pairwise_alignment_url: Pre-populated RCSB pairwise alignment.
    """

    reference_accession: str
    comparison_accession: str
    emerald_url: str | None
    reference_alphafold_url: str | None
    comparison_alphafold_url: str | None
    reference_molstar_url: str | None
    comparison_molstar_url: str | None
    rcsb_pairwise_alignment_url: str | None


def normalise_uniprot_accession(*, value: object) -> str | None:
    """Return a canonical UniProt accession when the whole value is valid.

    The external EMERALD URL contract accepts canonical six- or ten-character
    UniProt accessions. Isoform suffixes and embedded identifiers are not
    silently rewritten because doing so could select a different sequence.

    Args:
        value: Candidate accession value.

    Returns:
        Upper-case accession, or ``None`` when the value is not an exact
        supported UniProt accession.
    """
    text = str(value or "").strip().upper()
    if not text or _UNIPROT_ACCESSION_PATTERN.fullmatch(text) is None:
        return None
    return text


def build_emerald_pair_url(
    *,
    reference_accession: object,
    comparison_accession: object,
    alpha: float = 0.75,
    delta: int = 8,
) -> str | None:
    """Build a validated EMERALD pair URL for canonical UniProt accessions.

    Args:
        reference_accession: Sequence A UniProt accession.
        comparison_accession: Sequence B UniProt accession.
        alpha: EMERALD safety-window alpha value from zero to one.
        delta: Non-negative EMERALD suboptimality value, at most 100.

    Returns:
        Pre-populated EMERALD URL, or ``None`` when either identifier is not a
        supported canonical UniProt accession.

    Raises:
        AppError: If alpha or delta is outside EMERALD's documented URL range.
    """
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not 0.0 <= float(alpha) <= 1.0
    ):
        raise AppError("EMERALD alpha must be between 0 and 1")
    if isinstance(delta, bool) or not isinstance(delta, int) or not 0 <= delta <= 100:
        raise AppError("EMERALD delta must be an integer between 0 and 100")
    reference = normalise_uniprot_accession(value=reference_accession)
    comparison = normalise_uniprot_accession(value=comparison_accession)
    if reference is None or comparison is None:
        return None
    query = urlencode(
        {
            "seqA": reference,
            "seqB": comparison,
            "alpha": f"{float(alpha):g}",
            "delta": str(delta),
        }
    )
    return f"{EMERALD_BASE_URL}?{query}"


def build_alphafold_entry_url(*, accession: object) -> str | None:
    """Return an AlphaFold Database record URL for a valid UniProt accession.

    Args:
        accession: Candidate canonical UniProt accession.

    Returns:
        AlphaFold Database record URL, or ``None`` for another identifier type.
    """
    canonical = normalise_uniprot_accession(value=accession)
    return None if canonical is None else f"{ALPHAFOLD_ENTRY_BASE_URL}{canonical}"


def build_molstar_alphafold_url(*, accession: object) -> str | None:
    """Return a Mol* viewer URL that loads one exact AlphaFold DB model.

    Mol* documents the ``afdb`` query parameter for its viewer application.
    Supplying only the generic viewer route produces the empty start screen,
    so this helper fails closed for identifiers that are not canonical UniProt
    accessions.

    Args:
        accession: Candidate canonical UniProt accession.

    Returns:
        Pre-populated Mol* URL, or ``None`` for another identifier type.
    """
    canonical = normalise_uniprot_accession(value=accession)
    if canonical is None:
        return None
    return f"{MOLSTAR_VIEWER_BASE_URL}?{urlencode({'afdb': canonical})}"


def alphafold_rcsb_model_id(*, accession: object) -> str | None:
    """Return the RCSB Computed Structure Model ID for an AlphaFold entry.

    Args:
        accession: Candidate canonical UniProt accession.

    Returns:
        RCSB identifier in ``AF_AF<accession>F1`` form, or ``None``.
    """
    canonical = normalise_uniprot_accession(value=accession)
    return None if canonical is None else f"AF_AF{canonical}F1"


def build_rcsb_pairwise_alignment_url(
    *, reference_accession: object, comparison_accession: object
) -> str | None:
    """Return an RCSB pairwise URL preloaded with both AlphaFold models.

    The RCSB alignment application accepts a URL-encoded ``request-body``.
    AlphaFold Computed Structure Models are monomers with asymmetry ID ``A``;
    the reference is intentionally first in the request.

    Args:
        reference_accession: Fixed structural-reference UniProt accession.
        comparison_accession: Mobile/comparison UniProt accession.

    Returns:
        Exact pairwise-alignment URL, or ``None`` if either identifier cannot
        be represented without guessing.
    """
    reference_id = alphafold_rcsb_model_id(accession=reference_accession)
    comparison_id = alphafold_rcsb_model_id(accession=comparison_accession)
    if reference_id is None or comparison_id is None:
        return None
    request = {
        "query": {
            "context": {
                "mode": "pairwise",
                "method": {"name": "fatcat-rigid"},
                "structures": [
                    {"entry_id": reference_id, "selection": {"asym_id": "A"}},
                    {"entry_id": comparison_id, "selection": {"asym_id": "A"}},
                ],
            }
        }
    }
    query = urlencode(
        {"request-body": json.dumps(request, separators=(",", ":"))}
    )
    return f"{RCSB_PAIRWISE_ALIGNMENT_BASE_URL}?{query}"


def external_pair_actions(
    *, reference_accession: object, comparison_accession: object
) -> ExternalPairActions:
    """Return every safe external action for a selected protein pair.

    Args:
        reference_accession: Fixed structural reference identifier.
        comparison_accession: Aligned/mobile protein identifier.

    Returns:
        Immutable action URLs with unavailable identifier-specific actions set
        to ``None``.
    """
    reference = str(reference_accession or "").strip()
    comparison = str(comparison_accession or "").strip()
    if not reference or not comparison:
        raise AppError("Both reference and comparison accessions are required")
    actions = ExternalPairActions(
        reference_accession=reference,
        comparison_accession=comparison,
        emerald_url=build_emerald_pair_url(
            reference_accession=reference,
            comparison_accession=comparison,
        ),
        reference_alphafold_url=build_alphafold_entry_url(accession=reference),
        comparison_alphafold_url=build_alphafold_entry_url(accession=comparison),
        reference_molstar_url=build_molstar_alphafold_url(accession=reference),
        comparison_molstar_url=build_molstar_alphafold_url(accession=comparison),
        rcsb_pairwise_alignment_url=build_rcsb_pairwise_alignment_url(
            reference_accession=reference,
            comparison_accession=comparison,
        ),
    )
    LOGGER.debug(
        "Prepared external pair actions reference=%s comparison=%s "
        "emerald=%s molstar_pair=%s rcsb_alignment=%s",
        reference,
        comparison,
        actions.emerald_url is not None,
        actions.reference_molstar_url is not None
        and actions.comparison_molstar_url is not None,
        actions.rcsb_pairwise_alignment_url is not None,
    )
    return actions


def _normalise_sequence(*, value: object, accession: str) -> str:
    """Return an ungapped validated amino-acid sequence."""
    sequence = re.sub(r"\s+", "", str(value or "")).replace("-", "").upper()
    if not sequence or _AMINO_ACID_PATTERN.fullmatch(sequence) is None:
        raise AppError(f"Invalid amino-acid sequence for {accession}")
    return sequence


def _sequence_for_accession(
    *, sources: Sequence[pd.DataFrame], accession: str
) -> str:
    """Return one unambiguous exact sequence from ordered source tables."""
    matches: list[str] = []
    for source in sources:
        if source.empty or "candidate_accession" not in source.columns:
            continue
        selected = source[
            source["candidate_accession"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            == accession.casefold()
        ]
        for column in _SEQUENCE_COLUMN_PREFERENCE:
            if column not in selected.columns:
                continue
            for value in selected[column].tolist():
                if pd.isna(value) or not str(value).strip():
                    continue
                matches.append(
                    _normalise_sequence(value=value, accession=accession)
                )
            if matches:
                break
        if matches:
            break
    unique = tuple(dict.fromkeys(matches))
    if not unique:
        raise AppError(f"No exact sequence is available for {accession}")
    if len(unique) != 1:
        raise AppError(f"Conflicting exact sequences are available for {accession}")
    return unique[0]


def _fasta_header(*, accession: str, role: str) -> str:
    """Return a single-line, injection-safe FASTA header."""
    clean = re.sub(r"[\r\n\t]+", " ", accession).strip()
    if not clean:
        raise AppError(f"The {role} accession is empty")
    return f">{clean} role={role}"


def selected_pair_fasta_bytes(
    *,
    sources: Sequence[pd.DataFrame],
    reference_accession: object,
    comparison_accession: object,
) -> bytes:
    """Return exact ungapped FASTA for a reference/comparison pair.

    Args:
        sources: Ordered sequence tables. Earlier tables have precedence.
        reference_accession: Fixed reference identifier.
        comparison_accession: Comparison/mobile identifier.

    Returns:
        UTF-8 FASTA bytes with 80-residue sequence lines.

    Raises:
        AppError: If identifiers are blank, equal, missing, invalid or map to
            conflicting exact sequences.
    """
    reference = str(reference_accession or "").strip()
    comparison = str(comparison_accession or "").strip()
    if not reference or not comparison:
        raise AppError("Both reference and comparison accessions are required")
    if reference.casefold() == comparison.casefold():
        raise AppError("Reference and comparison accessions must be different")
    records = []
    for accession, role in (
        (reference, "reference"),
        (comparison, "comparison"),
    ):
        sequence = _sequence_for_accession(
            sources=sources,
            accession=accession,
        )
        wrapped = "\n".join(
            sequence[index:index + 80]
            for index in range(0, len(sequence), 80)
        )
        records.append(
            f"{_fasta_header(accession=accession, role=role)}\n{wrapped}"
        )
    return ("\n".join(records) + "\n").encode("utf-8")
