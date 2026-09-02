"""Tests for the maintained scientific application navigation."""

from __future__ import annotations

import pytest

from e3app.errors import AppError
from e3app.navigation import (
    NAVIGATION_STAGES,
    NavigationPage,
    NavigationStage,
    navigation_page_titles,
    validate_navigation,
)
from e3app.tab_help import TOP_LEVEL_TAB_HELP


def test_navigation_groups_every_helped_page_once() -> None:
    """Six ordered stages cover every maintained top-level page exactly once."""
    assert [stage.label for stage in NAVIGATION_STAGES] == [
        "🔵 1 · Information",
        "🟢 2 · Candidate discovery",
        "🟣 3 · E3 orthology context",
        "🟠 4 · Structural prioritisation",
        "🟡 5 · Structural comparison",
        "🔴 6 · Chemistry & outputs",
    ]
    titles = navigation_page_titles()
    assert len(titles) == 25
    assert len(titles) == len(set(titles))
    assert set(titles) == set(TOP_LEVEL_TAB_HELP)
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
