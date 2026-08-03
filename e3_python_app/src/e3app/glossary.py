"""Plain-language scientific definitions for the ARIA E3 applications.

The glossary is deliberately code-backed so the threshold explorer and the
standalone glossary tab cannot quietly drift apart.  Values describe the
completed top-200 grant-aligned analysis; changing an underlying scientific
rule requires a new workflow run, whereas moving an app slider is an explicitly
labelled sensitivity analysis over recorded values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class GlossaryEntry:
    """One application glossary entry.

    Args:
        section: Broad part of the workflow.
        term: User-facing term or control name.
        definition: Plain-language definition.
        recorded_rule: Exact rule used by the completed analysis, when relevant.
    """

    section: str
    term: str
    definition: str
    recorded_rule: str = ""


SLIDER_HELP: Mapping[str, str] = {
    "target_species_fraction": (
        "The proportion of the 12 configured target plant species represented in the "
        "evolutionary group. The table reports the represented count, total and fraction."
    ),
    "mandatory_species_fraction": (
        "The proportion of the six mandatory crop species represented in the group: barley, "
        "rice, tomato, potato, wheat and maize. The recorded primary analysis required all six."
    ),
    "domain_species_fraction": (
        "Among species for which a group member has usable domain annotation, the proportion "
        "with a catalogued E3-associated domain. Species without usable annotation are reported "
        "as unavailable and are not silently counted as domain-negative."
    ),
    "expression_species_fraction": (
        "Among species whose group member mapped uniquely to an available Expression Atlas gene, "
        "the proportion with broad expression support. Unmapped or unavailable species are "
        "reported separately and are not treated as measured zero expression."
    ),
    "structural_species_fraction": (
        "The proportion of the 12 target species represented by a member contributing to the "
        "conserved pocket-bearing structural component. This is coverage, not a TM-score."
    ),
    "minimum_druggability_score": (
        "The lowest selected-pocket druggability score among assessed members of the group. "
        "Using the minimum makes the gate an all-assessed-members requirement."
    ),
}


GLOSSARY_ENTRIES = (
    GlossaryEntry(
        "Groups and identifiers",
        "Seed",
        "A protein supplied as prior E3 evidence to initiate candidate discovery. A seed is "
        "evidence supporting discovery; it is not automatically a final candidate.",
    ),
    GlossaryEntry(
        "Groups and identifiers",
        "Normalised seed",
        "A seed after identifier cleaning, de-duplication and provenance retention, represented "
        "by the accession used consistently by the workflow.",
    ),
    GlossaryEntry(
        "Groups and identifiers",
        "Non-seed member",
        "An OrthoFinder-group protein that was not in the seed set. It is retained because "
        "orthology places it in the same evolutionary candidate group.",
    ),
    GlossaryEntry(
        "Groups and identifiers",
        "DeepClust cluster",
        "A sequence-similarity discovery cluster. Several DeepClust clusters can contribute to "
        "one evolutionary group, so it is not the final counting unit.",
    ),
    GlossaryEntry(
        "Groups and identifiers",
        "Orthogroup",
        "An OrthoFinder group of genes descended from one gene in the last common ancestor of "
        "the analysed species. It is labelled with an OG identifier.",
    ),
    GlossaryEntry(
        "Groups and identifiers",
        "Hierarchical orthogroup (HOG)",
        "An OrthoFinder evolutionary group defined at a named species-tree node. In the current "
        "resource these commonly have N0.HOG identifiers.",
    ),
    GlossaryEntry(
        "Groups and identifiers",
        "Evolutionary candidate group",
        "The final group-level decision unit after explicit OrthoFinder mapping and deterministic "
        "de-duplication. Headline counts and recommendation decisions should use this unit.",
    ),
    GlossaryEntry(
        "Decision language",
        "Gate",
        "A required yes/no rule applied to a candidate. A candidate passes a combined analysis "
        "only when it satisfies every enabled gate.",
    ),
    GlossaryEntry(
        "Decision language",
        "Gated / gated out",
        "Excluded from the current passing list because at least one enabled gate was not met. "
        "This is a computational prioritisation outcome, not proof of biological inactivity.",
    ),
    GlossaryEntry(
        "Decision language",
        "Strict / stringent",
        "The immutable primary rule set: rank-one selected pockets, every enabled pre-structure "
        "and structural gate, and both structural aligners where 3D support is required.",
    ),
    GlossaryEntry(
        "Decision language",
        "Sensitivity analysis",
        "An exploratory list produced by changing app thresholds or named alternative rules. It "
        "does not replace the recorded strict primary result.",
    ),
    GlossaryEntry(
        "Decision language",
        "Assessed",
        "The necessary data were available and the relevant computational test was performed.",
    ),
    GlossaryEntry(
        "Decision language",
        "Unavailable / not assessed",
        "The necessary evidence was absent or the group was outside the analysed cohort. This "
        "must not be interpreted as a negative biological result.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Minimum target-species fraction",
        SLIDER_HELP["target_species_fraction"],
        "At least 0.90 (90%) of 12 configured target species.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Minimum mandatory-species fraction",
        SLIDER_HELP["mandatory_species_fraction"],
        "1.00: all six mandatory crop species.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Minimum domain-supported assessed-species fraction",
        SLIDER_HELP["domain_species_fraction"],
        "At least 0.80 (80%) of species with usable domain annotation.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Positive expression measurement",
        "A mapped gene-by-condition TPM or FPKM measurement above the configured value. This is "
        "distinct from an unmapped gene or unavailable experiment.",
        "Greater than 0.0 TPM/FPKM in the completed run.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Broad expression support for one mapped gene",
        "The fraction of that gene's available Atlas measurements classified as positive.",
        "At least 0.50 (50%) of measurements were greater than 0.0.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Minimum expression-supported assessed-species fraction",
        SLIDER_HELP["expression_species_fraction"],
        "At least 0.80 (80%) of uniquely mapped, expression-assessed species.",
    ),
    GlossaryEntry(
        "Expression evidence states",
        "NOT_MAPPED",
        "No candidate alias matched an Atlas gene identifier uniquely. Any displayed counts of "
        "zero are placeholders for absent mapped evidence, not measured zero expression.",
    ),
    GlossaryEntry(
        "Expression evidence states",
        "NO_EXPRESSION_RECORDS",
        "A unique gene mapping exists, but the imported Atlas resource contains no expression "
        "measurements for that mapped gene.",
    ),
    GlossaryEntry(
        "Expression evidence states",
        "LIMITED_OR_ZERO_EXPRESSION",
        "Expression was measured, but fewer than half of available measurements exceeded the "
        "recorded positive-expression threshold.",
    ),
    GlossaryEntry(
        "Expression evidence states",
        "BROAD_EXPRESSION_SUPPORTED",
        "Expression was measured and at least half of available measurements exceeded the "
        "recorded positive-expression threshold.",
    ),
    GlossaryEntry(
        "Expression evidence states",
        "Tissue / organism part",
        "The sample's anatomical source as supplied by Atlas metadata, for example leaf or root. "
        "Metadata wording varies among experiments, so the app retains the original label.",
    ),
    GlossaryEntry(
        "Pocket and structural thresholds",
        "Minimum structurally supported species fraction",
        SLIDER_HELP["structural_species_fraction"],
        "At least 0.75 (75%) of the 12 target species.",
    ),
    GlossaryEntry(
        "Pocket and structural thresholds",
        "Minimum member druggability score",
        SLIDER_HELP["minimum_druggability_score"],
        "At least 0.50 for the lowest-scoring assessed member.",
    ),
    GlossaryEntry(
        "Pocket and structural thresholds",
        "Conserved pocket-bearing sequence region",
        "The selected pocket can be mapped to protein-sequence coordinates and the corresponding "
        "region is sufficiently conserved across assessed group members.",
        "Member mapping fraction 0.95; pocket pLDDT fraction 0.70; region overlap 0.25.",
    ),
    GlossaryEntry(
        "Pocket and structural thresholds",
        "Same 3D pocket position supported",
        "After whole-structure superposition, the selected pockets occupy a corresponding spatial "
        "position according to global similarity, centroid distance and pocket overlap.",
        "Minimum TM-score 0.50; centroid distance at most 8 Å; pocket overlap at least 0.50.",
    ),
    GlossaryEntry(
        "Pocket and structural thresholds",
        "Strictly conserved corresponding 3D pocket",
        "The rank-one pocket passes the same-position test and its structurally matched residues "
        "also satisfy residue and chemical-group conservation; group support must reach the "
        "configured fraction and both US-align and TM-align must support the conclusion.",
        "Residue match at least 0.50; chemical-group conservation at least 0.60; group support "
        "at least 0.75; residue matching distance at most 4 Å.",
    ),
    GlossaryEntry(
        "Result labels",
        "PASS",
        "The candidate satisfies every currently selected app gate.",
    ),
    GlossaryEntry(
        "Result labels",
        "NEAR_MISS",
        "The candidate fails exactly one currently selected app gate.",
    ),
    GlossaryEntry(
        "Result labels",
        "FAIL",
        "The candidate fails two or more currently selected app gates.",
    ),
    GlossaryEntry(
        "Result labels",
        "NOT_STRUCTURALLY_ASSESSED",
        "The candidate was outside the 200-group structural cohort or lacks the required "
        "structural result. It is not classified as a structural failure.",
    ),
)


def glossary_sections() -> tuple[str, ...]:
    """Return glossary sections in display order.

    Returns:
        Unique section labels in first-seen order.
    """
    return tuple(dict.fromkeys(entry.section for entry in GLOSSARY_ENTRIES))


def glossary_rows(section: str) -> list[dict[str, str]]:
    """Return serialisable glossary rows for one section.

    Args:
        section: Exact section returned by :func:`glossary_sections`.

    Returns:
        Rows suitable for Streamlit or tab-separated export.

    Raises:
        ValueError: If the requested section is unknown.
    """
    if section not in glossary_sections():
        raise ValueError(f"Unknown glossary section: {section}")
    return [
        {
            "Term": entry.term,
            "Plain-language definition": entry.definition,
            "Recorded top-200 rule": entry.recorded_rule,
        }
        for entry in GLOSSARY_ENTRIES
        if entry.section == section
    ]
