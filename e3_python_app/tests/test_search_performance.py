"""Structural performance regressions without machine-dependent timing thresholds."""

from pathlib import Path

import duckdb
import pytest

from e3app.enriched_hogs import ENRICHED_HOG_MEMBERS, ENRICHED_HOG_OVERVIEW
from e3app.protein_dossier import linked_relation_query
from e3app.result_queries import build_result_query, preview_query, query_count
from test_resource_browser import _open_page, _submit_search


def test_exact_hog_initial_render_does_not_build_or_count_full_dossiers(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete HOG ID opens ranks/members without broad scans or graph expansion."""

    def blocked(**kwargs: object) -> object:
        """Fail if the initial exact lookup invokes a deferred expensive operation."""
        raise AssertionError("An exact HOG lookup must not invoke a full-resource operation")

    monkeypatch.setattr("e3app.resource_browser.build_search_queries", blocked)
    monkeypatch.setattr("e3app.resource_browser.resolve_search_groups", blocked)
    monkeypatch.setattr("e3app.resource_browser.build_group_dossier", blocked)
    monkeypatch.setattr("e3app.resource_browser.dossier_inventory", blocked)
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="Protein & HOG search")
    app = _submit_search(app=app, text=" n0.hog0001 ")
    assert not app.exception
    assert app.selectbox(key="search_dossier_group").value == "N0.HOG0001"
    assert any(
        metric.label == "Rank after structural analysis" and metric.value == "1"
        for metric in app.metric
    )
    assert app.button(key="group_dossier_load")
    assert "group_dossier_complete_prepare" not in [button.key for button in app.button]
    assert app.button(key="search_direct_load")
    app.run()
    assert not app.exception
    assert any("Lookup completed in" in item.value for item in app.caption)


def test_dossier_build_and_inventory_are_reused_on_widget_changes(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting source previews or download formats cannot re-expand the evidence graph."""
    from e3app import resource_browser

    original_build = resource_browser.build_group_dossier
    original_inventory = resource_browser.dossier_inventory
    calls = {"build": 0, "inventory": 0}

    def tracked_build(**kwargs: object) -> object:
        """Count complete graph builds while retaining the real source behaviour."""
        calls["build"] += 1
        return original_build(**kwargs)

    def tracked_inventory(**kwargs: object) -> object:
        """Count complete inventory scans while retaining their actual result."""
        calls["inventory"] += 1
        return original_inventory(**kwargs)

    monkeypatch.setattr(resource_browser, "build_group_dossier", tracked_build)
    monkeypatch.setattr(resource_browser, "dossier_inventory", tracked_inventory)
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="Protein & HOG search")
    app = _submit_search(app=app, text="N0.HOG0001")
    assert calls == {"build": 0, "inventory": 0}
    app.button(key="group_dossier_load").click().run()
    assert not app.exception
    assert calls == {"build": 1, "inventory": 1}
    app.selectbox(key="dossier_source").set_value("candidate_evidence").run()
    app.radio(key="group_dossier_complete_format").set_value("excel").run()
    app.radio(key="group_dossier_complete_format").set_value("tsv").run()
    app.button(key="group_dossier_complete_prepare").click().run()
    assert not app.exception
    assert calls == {"build": 1, "inventory": 1}
    assert app.session_state["group_dossier_complete_prepared"][1].startswith(b"PK")
    app.button(key="search_direct_load").click().run()
    app.button(key="search_direct_complete_prepare").click().run()
    assert not app.exception
    assert app.session_state["search_direct_complete_prepared"][1].startswith(b"PK")
    assert calls == {"build": 1, "inventory": 1}


def test_complete_all_results_download_is_accessible_from_both_sections(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The restored discovery entry and search shortcut expose identical full exports."""
    from e3app import resource_browser

    counts = {"count": 0, "preview": 0}
    original_count, original_preview = resource_browser.query_count, resource_browser.preview_query

    def tracked_count(**kwargs: object) -> int:
        """Record complete-result counting without changing its result."""
        counts["count"] += 1
        return original_count(**kwargs)

    def tracked_preview(**kwargs: object) -> object:
        """Record bounded preview collection without changing its rows."""
        counts["preview"] += 1
        return original_preview(**kwargs)

    monkeypatch.setattr(resource_browser, "query_count", tracked_count)
    monkeypatch.setattr(resource_browser, "preview_query", tracked_preview)
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="All results")
    assert app.selectbox(key="all_results_relation").value == "candidate_master_results"
    first_counts = dict(counts)
    app.button(key="all_results_complete_prepare").click().run()
    assert any(
        button.label == "Download all results (TSV ZIP)" for button in app.get("download_button")
    )
    assert counts == first_counts
    payload = app.session_state["all_results_complete_prepared"][1]
    app.radio(key="e3_navigation_stage").set_value("🟢 2 · Candidate discovery").run()
    app.radio(key="e3_navigation_page_🟢 2 · Candidate discovery").set_value("All results").run()
    assert not app.exception
    app.button(key="all_results_complete_prepare").click().run()
    assert counts == first_counts
    assert app.session_state["all_results_complete_prepared"][1].startswith(b"PK")
    assert payload.startswith(b"PK")


def test_joined_download_does_not_require_eager_preview_or_counting(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full joined export remains available even when its preview is explicitly deferred."""
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="All results")
    app.selectbox(key="all_results_relation").set_value(ENRICHED_HOG_OVERVIEW).run()
    assert any(
        metric.label == "Complete matching rows" and metric.value == "On request"
        for metric in app.metric
    )
    assert not app.checkbox(key="all_results_joined_preview").value
    app.button(key="all_results_complete_prepare").click().run()
    assert not app.exception
    assert app.session_state["all_results_complete_prepared"][1].startswith(b"PK")
    app.checkbox(key="all_results_joined_preview").check().run()
    assert not app.exception
    assert any(
        metric.label == "Complete matching rows" and metric.value == "1" for metric in app.metric
    )


def test_hog_scope_precedes_membership_aggregation_and_preserves_rank_values(
    resource_db: Path,
) -> None:
    """Scoped joined queries retain all members and ranks without processing other HOGs."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES ('N0.HOG0002', 'Homo_sapiens', 'other')"
        )
        for result in (ENRICHED_HOG_OVERVIEW, ENRICHED_HOG_MEMBERS):
            full = build_result_query(connection=connection, result=result)
            scoped = build_result_query(
                connection=connection, result=result, hog_ids=("N0.HOG0001",)
            )
            full_frame = preview_query(connection=connection, query=full, maximum_rows=10)
            scoped_frame = preview_query(connection=connection, query=scoped, maximum_rows=10)
            selected = full_frame.loc[full_frame["hog_id"] == "N0.HOG0001"]
            assert len(scoped_frame) == len(selected)
            assert set(scoped_frame["hog_poststructure_rank"]) == set(
                selected["hog_poststructure_rank"]
            )
            assert set(scoped_frame["hog_prestructure_rank"]) == set(
                selected["hog_prestructure_rank"]
            )
            assert 'AND upper(trim(CAST("group_id" AS VARCHAR)))' in scoped.sql


def test_identifier_key_matching_has_no_row_by_key_nested_loop_join() -> None:
    """Large member-ID sets use vector/list predicates rather than correlated key scans."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE evidence AS SELECT 'P' || i AS member_accession FROM range(2000) t(i)"
        )
        query = linked_relation_query(
            connection=connection,
            relation="evidence",
            keys={"protein": {f"P{i}" for i in range(1507)}},
        )
        assert "unnest" not in query.sql.lower()
        assert query_count(connection=connection, query=query) == 1507
        plan = connection.execute("EXPLAIN " + query.sql, query.parameters).fetchone()[1]
        assert "BLOCKWISE_NL_JOIN" not in plan


def test_legacy_search_state_is_discarded_on_live_code_reload(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-hotfix Streamlit session cannot crash on the new cached-state fields."""
    from e3app.config import config_from_environment
    from e3app.resource_browser import source_identity

    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="Protein & HOG search")
    app.session_state["complete_resource_search"] = {
        "source": source_identity(config=config_from_environment()),
        "terms": ("N0.HOG0001",),
    }
    app.run()
    assert not app.exception
    assert "complete_resource_search" not in app.session_state


def test_missing_hog_reports_completion_and_wider_search_can_find_text_references(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-match lookup gives explicit feedback rather than appearing unresponsive."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute("CREATE TABLE notes(description VARCHAR)")
        connection.execute("INSERT INTO notes VALUES ('Reference to N0.HOG9999999 in a note')")
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="Protein & HOG search")
    app = _submit_search(app=app, text="N0.HOG9999999 ")
    assert not app.exception
    assert any("No recorded group found" in item.value for item in app.warning)
    assert any("Lookup completed in" in item.value for item in app.caption)
    app.checkbox(key="search_wider_fields").check()
    app = _submit_search(app=app, text="N0.HOG9999999")
    assert not app.exception
    assert app.session_state["complete_resource_search"]["group_only"] is False
    assert set(app.session_state["complete_resource_search"]["summary"]["relation"]) == {"notes"}
