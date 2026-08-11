"""Lossless evidence integration for candidate review.

The chemistry package keeps a compact decision table and a lossless, prefixed
review table.  Prefixes prevent similarly named fields from different stages
from silently overwriting one another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from e3chemistry.errors import InputValidationError
from e3chemistry.io_utils import require_columns

INTEGRATED_CORE_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "candidate_accession",
    "species_column",
    "pocket_number",
    "chemistry_review_tier",
    "chemistry_handoff_status",
    "chemistry_handoff_failure_reasons",
)

FIELD_DICTIONARY_FIELDS = (
    "output_field",
    "evidence_layer",
    "source_field",
    "definition",
)

PREFIX_SOURCES = {
    "ranking__": "Stage 08 evolutionary-group ranking",
    "pocket__": "Stage 09 selected-pocket evidence",
    "conservation__": "Stage 09 pocket-conservation summary",
    "chemistry__": "Structure-guided chemistry summary",
    "integrated__": "Stage 10 final integrated evidence",
    "structural__": "Stage 09b structural-alignment summary",
}

CORE_DEFINITIONS = {
    "evolutionary_group_rank": "Ordered Stage 08 evolutionary-group rank.",
    "evolutionary_group_key": "Stable type-prefixed evolutionary-group identity.",
    "primary_group_type": "Authoritative evolutionary-group class.",
    "primary_group_id": "Authoritative evolutionary-group identifier.",
    "cluster_id": "DeepClust cluster supplying the selected representative pocket.",
    "candidate_accession": "Protein accession supplying the selected pocket structure.",
    "species_column": "Species assigned to the selected protein accession.",
    "pocket_number": "FPocket pocket number bound to the candidate manifest.",
    "chemistry_review_tier": "Transparent review tier derived from configured gates.",
    "chemistry_handoff_status": "Configured open-fragment hand-off decision.",
    "chemistry_handoff_failure_reasons": "Semicolon-separated failed gate identifiers.",
}


def _text(value: Any) -> str:
    """Return stripped text for a possibly missing value."""
    return "" if value is None else str(value).strip()


def _group_identity(record: Mapping[str, Any]) -> tuple[str, str]:
    """Return the group type and identifier for one record."""
    return (
        _text(record.get("primary_group_type")),
        _text(record.get("primary_group_id")),
    )


def _cluster_identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return group and cluster identity for one record."""
    group_type, group_id = _group_identity(record)
    return group_type, group_id, _text(record.get("cluster_id"))


def _prefixed(record: Mapping[str, Any] | None, prefix: str) -> dict[str, Any]:
    """Return one record with collision-safe field prefixes."""
    if record is None:
        return {}
    return {f"{prefix}{field}": value for field, value in record.items()}


def _unique_index(
    *,
    records: Sequence[Mapping[str, Any]],
    key_function: Any,
    label: str,
) -> dict[Any, Mapping[str, Any]]:
    """Build a unique index or fail on ambiguous evidence."""
    index: dict[Any, Mapping[str, Any]] = {}
    for record in records:
        key = key_function(record)
        if key in index:
            raise InputValidationError(f"Duplicate {label} identity: {key!r}")
        index[key] = record
    return index


def integrated_fieldnames(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return stable core-first field names for an integrated evidence table."""
    observed = {str(field) for record in records for field in record}
    remaining = sorted(observed.difference(INTEGRATED_CORE_FIELDS))
    return INTEGRATED_CORE_FIELDS + tuple(remaining)


def build_integrated_evidence(
    *,
    group_ranking: Sequence[Mapping[str, Any]],
    selected_pockets: Sequence[Mapping[str, Any]],
    conservation: Sequence[Mapping[str, Any]],
    targets: Sequence[Mapping[str, Any]],
    group_summaries: Sequence[Mapping[str, Any]],
    integrated_evidence: Sequence[Mapping[str, Any]] = (),
    structural_alignment: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Join all evidence layers without dropping source fields.

    Args:
        group_ranking: Stage 08 evolutionary-group rows.
        selected_pockets: Stage 09 strict selected-pocket rows.
        conservation: Stage 09 pocket-conservation rows.
        targets: Checksum-bound chemistry target rows.
        group_summaries: Chemistry result rows.
        integrated_evidence: Optional Stage 10 final integrated rows.
        structural_alignment: Optional Stage 09b group summary rows.

    Returns:
        One core-first, lossless prefixed evidence row per chemistry target.

    Raises:
        InputValidationError: If an authoritative identity is duplicated or a
            required chemistry join cannot be resolved.
    """
    require_columns(
        records=group_ranking,
        required=(
            "evolutionary_group_key",
            "primary_group_type",
            "primary_group_id",
        ),
        label="evolutionary-group ranking",
    )
    require_columns(
        records=targets,
        required=(
            "evolutionary_group_key",
            "primary_group_type",
            "primary_group_id",
            "cluster_id",
            "candidate_accession",
            "pocket_number",
        ),
        label="chemistry targets",
    )
    ranking_by_key = _unique_index(
        records=group_ranking,
        key_function=lambda row: _text(row.get("evolutionary_group_key")),
        label="evolutionary-group ranking",
    )
    summary_by_key = _unique_index(
        records=group_summaries,
        key_function=lambda row: _text(row.get("evolutionary_group_key")),
        label="chemistry summary",
    )
    pocket_by_key = _unique_index(
        records=selected_pockets,
        key_function=lambda row: (
            *_cluster_identity(row),
            _text(row.get("candidate_accession")).upper(),
            int(row.get("pocket_number")),
        ),
        label="selected pocket",
    )
    conservation_by_key = _unique_index(
        records=conservation,
        key_function=_cluster_identity,
        label="pocket conservation",
    )
    integrated_by_group = _unique_index(
        records=integrated_evidence,
        key_function=_group_identity,
        label="final integrated evidence",
    )
    structural_by_cluster = _unique_index(
        records=structural_alignment,
        key_function=_cluster_identity,
        label="structural alignment",
    )
    rows: list[dict[str, Any]] = []
    for target in targets:
        group_key = _text(target.get("evolutionary_group_key"))
        ranking = ranking_by_key.get(group_key)
        summary = summary_by_key.get(group_key)
        if ranking is None or summary is None:
            raise InputValidationError(
                f"Could not join required evidence for {group_key}"
            )
        cluster_key = _cluster_identity(target)
        pocket_key = (
            *cluster_key,
            _text(target.get("candidate_accession")).upper(),
            int(target.get("pocket_number")),
        )
        pocket = pocket_by_key.get(pocket_key)
        if pocket is None:
            raise InputValidationError(
                "Could not join selected pocket for "
                f"{group_key}/{pocket_key[-2]}/{pocket_key[-1]}"
            )
        core = {
            "evolutionary_group_rank": target.get("evolutionary_group_rank"),
            "evolutionary_group_key": group_key,
            "primary_group_type": target.get("primary_group_type"),
            "primary_group_id": target.get("primary_group_id"),
            "cluster_id": target.get("cluster_id"),
            "candidate_accession": target.get("candidate_accession"),
            "species_column": target.get("species_column"),
            "pocket_number": target.get("pocket_number"),
            "chemistry_review_tier": summary.get("chemistry_review_tier"),
            "chemistry_handoff_status": summary.get("chemistry_handoff_status"),
            "chemistry_handoff_failure_reasons": summary.get(
                "chemistry_handoff_failure_reasons"
            ),
        }
        group_identity = _group_identity(target)
        rows.append(
            {
                **core,
                **_prefixed(ranking, "ranking__"),
                **_prefixed(pocket, "pocket__"),
                **_prefixed(
                    conservation_by_key.get(cluster_key), "conservation__"
                ),
                **_prefixed(summary, "chemistry__"),
                **_prefixed(
                    integrated_by_group.get(group_identity), "integrated__"
                ),
                **_prefixed(
                    structural_by_cluster.get(cluster_key), "structural__"
                ),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            int(row["evolutionary_group_rank"]),
            str(row["evolutionary_group_key"]),
        ),
    )


def build_field_dictionary(
    *, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    """Describe every field in the lossless integrated evidence table."""
    rows: list[dict[str, str]] = []
    for field in integrated_fieldnames(records):
        if field in CORE_DEFINITIONS:
            layer = "Integrated review identity/decision"
            source_field = field
            definition = CORE_DEFINITIONS[field]
        else:
            prefix = next(
                (value for value in PREFIX_SOURCES if field.startswith(value)),
                "",
            )
            layer = PREFIX_SOURCES.get(prefix, "Integrated evidence")
            source_field = field[len(prefix):] if prefix else field
            definition = (
                f"Copied without transformation from {layer}: {source_field}."
            )
        rows.append(
            {
                "output_field": field,
                "evidence_layer": layer,
                "source_field": source_field,
                "definition": definition,
            }
        )
    return rows
