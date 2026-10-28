"""Prepare full mmCIF files and an auditable HOG ZIP for manual Protein Imager upload."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
import logging
from typing import Mapping, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from e3app.alphafold_hog_bundle import (
    AlphaFoldBundleRecord,
    HttpReader,
    build_alphafold_hog_bundle,
)
from e3app.errors import AppError
from e3app.exports import safe_file_stem
from e3app.external_hog import prepared_hog_model

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProteinImagerFile:
    """One checksum-verified coordinate file, ready for manual upload."""

    accession: str
    filename: str
    data: bytes


@dataclass(frozen=True)
class ProteinImagerPreparation:
    """Prepared upload files, a downloadable ZIP and complete retrieval audit."""

    payload: bytes
    files: tuple[ProteinImagerFile, ...]
    records: tuple[AlphaFoldBundleRecord, ...]


def protein_imager_member_rows(*, rows: pd.DataFrame) -> pd.DataFrame:
    """Adapt exact HOG or portable-review member identifiers without guessing aliases.

    Args:
        rows: Published HOG members or selected-review model/sequence inventory rows.

    Returns:
        Identifier/species columns understood by the existing strict model selector.

    Raises:
        AppError: If non-empty input contains no supported identifier field.
    """
    parsed = next((name for name in (
        "member_parsed_accession", "candidate_accession", "parsed_accession",
    ) if name in rows.columns), None)
    raw = next((name for name in (
        "member_raw_identifier", "raw_identifier", "candidate_accession",
    ) if name in rows.columns), parsed)
    species = next((name for name in (
        "member_species", "species_column", "species",
    ) if name in rows.columns), None)
    if not rows.empty and parsed is None and raw is None:
        raise AppError("Protein Imager preparation needs explicit protein identifiers")
    result = pd.DataFrame(index=rows.index)
    for output, source in (
        ("member_parsed_accession", parsed), ("member_raw_identifier", raw),
        ("member_species", species),
    ):
        result[output] = rows[source].fillna("").astype(str) if source is not None else ""
    return result.reset_index(drop=True)


def prepare_protein_imager_data(
    *, group_id: str, accessions: Sequence[str],
    species_by_accession: Mapping[str, str] | None = None,
    reader: HttpReader | None = None,
) -> ProteinImagerPreparation:
    """Download selected full mmCIF models and package files accepted by Protein Imager.

    Args:
        group_id: Explicit HOG/group or individual-protein selection label.
        accessions: Selected canonical UniProt accessions.
        species_by_accession: Published species labels, when available.
        reader: Optional bounded HTTPS reader for deterministic offline testing.

    Returns:
        Individual complete coordinate files, a ZIP and per-protein retrieval records.
        Unavailable models are recorded; they are never replaced by another accession.

    Raises:
        AppError: If the request, model archive or checksum verification is invalid.
    """
    options = {"reader": reader} if reader is not None else {}
    bundle = build_alphafold_hog_bundle(
        hog_id=group_id, accessions=accessions, species_by_accession=species_by_accession,
        include_pae=False, **options,
    )
    files = tuple(
        ProteinImagerFile(
            accession=record.accession, filename=f"{record.accession}.cif",
            data=prepared_hog_model(bundle=bundle, accession=record.accession),
        ) for record in bundle.records if record.status == "included"
    )
    audit = StringIO(newline="")
    writer = csv.writer(audit, delimiter="\t", lineterminator="\n")
    writer.writerow((
        "group_id", "accession", "species", "status", "upload_file", "model_url",
        "model_bytes", "model_sha256", "detail",
    ))
    for record in bundle.records:
        writer.writerow((
            group_id, record.accession, record.species, record.status,
            f"models/{record.accession}.cif" if record.status == "included" else "",
            record.model_url, record.model_bytes, record.model_sha256, record.detail,
        ))
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for model in files:
            archive.writestr(f"models/{model.filename}", model.data)
        archive.writestr("manifest.tsv", audit.getvalue())
        archive.writestr("README.txt", (
            f"Protein Imager upload files: {safe_file_stem(value=group_id)}\n\n"
            "1. Extract this ZIP.\n"
            "2. Open https://3dproteinimaging.com/protein-imager/\n"
            "3. Use 'Drop here or select structural files' to load one or more .cif files "
            "from models/. The individual app mmCIF downloads can be loaded directly.\n\n"
            "manifest.tsv records each requested accession, species, retrieval status, "
            "source URL and model checksum. Missing models are listed without a substitute.\n"
            "These are full current AlphaFold Database coordinate files. PAE is not required "
            "for this upload and was not requested. Models retain their native coordinates; "
            "the recorded E3 superposition is not applied. For recorded E3 pocket residue IDs, use "
            "the original prediction model; current models can differ. Pocket selections "
            "must be made manually in Protein Imager. No results are written back to E3.\n"
        ))
    LOGGER.info(
        "Prepared Protein Imager data group=%s requested=%d included=%d bytes=%d sha256=%s",
        group_id, len(bundle.records), len(files), len(output.getvalue()),
        sha256(output.getvalue()).hexdigest(),
    )
    return ProteinImagerPreparation(payload=output.getvalue(), files=files, records=bundle.records)
