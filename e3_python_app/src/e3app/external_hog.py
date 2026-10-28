"""Exact HOG-member inputs and validated prepared models for external tools."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import logging
import re
from zipfile import BadZipFile, ZipFile

import duckdb
import pandas as pd

from e3app.alphafold_hog_bundle import AlphaFoldHogBundle, MAX_MODEL_BYTES, hog_model_candidates
from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError
from e3app.enriched_hogs import ENRICHED_HOG_OVERVIEW
from e3app.external_actions import selected_pair_fasta_bytes
from e3app.human_hogs import HIERARCHICAL_RELATION, HOG_MEMBERSHIP_REQUIRED_COLUMNS
from e3app.result_queries import build_result_query

LOGGER = logging.getLogger(__name__)
SEQUENCE_RELATION = "candidate_group_member_sequences"


def collect_external_hogs(*, connection: object) -> pd.DataFrame:
    """Collect every published root HOG with members and its recorded ranks.

    Args:
        connection: Open read-only resource connection.

    Returns:
        Complete HOG selection metadata, independent of the screen-preview limit.

    Raises:
        AppError: If the resource query cannot be constructed or executed.
    """
    query = build_result_query(
        connection=connection, result=ENRICHED_HOG_OVERVIEW,
        columns=("hog_id", "hog_prestructure_rank", "hog_poststructure_rank", "hog_member_count"),
    )
    try:
        hogs = connection.execute(query.sql, query.parameters).fetchdf()
    except duckdb.Error as exc:
        raise AppError(f"Could not load HOG choices: {exc}") from exc
    return hogs.loc[pd.to_numeric(hogs["hog_member_count"], errors="coerce") > 0].reset_index(
        drop=True,
    )


def _sequence_lookup(*, connection: object, hog_id: str) -> dict[tuple[str, str], set[str]]:
    """Read distinct sequences from the exact HOG/species/raw-identifier authority.

    Args:
        connection: Read-only source connection.
        hog_id: Exact root HOG whose published sequences are requested.

    Returns:
        Distinct normalised sequence strings per exact species/raw identifier.
    """
    required = {"record_type", "group_id", "species", "raw_identifier", "protein_sequence"}
    if SEQUENCE_RELATION not in list_relations(connection=connection) or not required.issubset(
        relation_columns(connection=connection, relation=SEQUENCE_RELATION)
    ):
        return {}
    rows = connection.execute(
        f"SELECT species, raw_identifier, protein_sequence "
        f"FROM {quote_identifier(SEQUENCE_RELATION)} "
        "WHERE CAST(group_id AS VARCHAR) = ? "
        "AND upper(trim(CAST(record_type AS VARCHAR))) = 'HIERARCHICAL_ORTHOGROUP'",
        [hog_id],
    ).fetchall()
    lookup: dict[tuple[str, str], set[str]] = {}
    for species, identifier, sequence in rows:
        if sequence is not None and str(sequence).strip():
            normalised = re.sub(r"\s+", "", str(sequence)).upper()
            lookup.setdefault((str(species), str(identifier)), set()).add(normalised)
    return lookup


def collect_external_hog_members(
    *, connection: object, hog_id: str, maximum_members: int = 100_000,
) -> pd.DataFrame:
    """Collect one complete HOG's exact members and available sequence inputs.

    Args:
        connection: Open read-only resource connection.
        hog_id: Exact root HOG selected from the loaded resource.
        maximum_members: Defensive interactive cap; excess members cause an error.

    Returns:
        Stable member keys, original identifiers/species, optional canonical accessions
        and exact sequence availability. Conflicting or invalid sequences stay unavailable.

    Raises:
        AppError: If the HOG, membership schema, cap or resource query is invalid.
    """
    if not isinstance(hog_id, str) or not hog_id.strip():
        raise AppError("Select an exact HOG identifier")
    if (
        isinstance(maximum_members, bool) or not isinstance(maximum_members, int)
        or not 1 <= maximum_members <= 100_000
    ):
        raise AppError("Interactive HOG member limit must be between 1 and 100000")
    relations = set(list_relations(connection=connection))
    columns = set(relation_columns(connection=connection, relation=HIERARCHICAL_RELATION)) if (
        HIERARCHICAL_RELATION in relations
    ) else set()
    if not HOG_MEMBERSHIP_REQUIRED_COLUMNS.issubset(columns):
        raise AppError("External HOG selection requires root-level hierarchical membership")
    parsed = "CAST(parsed_accession AS VARCHAR)" if "parsed_accession" in columns else "''"
    try:
        members = connection.execute(
            "SELECT DISTINCT CAST(species AS VARCHAR) AS member_species, "
            "CAST(raw_identifier AS VARCHAR) AS member_raw_identifier, "
            f"{parsed} AS member_parsed_accession "
            f"FROM {quote_identifier(HIERARCHICAL_RELATION)} "
            "WHERE CAST(group_id AS VARCHAR) = ? ORDER BY 1, 2, 3 "
            f"LIMIT {maximum_members + 1}",
            [hog_id],
        ).fetchdf()
        sequences = _sequence_lookup(connection=connection, hog_id=hog_id) if (
            len(members) <= maximum_members
        ) else {}
    except duckdb.Error as exc:
        raise AppError(f"Could not load selected HOG inputs: {exc}") from exc
    if len(members) > maximum_members:
        raise AppError("This HOG exceeds the interactive member limit; use complete exports")
    if members.empty:
        raise AppError(f"No published member records exist for {hog_id}")
    if members[["member_species", "member_raw_identifier"]].isna().any().any():
        raise AppError("HOG members require explicit species and raw identifiers")
    members["member_parsed_accession"] = members["member_parsed_accession"].fillna("")
    if members.duplicated(["member_species", "member_raw_identifier"]).any():
        raise AppError("Conflicting accession mappings exist for a HOG member")
    records = []
    for _, member in members.iterrows():
        species, raw = str(member["member_species"]), str(member["member_raw_identifier"])
        if not species.strip() or not raw.strip():
            raise AppError("HOG members require explicit species and raw identifiers")
        candidates = hog_model_candidates(members=pd.DataFrame([member]))
        canonical = candidates[0].accession if candidates else ""
        identifier = canonical or raw
        key = sha256(repr((species, raw)).encode("utf-8")).hexdigest()
        available = sequences.get((species, raw), set())
        status, sequence = "UNAVAILABLE", ""
        if len(available) > 1:
            status = "CONFLICTING_EXACT_SEQUENCES"
        elif available:
            sequence = next(iter(available))
            status = "AVAILABLE" if re.fullmatch(r"[ABCDEFGHIKLMNPQRSTVWXYZOUJ]+", sequence) else (
                "INVALID_EXACT_SEQUENCE"
            )
            if status != "AVAILABLE":
                sequence = ""
        records.append({
            **member.to_dict(), "member_key": key, "identifier": identifier,
            "canonical_accession": canonical,
            "label": f"{identifier} · {species.replace('_', ' ')} · {raw}",
            "fasta_identifier": re.sub(r"\s+", "_", f"{identifier}|{species}|{key[:12]}"),
            "protein_sequence": sequence, "sequence_status": status,
        })
    LOGGER.info("Loaded external-tool context for HOG %s: members=%d", hog_id, len(records))
    return pd.DataFrame(records)


def external_hog_pair_fasta(
    *, members: pd.DataFrame, first_member_key: str, second_member_key: str,
) -> bytes:
    """Export a selected HOG pair using species-bound exact sequence identities.

    Args:
        members: Exact rows returned by collect_external_hog_members.
        first_member_key: Selected first member's stable key.
        second_member_key: Selected second member's stable key.

    Returns:
        Two-record FASTA with unique descriptive IDs, preserving pair order.

    Raises:
        AppError: If keys are unknown/equal, rows are ambiguous or sequences unavailable.
    """
    required = {
        "member_key", "sequence_status", "identifier", "fasta_identifier", "protein_sequence",
    }
    if not required.issubset(members.columns):
        raise AppError("Selected HOG members are missing exact-sequence fields")
    if first_member_key == second_member_key:
        raise AppError("Select two different HOG members for pair FASTA")
    identifiers = []
    for key in (first_member_key, second_member_key):
        chosen = members.loc[members["member_key"].eq(key)]
        if len(chosen) != 1:
            raise AppError("The selected HOG member is missing or ambiguous")
        row = chosen.iloc[0]
        if row["sequence_status"] != "AVAILABLE":
            raise AppError(
                f"Exact sequence unavailable for {row['identifier']}: {row['sequence_status']}"
            )
        identifiers.append(str(row["fasta_identifier"]))
    source = members.rename(columns={"fasta_identifier": "candidate_accession"})
    return selected_pair_fasta_bytes(
        sources=(source,), reference_accession=identifiers[0], comparison_accession=identifiers[1],
    )


def prepared_hog_model(*, bundle: AlphaFoldHogBundle, accession: str) -> bytes:
    """Read and checksum-verify one included mmCIF from a prepared HOG archive.

    Args:
        bundle: Previously prepared model ZIP and audit records.
        accession: Exact accession of an included model.

    Returns:
        Complete mmCIF bytes suitable for manual Protein Imager loading.

    Raises:
        AppError: If the model is absent, ambiguous, oversized or fails its audit.
    """
    records = [row for row in bundle.records
               if row.accession == accession and row.status == "included"]
    if len(records) != 1:
        raise AppError("Select exactly one included model from the prepared bundle")
    record = records[0]
    try:
        with ZipFile(BytesIO(bundle.payload)) as archive:
            files = [item for item in archive.infolist()
                     if item.filename.endswith(f"_model_{record.model_index}.cif")]
            if len(files) != 1 or not (
                0 < files[0].file_size == record.model_bytes <= MAX_MODEL_BYTES
            ):
                raise AppError("Prepared model file is missing, ambiguous or has an invalid size")
            data = archive.read(files[0])
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise AppError(f"Could not read the prepared model archive: {exc}") from exc
    if sha256(data).hexdigest() != record.model_sha256:
        raise AppError("Prepared model checksum differs from its audit record")
    return data
