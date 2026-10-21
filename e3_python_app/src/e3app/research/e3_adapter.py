"""E3 resource selection adapter; the protein research engine has no E3 assumptions."""

from __future__ import annotations

import re

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError
from e3app.prestructure_hogs import collect_prestructure_ranked_hogs

from .common import ResearchError, bounded_number


def select_e3_inputs(
    *, connection: object, maximum_groups: int = 200, group_ids: tuple[str, ...] = ()
) -> pd.DataFrame:
    """Select exact member accessions and inherited seeds from selected ranked E3 HOGs.

    Args:
        connection: Open immutable E3 resource.
        maximum_groups: Top pre-structure HOG count, used when IDs are not supplied.
        group_ids: Optional exact HOG identifiers replacing the top-N selection.

    Returns:
        Source HOG, rank, raw ID and exact accession context for one-to-many resolution.

    Raises:
        ResearchError: If membership is absent or the complete input exceeds 10,000 IDs.
    """
    maximum = bounded_number(
        value=maximum_groups, label="E3 group count", minimum=1, maximum=1000, integer=True
    )
    try:
        ranked = collect_prestructure_ranked_hogs(
            connection=connection, maximum_hogs=10_000 if group_ids else maximum
        )
    except AppError:
        if not group_ids:
            raise
        ranked = pd.DataFrame(columns=["primary_group_id"])
    groups = list(dict.fromkeys(group_ids or tuple(ranked["primary_group_id"].astype(str))))
    if not groups or len(groups) > 1000:
        raise ResearchError("Select between 1 and 1000 E3 HOGs")
    if "hierarchical_membership" not in list_relations(connection):
        raise ResearchError("E3-to-global linking requires hierarchical_membership")
    columns = set(relation_columns(connection, "hierarchical_membership"))
    if not {"group_id", "raw_identifier"}.issubset(columns):
        raise ResearchError("E3 membership requires group_id and raw_identifier")
    accession = (
        "nullif(trim(CAST(parsed_accession AS VARCHAR)), '')"
        if "parsed_accession" in columns
        else "NULL"
    )
    root = " AND record_type='root_hog'" if "record_type" in columns else ""
    frame = connection.execute(
        "SELECT DISTINCT CAST(group_id AS VARCHAR) AS source_group_id, "
        "CAST(raw_identifier AS VARCHAR) AS raw_identifier, "
        f"coalesce({accession}, CAST(raw_identifier AS VARCHAR)) AS input_id "
        "FROM hierarchical_membership WHERE group_id IN (SELECT unnest(?))"
        + root
        + " ORDER BY source_group_id,input_id LIMIT 10001",
        [groups],
    ).fetchdf()
    rows = frame.to_dict(orient="records")
    seed_columns = [
        column
        for column in ranked
        if "seed" in column and column.endswith(("ids", "ids_calculated"))
    ]
    for record in ranked.to_dict(orient="records"):
        if str(record["primary_group_id"]) not in groups:
            continue
        for column in seed_columns:
            value = record[column]
            if pd.isna(value):
                continue
            for identifier in re.split(r"[;,\s]+", str(value)):
                if identifier and identifier.lower() not in {"none", "nan", "na"}:
                    rows.append(
                        {
                            "source_group_id": str(record["primary_group_id"]),
                            "raw_identifier": identifier,
                            "input_id": identifier,
                        }
                    )
    result = pd.DataFrame(
        rows, columns=("source_group_id", "raw_identifier", "input_id")
    ).drop_duplicates()
    if len(result) > 10_000:
        raise ResearchError(
            "Complete E3 selection exceeds 10000 mapping rows; reduce the group selection"
        )
    if result.empty:
        raise ResearchError("No exact protein identifiers are available for these E3 groups")
    result["source_context"] = "E3_ROOT_HOG_MEMBER_OR_RECORDED_SEED"
    return result


def select_e3_cluster_inputs(
    *, connection: object, maximum_clusters: int = 200, cluster_ids: tuple[str, ...] = ()
) -> pd.DataFrame:
    """Select original representatives and inherited seeds from local discovery clusters.

    Args:
        connection: Immutable E3 resource.
        maximum_clusters: Number of published computationally ranked discovery clusters.
        cluster_ids: Optional exact local cluster IDs replacing the ranked selection.

    Returns:
        Source cluster/rank and exact source-sequence or seed identifiers for global mapping.

    Raises:
        ResearchError: If ranking, discovery evidence or a complete bounded selection is absent.
    """
    maximum = bounded_number(
        value=maximum_clusters, label="E3 cluster count", minimum=1, maximum=1000, integer=True
    )
    relations = set(list_relations(connection))
    selected = dict.fromkeys(cluster_ids)
    if not selected:
        for relation in (
            "candidate_master_results",
            "final_candidate_prioritisation",
            "top_computational_review_shortlist",
            "top_50_computational_review_shortlist",
        ):
            if relation not in relations:
                continue
            columns = set(relation_columns(connection, relation))
            rank = next(
                (
                    name
                    for name in ("computational_rank", "final_rank", "stringent_rank")
                    if name in columns
                ),
                None,
            )
            if "cluster_id" not in columns or rank is None:
                continue
            records = connection.execute(
                "SELECT CAST(cluster_id AS VARCHAR),min(TRY_CAST("
                + quote_identifier(rank)
                + " AS DOUBLE)) AS source_rank FROM "
                + quote_identifier(relation)
                + (
                    " GROUP BY cluster_id HAVING source_rank>0 ORDER BY "
                    "source_rank,cluster_id LIMIT ?"
                ),
                [maximum],
            ).fetchall()
            selected = dict(records)
            break
    if not selected:
        raise ResearchError(
            "Select local cluster IDs or load a published cluster-level computational ranking"
        )
    if "candidate_evidence" not in relations:
        raise ResearchError("Discovery linking requires candidate_evidence with inherited seed IDs")
    columns = set(relation_columns(connection, "candidate_evidence"))
    if not {"representative_id", "matched_seed_ids_calculated"}.issubset(columns):
        raise ResearchError(
            "Discovery linking requires representative_id and matched_seed_ids_calculated"
        )
    original = (
        "representative_original_id"
        if "representative_original_id" in columns
        else "representative_id"
    )
    records = connection.execute(
        "SELECT CAST(representative_id AS VARCHAR) AS local_cluster_id, "
        + quote_identifier(original)
        + " AS source_representative, matched_seed_ids_calculated "
        "FROM candidate_evidence WHERE representative_id IN (SELECT unnest(?)) "
        "ORDER BY representative_id",
        [list(selected)],
    ).fetchdf()
    if set(records["local_cluster_id"]) != set(selected):
        raise ResearchError(
            "Some selected local clusters have no discovery evidence; none were silently omitted"
        )
    rows = []
    for row in records.to_dict(orient="records"):
        for field in ("source_representative", "matched_seed_ids_calculated"):
            if pd.isna(row[field]):
                continue
            for identifier in re.split(r"[;,\s]+", str(row[field])):
                if identifier and identifier.lower() not in {"none", "nan", "na"}:
                    rows.append(
                        {
                            "input_id": identifier,
                            "source_cluster_id": row["local_cluster_id"],
                            "source_rank": selected[row["local_cluster_id"]],
                            "source_context": (
                                "E3_DISCOVERY_REPRESENTATIVE"
                                if field == "source_representative"
                                else "E3_INHERITED_SEED"
                            ),
                        }
                    )
    result = pd.DataFrame(rows).drop_duplicates()
    if result.empty or len(result) > 10_000:
        raise ResearchError("Select a non-empty complete set of at most 10000 source identifiers")
    # Nullable ranks are represented as JSON null rather than NaN in queued context.
    return result.astype(object).where(pd.notna(result), None)
