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
    MAX_BUNDLE_BYTES,
    MAX_MODEL_BYTES,
    build_alphafold_hog_bundle,
)
from e3app.errors import AppError
from e3app.exports import safe_file_stem
from e3app.external_hog import prepared_hog_model
from e3app.external_actions import normalise_uniprot_accession
from e3app.protein_imager_pockets import PocketSource, PocketUploadFile, export_recorded_pockets

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
    pocket_files: tuple[PocketUploadFile, ...] = ()
    pocket_audit: tuple[dict, ...] = ()


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
    pocket_source: PocketSource | None = None, original_models: Sequence[bytes] = (),
) -> ProteinImagerPreparation:
    """Download selected full mmCIF models and package files accepted by Protein Imager.

    Args:
        group_id: Explicit HOG/group or individual-protein selection label.
        accessions: Selected canonical UniProt accessions.
        species_by_accession: Published species labels, when available.
        reader: Optional bounded HTTPS reader for deterministic offline testing.
        pocket_source: Original pocket evidence from the selected portable report.
        original_models: Optional original mmCIF bytes, matched by recorded SHA-256.

    Returns:
        Individual complete coordinate files, a ZIP and per-protein retrieval records.
        Unavailable models are recorded; they are never replaced by another accession.

    Raises:
        AppError: If the request, model archive or checksum verification is invalid.
    """
    if pocket_source is not None and pocket_source.group_id != group_id and not (
        len(accessions) == 1 and accessions[0] == group_id
        and normalise_uniprot_accession(value=group_id) == group_id
    ):
        raise AppError("Recorded pocket group does not match the requested group")
    if any(len(model) > MAX_MODEL_BYTES for model in original_models) or sum(
        len(model) for model in original_models
    ) > MAX_BUNDLE_BYTES:
        raise AppError("Original model inputs exceed the permitted size limits")
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
    pockets = export_recorded_pockets(
        source=pocket_source, accessions=accessions,
        models=(*original_models, *(file.data for file in files)),
    ) if pocket_source is not None else None
    if sum(len(file.data) for file in files) + sum(
        len(file.data) for file in (pockets.files if pockets is not None else ())
    ) > MAX_BUNDLE_BYTES:
        raise AppError("Protein Imager upload files exceed the 512 MiB limit")
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
        if pockets is not None:
            for file in pockets.files:
                archive.writestr(f"pockets/{file.filename}", file.data)
            for filename, data in pockets.tables.items():
                archive.writestr(filename, data)
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
            "must be styled manually in Protein Imager. No results are written back to E3.\n\n"
            + (
                "RECORDED POCKETS INCLUDED\n"
                "Use a matching *_protein.cif and its *_rankN_pocketM.cif files from pockets/. "
                "Load these together without separate alignment; they share native coordinates. "
                "Select the pocket as a separate structure and colour it uniformly or show sticks. "
                "pocket_scores.tsv preserves the recorded pocket number, rank and scores; "
                "pocket_residues.tsv lists exact recorded chain/residue IDs, C-alpha positions "
                "and available pLDDT. Scores are supplementary tables and are not read by the "
                "external viewer. Rank one is the primary pocket; other ranks are sensitivity "
                "evidence. Predictions do not establish ligand binding.\n"
                "IMPORTANT: *_CA_only_* files contain only recorded C-alpha atoms, with zero "
                "B factors as placeholders. They show pocket locations but cannot support "
                "side-chain, atomic-surface or cavity-volume inspection. Do not combine them "
                "with an unchecked current model from models/. For atomistic inspection, "
                "supply the exact original prediction mmCIF in the app. Only matching SHA-256 "
                "and original trace coordinates permit an original-model/pocket export. "
                "The app never maps historical pockets onto an unchecked newer model. "
                "pocket_status.tsv and pocket_files.tsv record representation, missing "
                "coordinates, file checksums and the original report checksum. No cavity "
                "spheres, mesh, docking results or automatic project colours are generated.\n"
                if pockets is not None else
                "NO RECORDED POCKET DATA INCLUDED. This package contains current protein "
                "structures only. Load the matching portable pocket review in the app to "
                "prepare recorded pocket inspection files.\n"
            )
        ))
    LOGGER.info(
        "Prepared Protein Imager data group=%s requested=%d included=%d bytes=%d sha256=%s",
        group_id, len(bundle.records), len(files), len(output.getvalue()),
        sha256(output.getvalue()).hexdigest(),
    )
    return ProteinImagerPreparation(
        payload=output.getvalue(), files=files, records=bundle.records,
        pocket_files=pockets.files if pockets is not None else (),
        pocket_audit=pockets.audit if pockets is not None else (),
    )
