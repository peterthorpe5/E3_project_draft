"""Presentation-safe helpers for ranking members within one HOG."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import pandas as pd

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

WITHIN_HOG_DEFAULT_COLUMNS = (
    "hog_id",
    "hog_prestructure_rank",
    "hog_poststructure_rank",
    "member_structural_readiness_rank",
    "member_structural_readiness_status",
    "member_species",
    "member_parsed_accession",
    "member_parsed_entry",
    "member_raw_identifier",
    "member_structure_assessed",
    "member_druggability_score",
    "member_pocket_mapping_fraction",
    "member_pocket_plddt_fraction",
    "member_predictor_agreement",
    "member_pocket_component_selected",
    "member_structural_evidence_status",
)

WITHIN_HOG_ORDERING = (
    ("1", "Joined selected-pocket structural evidence", "assessed before unassessed"),
    ("2", "Member druggability score", "higher first; missing last"),
    ("3", "Pocket residue-mapping fraction", "higher first; missing last"),
    ("4", "Pocket pLDDT fraction", "higher first; missing last"),
    ("5", "Pocket-predictor agreement", "higher first; missing last"),
    ("6", "Species and raw member identifier", "stable alphabetical tie-break"),
)


@dataclass(frozen=True)
class WithinHogSummary:
    """Summary of one selected HOG's member-review ordering.

    Attributes:
        hog_id: Selected root HOG identifier.
        member_count: Number of member records in the result.
        structurally_assessed_count: Members with joined pocket evidence.
        unassessed_count: Members without joined pocket evidence.
        first_member: Identifier for the first member in the review order.
        first_member_status: Evidence status for that first member.
    """

    hog_id: str
    member_count: int
    structurally_assessed_count: int
    unassessed_count: int
    first_member: str
    first_member_status: str


def within_hog_choice_labels(*, hogs: pd.DataFrame) -> dict[str, str]:
    """Create searchable HOG labels with both authoritative HOG ranks.

    Args:
        hogs: One-row-per-HOG overview containing ``hog_id`` and optional rank
            and member-count fields.

    Returns:
        HOG IDs mapped to readable selection labels in input order.

    Raises:
        AppError: If identifiers are absent, blank or duplicated.
    """
    if "hog_id" not in hogs.columns:
        raise AppError("Within-HOG choices require a hog_id column")
    identifiers = hogs["hog_id"].fillna("").astype(str).str.strip()
    if identifiers.eq("").any():
        raise AppError("Within-HOG choices contain a blank HOG identifier")
    if identifiers.duplicated().any():
        raise AppError("Within-HOG choices contain duplicate HOG identifiers")

    labels: dict[str, str] = {}
    for row_index, hog_id in identifiers.items():
        parts = [hog_id]
        for column, label in (
            ("hog_prestructure_rank", "pre-structure rank"),
            ("hog_poststructure_rank", "post-structure rank"),
            ("hog_member_count", "members"),
        ):
            if column not in hogs.columns:
                continue
            value = pd.to_numeric(
                pd.Series([hogs.at[row_index, column]]),
                errors="coerce",
            ).iloc[0]
            if pd.notna(value):
                parts.append(f"{label} {int(value):,}")
        labels[hog_id] = " · ".join(parts)
    LOGGER.debug("Prepared %d within-HOG selector labels", len(labels))
    return labels


def summarise_within_hog_members(*, members: pd.DataFrame) -> WithinHogSummary:
    """Summarise one HOG without converting missing evidence to zero.

    Args:
        members: Ranked enriched member rows for exactly one HOG.

    Returns:
        Counts and the first member in the recorded review ordering.

    Raises:
        AppError: If required fields are absent or several HOGs are mixed.
    """
    required = {
        "hog_id",
        "member_raw_identifier",
        "member_structural_readiness_rank",
        "member_structural_readiness_status",
        "member_structure_assessed",
    }
    missing = sorted(required.difference(members.columns))
    if missing:
        raise AppError(
            "Within-HOG member summary is missing columns: " + ", ".join(missing)
        )
    records = members.loc[
        members["member_raw_identifier"].notna()
        & members["member_raw_identifier"].astype(str).str.strip().ne("")
    ].copy()
    if records.empty:
        return WithinHogSummary("", 0, 0, 0, "Unavailable", "NO_MEMBER_RECORD")
    hog_ids = sorted(records["hog_id"].dropna().astype(str).str.strip().unique())
    if len(hog_ids) != 1 or not hog_ids[0]:
        raise AppError("Within-HOG member summary requires exactly one HOG")
    assessed = records["member_structure_assessed"].map(
        lambda value: value is True
        or str(value).strip().casefold() in {"true", "1", "yes"}
    )
    ranks = pd.to_numeric(
        records["member_structural_readiness_rank"],
        errors="coerce",
    )
    if ranks.isna().all():
        raise AppError("Within-HOG member rows contain no usable readiness rank")
    first = records.loc[ranks.idxmin()]
    identifier = next(
        (
            str(first[column]).strip()
            for column in (
                "member_parsed_accession",
                "member_parsed_entry",
                "member_raw_identifier",
            )
            if column in records.columns
            and pd.notna(first[column])
            and str(first[column]).strip()
        ),
        "Unavailable",
    )
    status_value = first["member_structural_readiness_status"]
    first_status = (
        str(status_value).strip()
        if pd.notna(status_value) and str(status_value).strip()
        else "Unavailable"
    )
    summary = WithinHogSummary(
        hog_id=hog_ids[0],
        member_count=len(records),
        structurally_assessed_count=int(assessed.sum()),
        unassessed_count=int((~assessed).sum()),
        first_member=identifier,
        first_member_status=first_status,
    )
    LOGGER.info(
        "Summarised within-HOG ranking hog=%s members=%d assessed=%d",
        summary.hog_id,
        summary.member_count,
        summary.structurally_assessed_count,
    )
    return summary
