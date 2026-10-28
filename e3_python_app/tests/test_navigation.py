"""Tests for the maintained scientific application navigation."""

from __future__ import annotations

import pytest

from e3app.errors import AppError
from e3app.navigation import (
    NAVIGATION_STAGES,
    NavigationPage,
    NavigationStage,
    navigation_page,
    navigation_page_titles,
    navigation_stage,
    navigation_stage_labels,
    validate_navigation,
)
from e3app.tab_help import TOP_LEVEL_TAB_HELP


def test_navigation_groups_every_helped_page_once() -> None:
    """Search/results and six ordered stages cover every page exactly once."""
    assert list(navigation_stage_labels()) == [
        "🔎 Search & results",
        "🔵 1 · Information",
        "🟢 2 · Candidate discovery",
        "🟣 3 · E3 orthology context",
        "🟠 4 · Structural prioritisation",
        "🟡 5 · Structural comparison",
        "🔴 6 · Chemistry & outputs",
    ]
    titles = navigation_page_titles()
    assert len(titles) == 30
    assert len(titles) == len(set(titles))
    assert set(titles) == set(TOP_LEVEL_TAB_HELP)
    validate_navigation()


def test_navigation_selects_one_stage_and_page_for_lazy_rendering() -> None:
    """Exact selectors return one maintained page without rendering every page."""
    stage = navigation_stage(label="🟣 3 · E3 orthology context")
    assert "C-terminal conservation" in [page.title for page in stage.pages]
    page = navigation_page(stage=stage, title="C-terminal conservation")
    assert page.method_annotation
    with pytest.raises(AppError, match="Unknown application navigation stage"):
        navigation_stage(label="missing")
    with pytest.raises(AppError, match="Unknown application page"):
        navigation_page(stage=stage, title="missing")


def test_all_results_has_two_explicit_shortcuts_to_the_same_page() -> None:
    """Candidate discovery and search retain the identical complete-results page."""
    discovery = navigation_stage(label="🟢 2 · Candidate discovery")
    search = navigation_stage(label="🔎 Search & results")
    first = navigation_page(stage=discovery, title="All results")
    second = navigation_page(stage=search, title="All results")
    assert first == second
    assert first.shared
    assert navigation_page_titles().count("All results") == 1
    validate_navigation()


def test_external_links_is_one_shared_directory_without_an_extra_stage() -> None:
    """Information and structural prioritisation share the same directory page."""
    information = navigation_stage(label="🔵 1 · Information")
    structural = navigation_stage(label="🟠 4 · Structural prioritisation")
    first = navigation_page(stage=information, title="External links")
    second = navigation_page(stage=structural, title="External links")
    assert first == second
    assert first.shared
    assert not first.method_annotation
    assert navigation_page_titles().count("External links") == 1
    assert len(navigation_stage_labels()) == 7
    validate_navigation()


@pytest.mark.parametrize(
    ("stages", "message"),
    [
        ((), "contains no stages"),
        (
            (NavigationStage(" ", "Description", (NavigationPage("Page"),)),),
            "labels must not be blank",
        ),
        (
            (
                NavigationStage("Stage", "One", (NavigationPage("Page 1"),)),
                NavigationStage("Stage", "Two", (NavigationPage("Page 2"),)),
            ),
            "labels must be unique",
        ),
        (
            (NavigationStage("Stage", " ", (NavigationPage("Page"),)),),
            "descriptions must not be blank",
        ),
        (
            (NavigationStage("Stage", "Description", ()),),
            "must contain a page",
        ),
        (
            (NavigationStage("Stage", "Description", (NavigationPage(" "),)),),
            "page titles must not be blank",
        ),
        (
            (
                NavigationStage(
                    "Stage",
                    "Description",
                    (NavigationPage("Page"), NavigationPage("Page")),
                ),
            ),
            "page titles must be unique",
        ),
    ],
)
def test_invalid_navigation_fails_explicitly(
    stages: tuple[NavigationStage, ...],
    message: str,
) -> None:
    """Empty, blank and duplicate navigation entries cannot render silently."""
    with pytest.raises(AppError, match=message):
        validate_navigation(stages=stages)
