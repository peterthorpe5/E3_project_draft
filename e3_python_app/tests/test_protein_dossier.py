"""Search-to-HOG resolution and complete, explicitly linked evidence dossiers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from e3app.enriched_hogs import ENRICHED_HOG_OVERVIEW
from e3app.errors import AppError
from e3app.protein_dossier import (
    RECORDED_GROUP_RANKINGS,
    build_group_dossier,
    canonical_group_ranks,
    dossier_inventory,
    group_ranking_query,
    identifier_tokens,
    link_columns,
    linked_relation_query,
    resolve_search_groups,
)
from e3app.result_queries import build_search_queries, preview_query


def test_search_resolves_a_member_and_dossier_follows_cluster_only_evidence(
    resource_db: Path,
) -> None:
    """A member search finds group ranks plus annotations that never store a HOG ID."""
    with duckdb.connect(str(resource_db), read_only=True) as connection:
        direct = build_search_queries(connection=connection, terms=("P38398",), mode="exact")
        groups = resolve_search_groups(connection=connection, queries=direct)
        assert "N0.HOG0001" in groups
        queries = build_group_dossier(connection=connection, group_id="n0.hog0001")
        inventory = dossier_inventory(connection=connection, queries=queries).set_index("source")
        assert inventory.loc["candidate_evidence", "complete_rows"] == 1
        assert inventory.loc["domain_summary", "complete_rows"] == 1
        assert inventory.loc["resource_metadata", "complete_rows"] == 1
        overview = next(query for query in queries if query.name == ENRICHED_HOG_OVERVIEW)
        row = preview_query(connection=connection, query=overview, maximum_rows=1).iloc[0]
        assert row["hog_prestructure_rank"] == 1
        assert row["hog_poststructure_rank"] == 1
        evidence = next(query for query in queries if query.name == "candidate_evidence")
        row = preview_query(connection=connection, query=evidence, maximum_rows=1).iloc[0]
        assert row["raw_member_count"] == 12
        assert "representative_id" in row["_dossier_link_columns"]
        assert row["_dossier_group"] == "n0.hog0001"


def test_dossier_has_no_display_limit_and_does_not_walk_into_unrelated_groups() -> None:
    """Every group member is retained, without recursively traversing a shared protein."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE mapping(group_id VARCHAR, member_accession VARCHAR, cluster_id VARCHAR)"
        )
        connection.execute(
            "INSERT INTO mapping SELECT 'N0.HOG0004891', 'P' || i, 'C1' FROM range(1507) t(i)"
        )
        connection.execute("INSERT INTO mapping VALUES ('N0.HOG9999999', 'P0', 'UNRELATED')")
        connection.execute("CREATE TABLE evidence(cluster_id VARCHAR, hidden_annotation VARCHAR)")
        connection.execute(
            "INSERT INTO evidence VALUES ('C1', 'retain me'), ('UNRELATED', 'exclude me')"
        )
        queries = build_group_dossier(connection=connection, group_id="N0.HOG0004891")
        inventory = dossier_inventory(connection=connection, queries=queries).set_index("source")
        assert inventory.loc["mapping", "complete_rows"] == 1508
        assert inventory.loc["evidence", "complete_rows"] == 1
        # The shared-P0 mapping row remains source context; its other cluster
        # must not expand the dossier to unrelated evidence.
        evidence = next(query for query in queries if query.name == "evidence")
        assert (
            preview_query(connection=connection, query=evidence, maximum_rows=1).iloc[0][
                "hidden_annotation"
            ]
            == "retain me"
        )


def test_schema_tolerant_group_resolution_without_rankings_or_hog_membership() -> None:
    """Generic groups, protein aliases and cluster-only searches work with thin releases."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE aliases(identifier_value VARCHAR, member_accession VARCHAR)"
        )
        connection.execute("INSERT INTO aliases VALUES ('MyProtein', 'ABC1')")
        connection.execute("CREATE TABLE groups(group_id VARCHAR, member_accession VARCHAR)")
        connection.execute("INSERT INTO groups VALUES ('family-alpha', 'ABC1')")
        connection.execute("CREATE TABLE unrelated(score INT)")
        queries = build_search_queries(connection=connection, terms=("MyProtein",))
        assert resolve_search_groups(connection=connection, queries=queries) == ("FAMILY-ALPHA",)
        dossier = build_group_dossier(connection=connection, group_id="FAMILY-ALPHA")
        assert {query.name for query in dossier} == {"aliases", "groups"}
        assert linked_relation_query(connection=connection, relation="unrelated", keys={}) is None
        empty = build_search_queries(connection=connection, terms=("missing",))
        assert resolve_search_groups(connection=connection, queries=empty) == ()
        connection.execute("INSERT INTO groups VALUES ('N0.HOG003', 'ABC1')")
        assert set(resolve_search_groups(connection=connection, queries=queries)) == {
            "FAMILY-ALPHA",
            "N0.HOG003",
        }


def test_link_classification_tokens_and_invalid_group_requests() -> None:
    """Identifier schemas are discovered without mistaking scores for relationship IDs."""
    fields = link_columns(
        columns=(
            "primary_group_id",
            "lead_cluster_id",
            "candidate_accessions",
            "hog_poststructure_rank",
            "custom_hog_id",
            "other_accession",
        )
    )
    assert fields == {
        "group": ("primary_group_id", "custom_hog_id"),
        "cluster": ("lead_cluster_id",),
        "protein": ("candidate_accessions", "other_accession"),
    }
    assert identifier_tokens(value=None, kind="group") == set()
    assert identifier_tokens(value=["hog:N0.HOG0001", "OG2"], kind="group") == {
        "HOG:N0.HOG0001",
        "N0.HOG0001",
        "OG2",
    }
    assert {"Q9SA03", "FB27_ARATH"}.issubset(
        identifier_tokens(
            value="sp|Q9SA03|FB27_ARATH description;OTHER",
            kind="protein",
        )
    )
    with pytest.raises(AppError, match="category"):
        identifier_tokens(value="x", kind="invalid")
    with duckdb.connect(":memory:") as connection:
        for group in ("", " " * 5, "x" * 201, None, "x\x00"):
            with pytest.raises(AppError):
                build_group_dossier(connection=connection, group_id=group)
        with pytest.raises(AppError, match="Unknown dossier"):
            linked_relation_query(connection=connection, relation="missing", keys={})


def test_rank_sources_are_resolved_per_group_and_stage(resource_db: Path) -> None:
    """A thin final shortlist cannot hide ranks in the full earlier source."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "CREATE TABLE final_evolutionary_candidate_prioritisation("
            "primary_group_id VARCHAR, final_evolutionary_rank INT)"
        )
        connection.execute(
            "INSERT INTO final_evolutionary_candidate_prioritisation VALUES ('N0.HOG_OTHER', 1)"
        )
        connection.execute("CREATE TABLE other_scores(hog_id VARCHAR, computational_rank INT)")
        connection.execute("INSERT INTO other_scores VALUES ('N0.HOG0001', 90)")
        dossier = build_group_dossier(connection=connection, group_id="N0.HOG0001")
        query = next(query for query in dossier if query.name == RECORDED_GROUP_RANKINGS)
        ranks = canonical_group_ranks(connection=connection, query=query).set_index("rank_stage")
        assert ranks.loc["Group rank before structural analysis", "recorded_rank"] == "1"
        assert ranks.loc["Group rank after structural analysis", "recorded_rank"] == "1"
        assert set(ranks["source"]) == {"candidate_master_results"}
        recorded = preview_query(connection=connection, query=query, maximum_rows=100)
        assert "Source-specific rank" in set(recorded["rank_stage"])
        assert "90" in set(recorded["recorded_rank"])


def test_typed_group_keys_and_noncanonical_ranks_remain_explicit() -> None:
    """Typed group keys resolve, but a cluster/member rank cannot become a HOG rank."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE custom(evolutionary_group_key VARCHAR, member_rank INT, "
            "description VARCHAR)"
        )
        connection.execute("INSERT INTO custom VALUES ('HOG:N0.HOG0008', 7, 'custom evidence')")
        dossier = build_group_dossier(connection=connection, group_id="N0.HOG0008")
        inventory = dossier_inventory(connection=connection, queries=dossier).set_index("source")
        assert inventory.loc["custom", "complete_rows"] == 1
        query = group_ranking_query(connection=connection, group_id="N0.HOG0008")
        assert canonical_group_ranks(connection=connection, query=query).empty
        assert canonical_group_ranks(connection=connection, query=None).empty
        connection.execute("DROP TABLE custom")
        assert group_ranking_query(connection=connection, group_id="missing") is None


def test_descriptive_only_search_does_not_invent_relationships() -> None:
    """A matching description without identifiers yields no fabricated group."""
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE notes(description VARCHAR)")
        connection.execute("INSERT INTO notes VALUES ('some protein')")
        queries = build_search_queries(connection=connection, terms=("protein",))
        assert resolve_search_groups(connection=connection, queries=queries) == ()
