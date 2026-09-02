"""Maintained scientific navigation for the E3 application."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Sequence

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavigationPage:
    """One existing application page within a scientific stage.

    Attributes:
        title: Exact maintained page title used by help and render registries.
        method_annotation: Whether to show the recorded methods panel.
    """

    title: str
    method_annotation: bool = False


@dataclass(frozen=True)
class NavigationStage:
    """A visually distinct group of related application pages.

    Attributes:
        label: Numbered and colour-marked label displayed in the application.
        description: Plain-language scope of the stage.
        pages: Ordered pages shown within the stage.
    """

    label: str
    description: str
    pages: tuple[NavigationPage, ...]


NAVIGATION_STAGES = (
    NavigationStage(
        label="🔵 1 · Information",
        description=(
            "Release scope, workflow, definitions and the provenance needed "
            "before interpreting scientific results."
        ),
        pages=(
            NavigationPage("Overview"),
            NavigationPage("Workflow schematic", method_annotation=True),
            NavigationPage("Glossary"),
            NavigationPage("Provenance and QC", method_annotation=True),
        ),
    ),
    NavigationStage(
        label="🟢 2 · Candidate discovery",
        description=(
            "Pre-structural E3 evidence, authoritative rankings, expression, "
            "domains and complete candidate-level results."
        ),
        pages=(
            NavigationPage(
                "Computational recommendations",
                method_annotation=True,
            ),
            NavigationPage(
                "Independent structural-review shortlist",
                method_annotation=True,
            ),
            NavigationPage("All results"),
            NavigationPage("Candidates"),
            NavigationPage("E3 seed catalogue"),
            NavigationPage("Domains", method_annotation=True),
            NavigationPage("Expression", method_annotation=True),
            NavigationPage("Threshold explorer", method_annotation=True),
            NavigationPage("Visual explorer"),
        ),
    ),
    NavigationStage(
        label="🟣 3 · E3 orthology context",
        description=(
            "E3-linked OrthoFinder groups and their human, plant and seed "
            "members; membership is evolutionary context, not proof of function."
        ),
        pages=(
            NavigationPage("Orthology", method_annotation=True),
            NavigationPage("Human HOGs"),
            NavigationPage("Plant & human HOGs"),
            NavigationPage("Seed & HOG explorer"),
        ),
    ),
    NavigationStage(
        label="🟠 4 · Structural prioritisation",
        description=(
            "Model, pocket and conservation evidence used to decide which "
            "candidates merit detailed structural comparison."
        ),
        pages=(
            NavigationPage("Ligandability", method_annotation=True),
            NavigationPage("Pocket conservation", method_annotation=True),
        ),
    ),
    NavigationStage(
        label="🟡 5 · Structural comparison",
        description=(
            "Portable plant-only and human-inclusive structures, pockets, "
            "sequence alignments and recorded three-dimensional comparisons."
        ),
        pages=(
            NavigationPage("3D structures & pockets", method_annotation=True),
            NavigationPage("Pocket-aligned sequences", method_annotation=True),
            NavigationPage("3D alignment", method_annotation=True),
            NavigationPage(
                "Human & plant 3D alignment",
                method_annotation=True,
            ),
        ),
    ),
    NavigationStage(
        label="🔴 6 · Chemistry & outputs",
        description=(
            "Structure-guided chemistry evidence and cross-resource search for "
            "review, export and downstream follow-up."
        ),
        pages=(
            NavigationPage("Computational chemistry", method_annotation=True),
            NavigationPage("Search"),
        ),
    ),
)


def navigation_page_titles(
    *, stages: Sequence[NavigationStage] = NAVIGATION_STAGES
) -> tuple[str, ...]:
    """Return all page titles in their maintained display order.

    Args:
        stages: Navigation stages to flatten.

    Returns:
        Ordered page titles.
    """
    return tuple(page.title for stage in stages for page in stage.pages)


def validate_navigation(
    *, stages: Sequence[NavigationStage] = NAVIGATION_STAGES
) -> None:
    """Validate stage labels, descriptions and globally unique page titles.

    Args:
        stages: Navigation stages to validate.

    Raises:
        AppError: If the navigation is empty or contains blank or duplicate
            labels, descriptions or page titles.
    """
    if not stages:
        raise AppError("The application navigation contains no stages")
    stage_labels = [stage.label.strip() for stage in stages]
    if any(not label for label in stage_labels):
        raise AppError("Application navigation stage labels must not be blank")
    if len(stage_labels) != len(set(stage_labels)):
        raise AppError("Application navigation stage labels must be unique")
    if any(not stage.description.strip() for stage in stages):
        raise AppError("Application navigation stage descriptions must not be blank")
    if any(not stage.pages for stage in stages):
        raise AppError("Every application navigation stage must contain a page")
    page_titles = navigation_page_titles(stages=stages)
    if any(not title.strip() for title in page_titles):
        raise AppError("Application navigation page titles must not be blank")
    if len(page_titles) != len(set(page_titles)):
        raise AppError("Application navigation page titles must be unique")
    LOGGER.debug(
        "Validated application navigation stages=%d pages=%d",
        len(stages),
        len(page_titles),
    )
