"""Build bounded AlphaFold Database model bundles for one selected HOG."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import logging
import math
import re
from typing import Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from e3app import __version__
from e3app.errors import AppError
from e3app.external_actions import normalise_uniprot_accession

LOGGER = logging.getLogger(__name__)

AF3_INSPECTOR_URL = "https://pdbms.altervista.org/af3viewer/afviewer8.html"
ALPHAFOLD_API_BASE_URL = "https://alphafold.ebi.ac.uk/api/prediction/"
ALPHAFOLD_HOST = "alphafold.ebi.ac.uk"
HTTP_TIMEOUT_SECONDS = 30
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MODEL_BYTES = 100 * 1024 * 1024
MAX_PAE_BYTES = 200 * 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_MODELS = 1000
MAX_DOWNLOAD_WORKERS = 4
_UNIPROT_RAW_IDENTIFIER_PATTERN = re.compile(
    r"^\s*(?:sp|tr)\|([^|\s]+)\|",
    flags=re.IGNORECASE,
)


class AlphaFoldModelUnavailable(AppError):
    """Raised when AlphaFold Database has no suitable model for an accession."""


@dataclass(frozen=True)
class HogModelCandidate:
    """One unique HOG member that can be queried in AlphaFold Database."""

    accession: str
    species: str
    label: str


@dataclass(frozen=True)
class AlphaFoldModelReference:
    """Approved AlphaFold Database URLs for one UniProt accession."""

    accession: str
    model_url: str
    pae_url: str | None


@dataclass(frozen=True)
class AlphaFoldBundleRecord:
    """Manifest record for one requested HOG-member model."""

    model_index: int
    accession: str
    species: str
    status: str
    model_url: str
    model_bytes: int
    model_sha256: str
    pae_status: str
    pae_url: str
    detail: str


@dataclass(frozen=True)
class AlphaFoldHogBundle:
    """Download-ready Inspector compatibility archive and its audit records."""

    payload: bytes
    records: tuple[AlphaFoldBundleRecord, ...]

    @property
    def requested_count(self) -> int:
        """Return the number of requested unique accessions."""
        return len(self.records)

    @property
    def included_count(self) -> int:
        """Return the number of models written to the archive."""
        return sum(record.status == "included" for record in self.records)

    @property
    def pae_count(self) -> int:
        """Return the number of included models with converted PAE data."""
        return sum(record.pae_status == "included" for record in self.records)

    @property
    def skipped_accessions(self) -> tuple[str, ...]:
        """Return requested accessions without an included model."""
        return tuple(
            record.accession
            for record in self.records
            if record.status != "included"
        )


@dataclass(frozen=True)
class _RetrievedModel:
    """Internal result of one bounded model retrieval attempt."""

    accession: str
    status: str
    detail: str
    reference: AlphaFoldModelReference | None = None
    model: bytes = b""
    pae: bytes | None = None
    pae_status: str = "not_available"


HttpReader = Callable[[str, int], bytes]


def hog_model_candidates(*, members: pd.DataFrame) -> tuple[HogModelCandidate, ...]:
    """Return unique canonical UniProt candidates in current member order.

    Args:
        members: HOG member rows containing a parsed accession, a structural
            accession or a standard UniProt ``sp|ACCESSION|`` or
            ``tr|ACCESSION|`` raw identifier. Species and within-HOG rank fields
            are optional.

    Returns:
        Unique candidates suitable for an AlphaFold Database query.

    Raises:
        AppError: If no supported accession source column is present.
    """
    accession_columns = (
        "member_parsed_accession",
        "member_structural_accession",
        "member_raw_identifier",
    )
    if not any(column in members.columns for column in accession_columns):
        raise AppError(
            "HOG model selection requires an accession source: a parsed "
            "accession, structural accession or raw member identifier"
        )

    candidates: list[HogModelCandidate] = []
    seen: set[str] = set()
    for _, row in members.iterrows():
        accession = _member_accession(row=row)
        if accession is None or accession in seen:
            continue
        seen.add(accession)
        raw_species = row.get("member_species", "")
        species = "" if pd.isna(raw_species) else str(raw_species).strip()
        species_label = species.replace("_", " ")
        parts = [accession]
        if species_label:
            parts.append(species_label)
        raw_rank = pd.to_numeric(
            pd.Series([row.get("member_structural_readiness_rank")]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(raw_rank):
            parts.append(f"within-HOG rank {int(raw_rank):,}")
        candidates.append(
            HogModelCandidate(
                accession=accession,
                species=species,
                label=" · ".join(parts),
            )
        )
    LOGGER.debug("Prepared %d unique HOG model candidates", len(candidates))
    return tuple(candidates)


def _member_accession(*, row: pd.Series) -> str | None:
    """Return a canonical accession from one enriched HOG member row.

    Explicit parsed and structural fields take precedence. The raw-field
    fallback recognises only the standard UniProt ``sp|...|`` and ``tr|...|``
    formats; arbitrary embedded text is deliberately not guessed.
    """
    for column in ("member_parsed_accession", "member_structural_accession"):
        accession = normalise_uniprot_accession(value=row.get(column))
        if accession is not None:
            return accession
    raw_identifier = str(row.get("member_raw_identifier") or "").strip()
    match = _UNIPROT_RAW_IDENTIFIER_PATTERN.match(raw_identifier)
    if match is None:
        return normalise_uniprot_accession(value=raw_identifier)
    return normalise_uniprot_accession(value=match.group(1))


def _read_https(url: str, maximum_bytes: int) -> bytes:
    """Read one bounded response from the approved AlphaFold DB host."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALPHAFOLD_HOST:
        raise AppError("AlphaFold response supplied an unapproved URL")
    request = Request(url, headers={"User-Agent": f"e3-python-app/{__version__}"})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read(maximum_bytes + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise AlphaFoldModelUnavailable("no AlphaFold Database model") from exc
        raise AppError(f"AlphaFold Database returned HTTP {exc.code}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise AppError(f"Could not retrieve AlphaFold Database data: {exc}") from exc
    if len(payload) > maximum_bytes:
        raise AppError("AlphaFold response exceeded the defensive size limit")
    return payload


def _approved_alphafold_url(*, value: object, suffix: str) -> str:
    """Return an approved AlphaFold DB file URL with an exact suffix."""
    url = str(value or "").strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALPHAFOLD_HOST
        or not parsed.path.casefold().endswith(suffix.casefold())
    ):
        raise AppError(f"AlphaFold metadata supplied an invalid {suffix} URL")
    return url


def parse_model_reference(
    *, payload: bytes, accession: str
) -> AlphaFoldModelReference:
    """Parse one exact mmCIF and optional PAE URL from API metadata.

    Args:
        payload: AlphaFold Database prediction API response.
        accession: Canonical accession requested from that endpoint.

    Returns:
        Approved model reference.

    Raises:
        AlphaFoldModelUnavailable: If no mmCIF model is published.
        AppError: If metadata is malformed, ambiguous or unsafe.
    """
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
        and isinstance(record.get("cifUrl"), str)
    ]
    if not matching:
        raise AlphaFoldModelUnavailable("no AlphaFold Database mmCIF model")
    model_urls = {
        _approved_alphafold_url(value=record["cifUrl"], suffix=".cif")
        for record in matching
    }
    if len(model_urls) != 1:
        raise AppError("AlphaFold Database returned ambiguous mmCIF models")
    pae_values = {
        str(record.get("paeDocUrl", "")).strip()
        for record in matching
        if str(record.get("paeDocUrl", "")).strip()
    }
    if len(pae_values) > 1:
        raise AppError("AlphaFold Database returned ambiguous PAE documents")
    pae_url = None
    if pae_values:
        pae_url = _approved_alphafold_url(
            value=next(iter(pae_values)),
            suffix=".json",
        )
    return AlphaFoldModelReference(
        accession=accession,
        model_url=next(iter(model_urls)),
        pae_url=pae_url,
    )


def convert_alphafold_pae_for_inspector(*, payload: bytes) -> bytes:
    """Convert an AlphaFold DB PAE document to the Inspector full-data shape.

    Args:
        payload: AlphaFold DB PAE JSON bytes.

    Returns:
        Compact UTF-8 JSON containing PAE and monomer residue labels.

    Raises:
        AppError: If the PAE document is malformed or unsafe to represent.
    """
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("AlphaFold PAE was not valid UTF-8 JSON") from exc
    if isinstance(document, list) and len(document) == 1:
        document = document[0]
    if not isinstance(document, dict):
        raise AppError("AlphaFold PAE did not contain one prediction object")
    matrix = document.get("predicted_aligned_error", document.get("pae"))
    if not isinstance(matrix, list) or not matrix:
        raise AppError("AlphaFold PAE did not contain a non-empty matrix")
    dimension = len(matrix)
    for row in matrix:
        if not isinstance(row, list) or len(row) != dimension:
            raise AppError("AlphaFold PAE matrix was not square")
        for value in row:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 100.0
            ):
                raise AppError("AlphaFold PAE contained an invalid value")
    converted = {
        "pae": matrix,
        "token_chain_ids": ["A"] * dimension,
        "token_res_ids": list(range(1, dimension + 1)),
    }
    return json.dumps(converted, separators=(",", ":")).encode("utf-8")


def _validate_model(*, payload: bytes) -> None:
    """Require a non-empty text mmCIF document before adding it to a ZIP."""
    if not payload or b"\x00" in payload:
        raise AppError("AlphaFold model was empty or not a text mmCIF file")
    try:
        prefix = payload[:4096].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppError("AlphaFold model was not valid UTF-8 mmCIF text") from exc
    if not prefix.lstrip().startswith("data_"):
        raise AppError("AlphaFold model did not start with an mmCIF data block")


def _retrieve_model(*, accession: str, reader: HttpReader) -> _RetrievedModel:
    """Retrieve one model and optional PAE while containing per-model errors."""
    try:
        metadata = reader(
            f"{ALPHAFOLD_API_BASE_URL}{accession}",
            MAX_METADATA_BYTES,
        )
        reference = parse_model_reference(payload=metadata, accession=accession)
        model = reader(reference.model_url, MAX_MODEL_BYTES)
        _validate_model(payload=model)
    except AlphaFoldModelUnavailable as exc:
        LOGGER.info("No AlphaFold Database model for %s: %s", accession, exc)
        return _RetrievedModel(
            accession=accession,
            status="not_available",
            detail=str(exc),
        )
    except AppError as exc:
        LOGGER.warning("AlphaFold model retrieval failed for %s: %s", accession, exc)
        return _RetrievedModel(
            accession=accession,
            status="error",
            detail=str(exc),
        )

    pae = None
    pae_status = "not_available"
    detail = ""
    if reference.pae_url is not None:
        try:
            pae_payload = reader(reference.pae_url, MAX_PAE_BYTES)
            pae = convert_alphafold_pae_for_inspector(payload=pae_payload)
            pae_status = "included"
        except (AlphaFoldModelUnavailable, AppError) as exc:
            pae_status = "error"
            detail = f"Model included; PAE unavailable: {exc}"
            LOGGER.warning("AlphaFold PAE retrieval failed for %s: %s", accession, exc)
    LOGGER.debug(
        "Retrieved AlphaFold model %s: model_bytes=%d pae_status=%s",
        accession,
        len(model),
        pae_status,
    )
    return _RetrievedModel(
        accession=accession,
        status="available",
        detail=detail,
        reference=reference,
        model=model,
        pae=pae,
        pae_status=pae_status,
    )


def _normalise_accessions(*, values: Iterable[object]) -> tuple[str, ...]:
    """Return unique canonical accessions in user-selected order."""
    accessions: list[str] = []
    seen: set[str] = set()
    for value in values:
        accession = normalise_uniprot_accession(value=value)
        if accession is None:
            raise AppError(f"Invalid UniProt accession selected: {value}")
        if accession not in seen:
            seen.add(accession)
            accessions.append(accession)
    if not accessions:
        raise AppError("Select at least one HOG member model")
    if len(accessions) > MAX_BUNDLE_MODELS:
        raise AppError(
            f"At most {MAX_BUNDLE_MODELS:,} models can be requested in one bundle"
        )
    return tuple(accessions)


def _retrieve_models_in_order(
    *,
    accessions: tuple[str, ...],
    reader: HttpReader,
    maximum_workers: int,
) -> Iterable[_RetrievedModel]:
    """Yield ordered retrieval results while retaining only a bounded window."""
    worker_count = min(maximum_workers, len(accessions))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        active = {
            index: executor.submit(
                _retrieve_model,
                accession=accession,
                reader=reader,
            )
            for index, accession in enumerate(accessions[:worker_count])
        }
        next_index = worker_count
        for index in range(len(accessions)):
            result = active.pop(index).result()
            if next_index < len(accessions):
                active[next_index] = executor.submit(
                    _retrieve_model,
                    accession=accessions[next_index],
                    reader=reader,
                )
                next_index += 1
            yield result


def _safe_stem(*, value: object) -> str:
    """Return a bounded archive stem containing portable filename characters."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    stem = stem.strip("._-")[:80]
    if not stem:
        raise AppError("A non-empty HOG identifier is required")
    return stem


def _clean_manifest_value(value: object) -> str:
    """Return one TSV-safe audit value."""
    return re.sub(r"[\t\r\n]+", " ", str(value or "")).strip()


def _manifest_bytes(*, hog_id: str, records: tuple[AlphaFoldBundleRecord, ...]) -> bytes:
    """Serialise deterministic bundle provenance as tab-separated text."""
    header = (
        "hog_id",
        "model_index",
        "accession",
        "species",
        "status",
        "model_url",
        "model_bytes",
        "model_sha256",
        "pae_status",
        "pae_url",
        "detail",
    )
    lines = ["\t".join(header)]
    for record in records:
        lines.append(
            "\t".join(
                _clean_manifest_value(value=value)
                for value in (
                    hog_id,
                    record.model_index,
                    record.accession,
                    record.species,
                    record.status,
                    record.model_url,
                    record.model_bytes,
                    record.model_sha256,
                    record.pae_status,
                    record.pae_url,
                    record.detail,
                )
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _readme_bytes(*, hog_id: str) -> bytes:
    """Return the scientific interpretation boundary bundled with the models."""
    document = f"""E3 HOG model bundle: {hog_id}

This archive was prepared for manual upload to the AlphaFold 3 Multi-Model
Inspector. It contains selected single-protein models retrieved from the
AlphaFold Protein Structure Database.

IMPORTANT INTERPRETATION BOUNDARY

- The files represent different protein members of one HOG. They are not
  alternative AlphaFold 3 conformers, seeds or samples of one protein.
- The Inspector's 3D overlay and residue-level pLDDT views can be used for
  exploratory comparison. A PAE panel is available only where the source
  AlphaFold Database record supplied PAE data.
- The residue numbers in separate pLDDT traces are not homologous alignment
  columns. Use the project's recorded sequence and structural alignments for
  residue-equivalence claims.
- AF3-specific pTM, ipTM, ranking-score, contact-probability and chain-pair
  panels are not supplied by this compatibility bundle and must not be
  interpreted as zero-valued evidence.
- Missing models are recorded in manifest.tsv and do not invalidate models
  that were available.

manifest.tsv maps every Inspector model index to its HOG member, source URL,
checksum and retrieval status.
"""
    return document.encode("utf-8")


def build_alphafold_hog_bundle(
    *,
    hog_id: object,
    accessions: Iterable[object],
    species_by_accession: Mapping[str, str] | None = None,
    reader: HttpReader = _read_https,
    maximum_workers: int = MAX_DOWNLOAD_WORKERS,
    maximum_bundle_bytes: int = MAX_BUNDLE_BYTES,
) -> AlphaFoldHogBundle:
    """Build an Inspector-compatible ZIP from available HOG-member models.

    Args:
        hog_id: Selected HOG identifier used in filenames and provenance.
        accessions: User-selected canonical UniProt accessions.
        species_by_accession: Optional exact species labels for the manifest.
        reader: Bounded HTTPS reader, injectable for deterministic tests.
        maximum_workers: Bounded concurrent retrieval limit.
        maximum_bundle_bytes: Maximum uncompressed model and PAE payload total.

    Returns:
        ZIP bytes plus complete per-accession audit records.

    Raises:
        AppError: If the request, limits or identifiers are invalid.
    """
    stem = _safe_stem(value=hog_id)
    canonical = _normalise_accessions(values=accessions)
    if (
        isinstance(maximum_workers, bool)
        or not isinstance(maximum_workers, int)
        or not 1 <= maximum_workers <= MAX_DOWNLOAD_WORKERS
    ):
        raise AppError(
            f"maximum_workers must be between 1 and {MAX_DOWNLOAD_WORKERS}"
        )
    if (
        isinstance(maximum_bundle_bytes, bool)
        or not isinstance(maximum_bundle_bytes, int)
        or maximum_bundle_bytes < 1
        or maximum_bundle_bytes > MAX_BUNDLE_BYTES
    ):
        raise AppError(
            f"maximum_bundle_bytes must be between 1 and {MAX_BUNDLE_BYTES}"
        )
    species_lookup = {
        str(key).upper(): str(value or "").strip()
        for key, value in (species_by_accession or {}).items()
    }
    LOGGER.info(
        "Preparing AlphaFold HOG bundle %s: requested=%d workers=%d",
        stem,
        len(canonical),
        min(maximum_workers, len(canonical)),
    )
    retrieved = _retrieve_models_in_order(
        accessions=canonical,
        reader=reader,
        maximum_workers=maximum_workers,
    )

    output = BytesIO()
    records: list[AlphaFoldBundleRecord] = []
    included_bytes = 0
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for model_index, result in enumerate(retrieved):
            reference = result.reference
            model_url = "" if reference is None else reference.model_url
            pae_url = (
                ""
                if reference is None or reference.pae_url is None
                else reference.pae_url
            )
            status = result.status
            detail = result.detail
            digest = ""
            model_size = 0
            pae_status = result.pae_status
            if status == "available":
                next_bytes = len(result.model) + (
                    0 if result.pae is None else len(result.pae)
                )
                if included_bytes + next_bytes > maximum_bundle_bytes:
                    status = "bundle_limit"
                    pae_status = "not_included"
                    detail = "Model skipped because the bundle size limit was reached"
                else:
                    status = "included"
                    included_bytes += next_bytes
                    model_size = len(result.model)
                    digest = sha256(result.model).hexdigest()
                    prefix = f"e3_{stem}"
                    archive.writestr(
                        f"{prefix}_model_{model_index}.cif",
                        result.model,
                    )
                    if result.pae is not None:
                        archive.writestr(
                            f"{prefix}_full_data_{model_index}.json",
                            result.pae,
                        )
            records.append(
                AlphaFoldBundleRecord(
                    model_index=model_index,
                    accession=result.accession,
                    species=species_lookup.get(result.accession, ""),
                    status=status,
                    model_url=model_url,
                    model_bytes=model_size,
                    model_sha256=digest,
                    pae_status=pae_status,
                    pae_url=pae_url,
                    detail=detail,
                )
            )
        immutable_records = tuple(records)
        archive.writestr(
            "manifest.tsv",
            _manifest_bytes(hog_id=stem, records=immutable_records),
        )
        archive.writestr("README.txt", _readme_bytes(hog_id=stem))

    bundle = AlphaFoldHogBundle(
        payload=output.getvalue(),
        records=tuple(records),
    )
    LOGGER.info(
        "Built AlphaFold HOG bundle %s: requested=%d included=%d pae=%d bytes=%d",
        stem,
        bundle.requested_count,
        bundle.included_count,
        bundle.pae_count,
        len(bundle.payload),
    )
    return bundle
