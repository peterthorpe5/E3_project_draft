"""Nightingale-ready recorded E3 features without inventing an annotation-sequence match."""

from __future__ import annotations

import logging

import pandas as pd

from e3app.data import list_relations, relation_columns

from .common import ResearchError, bounded_number

LOGGER = logging.getLogger(__name__)


def published_features(*, connection: object, accession: str) -> pd.DataFrame:
    """Retrieve all recorded domain rows for one exact member accession.

    Args:
        connection: Immutable E3 resource.
        accession: Exact published member accession; no alias guessing or remote lookup.

    Returns:
        Complete recorded rows, including their original group/species context.

    Raises:
        ResearchError: If identifiers, domain schema or complete bounds are invalid.
    """
    if not accession.strip() or len(accession) > 1000 or any(ord(c) < 32 for c in accession):
        raise ResearchError("Enter one exact, non-empty published protein accession")
    if "domain_hits" not in list_relations(connection):
        raise ResearchError("This E3 release does not include the recorded domain_hits relation")
    required = {"member_accession", "location_start", "location_end", "protein_length",
                "entry_accession", "entry_name", "primary_group_id", "species_column"}
    if not required.issubset(relation_columns(connection, "domain_hits")):
        raise ResearchError(
            "Recorded domain coordinates or their original protein length are absent")
    frame = connection.execute(
        "SELECT DISTINCT * FROM domain_hits WHERE CAST(member_accession AS VARCHAR)=? LIMIT 100001",
        [accession.strip()],
    ).fetchdf()
    if len(frame) > 100_000:
        raise ResearchError("Complete protein annotation exceeds the 100000-row inspection bound")
    LOGGER.info("Loaded %d recorded E3 feature rows for exact accession %s", len(frame), accession)
    return frame


def recorded_feature_payload(*, rows: pd.DataFrame) -> dict[str, object]:
    """Create a recorded-length coordinate view, without substituting a current sequence.

    Args:
        rows: One exact selected accession, group and species context.

    Returns:
        Nightingale features and their recorded protein length; sequence is intentionally empty.

    Raises:
        ResearchError: If selected contexts, lengths or inclusive positions are inconsistent.
    """
    required = {"member_accession", "location_start", "location_end", "protein_length",
                "entry_accession", "entry_name", "primary_group_id", "species_column"}
    if rows.empty or not required.issubset(rows):
        raise ResearchError("Select recorded domain evidence with its original coordinate context")
    for field in ("member_accession", "primary_group_id", "species_column"):
        if rows[field].astype(str).nunique() != 1:
            raise ResearchError(
                "Choose one exact protein/group/species context for feature inspection")
    lengths = pd.to_numeric(arg=rows["protein_length"], errors="coerce")
    if lengths.isna().any() or lengths.nunique() != 1:
        raise ResearchError("Recorded annotation protein lengths are missing or inconsistent")
    length = bounded_number(value=lengths.iloc[0], label="Recorded protein length", minimum=1,
                            maximum=1_000_000, integer=True)
    features = []
    for row in rows.to_dict(orient="records"):
        start = bounded_number(value=row["location_start"], label="Feature start", minimum=1,
                               maximum=length, integer=True)
        end = bounded_number(value=row["location_end"], label="Feature end", minimum=start,
                             maximum=length, integer=True)
        features.append({
            "accession": str(row["entry_accession"]), "description": str(row["entry_name"]),
            "locations": [{"fragments": [{"start": start, "end": end}]}],
            "color": "#4c5fc3",
        })
    return {
        "sequence": "", "length": length, "features": features,
        "coordinate_scope": "Recorded annotation coordinates; amino-acid sequence not verified",
    }
