"""Plain-language scientific definitions for the ARIA E3 applications.

The glossary is deliberately code-backed so the threshold explorer and the
standalone glossary tab cannot quietly drift apart.  Values describe the
completed top-200 grant-aligned analysis; changing an underlying scientific
rule requires a new workflow run, whereas moving an app slider is an explicitly
labelled sensitivity analysis over recorded values.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from importlib.resources import files
import re
from typing import Mapping, Sequence


@dataclass(frozen=True)
class GlossaryEntry:
    """One application glossary entry.

    Args:
        section: Broad part of the workflow.
        term: User-facing term or control name.
        definition: Plain-language definition.
        recorded_rule: Exact rule used by the completed analysis, when relevant.
        type_or_unit: Field or term data type and unit, when relevant.
        interpretation_or_caution: Important interpretation boundary.
        source: Project document or application rule supplying the definition.
    """

    section: str
    term: str
    definition: str
    recorded_rule: str = ""
    type_or_unit: str = ""
    interpretation_or_caution: str = ""
    source: str = "Application computational rules"


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


_CORE_GLOSSARY_ENTRIES = (
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
        "Context-positive expression",
        "A mapped gene-by-Atlas-group context whose median expression meets the configured "
        "threshold. Each Atlas matrix cell is a five-number summary (minimum, lower quartile, "
        "median, upper quartile and maximum); it is not a list of biological replicates.",
        "Median TPM at least 0.5. FPKM is used only when an experiment has no TPM matrix.",
    ),
    GlossaryEntry(
        "Pre-structure thresholds",
        "Broad expression support for one mapped gene",
        "The fraction of that gene's imported Atlas group contexts classified as "
        "context-positive after selecting one unit per experiment.",
        "At least 0.50 (50%) of available contexts had median TPM at least 0.5.",
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
        "Expression was measured, but fewer than half of available Atlas group contexts met the "
        "recorded median-expression threshold.",
    ),
    GlossaryEntry(
        "Expression evidence states",
        "BROAD_EXPRESSION_SUPPORTED",
        "Expression was measured and at least half of available Atlas group contexts met the "
        "recorded median-expression threshold.",
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


def _load_resource_entries(
    *,
    file_name: str,
    source: str,
) -> tuple[GlossaryEntry, ...]:
    """Load validated glossary rows bundled with the application.

    Args:
        file_name: Resource TSV basename under ``e3app/resources``.
        source: User-facing source label applied to every imported row.

    Returns:
        Ordered immutable glossary entries.

    Raises:
        ValueError: If the file schema or a required cell is invalid.
    """
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("A non-empty glossary resource filename is required.")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A non-empty glossary source label is required.")
    required = (
        "field",
        "category",
        "type_or_unit",
        "definition",
        "interpretation_or_caution",
    )
    resource = files("e3app").joinpath("resources", file_name)
    with resource.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != required:
            raise ValueError(
                f"Glossary resource {file_name} has an invalid column schema."
            )
        entries = []
        for row_number, row in enumerate(reader, start=2):
            if any(not str(row[column]).strip() for column in required):
                raise ValueError(
                    f"Glossary resource {file_name} has an empty required "
                    f"value on row {row_number}."
                )
            entries.append(
                GlossaryEntry(
                    section=str(row["category"]).strip(),
                    term=str(row["field"]).strip(),
                    definition=str(row["definition"]).strip(),
                    type_or_unit=str(row["type_or_unit"]).strip(),
                    interpretation_or_caution=str(
                        row["interpretation_or_caution"]
                    ).strip(),
                    source=source.strip(),
                )
            )
    if not entries:
        raise ValueError(f"Glossary resource {file_name} contains no terms.")
    return tuple(entries)


GLOSSARY_ENTRIES = (
    *_CORE_GLOSSARY_ENTRIES,
    *_load_resource_entries(
        file_name="project_term_glossary.tsv",
        source="Milestone 1 and Milestone 2 technical guides",
    ),
    *_load_resource_entries(
        file_name="final_candidate_field_dictionary.tsv",
        source="Final candidate field dictionary v1.0",
    ),
)

_TYPE_OR_UNIT_PATTERNS = (
    (re.compile(r"(^|_)(fraction|proportion|identity|overlap)(_|$)"), "Fraction (0-1)"),
    (re.compile(r"(^|_)score($|_)"), "Numeric score; consult the named method"),
    (re.compile(r"(^|_)(count|number|rank|length|position|index)($|_)"), "Integer"),
    (
        re.compile(r"(^|_)(pass|supported|available|is_[a-z0-9_]+)($|_)"),
        "Boolean or categorical status",
    ),
    (re.compile(r"(^|_)(date|time|timestamp)($|_)"), "Date/time"),
    (re.compile(r"(^|_)(id|identifier|accession|entry)($|_)"), "Identifier/text"),
)


def _humanise_column_name(column_name: str) -> str:
    """Return a readable phrase for one machine-facing field name."""
    return " ".join(column_name.replace("_", " ").split())


def _inferred_column_definition(column_name: str) -> tuple[str, str]:
    """Return a transparent fallback definition and interpretation."""
    phrase = _humanise_column_name(column_name)
    lower = column_name.lower()
    if lower.endswith("_count"):
        definition = f"Number of records, members or events represented by {phrase}."
    elif lower.endswith("_fraction") or lower.endswith("_proportion"):
        definition = f"Proportion represented by {phrase}, normally reported from 0 to 1."
    elif lower.endswith("_score"):
        definition = f"Recorded numerical value for {phrase}."
    elif lower.endswith("_rank"):
        definition = (
            f"Ordered position for {phrase}; lower values normally indicate "
            "earlier priority."
        )
    elif lower.endswith("_status"):
        definition = f"Controlled categorical result for {phrase}."
    elif lower.startswith("is_") or lower.endswith("_pass"):
        definition = f"Indicator recording whether {phrase} is true or satisfied."
    elif lower.endswith("_id") or lower.endswith("_identifier"):
        definition = f"Identifier used for {phrase}."
    elif lower.endswith("_accessions"):
        definition = f"Semicolon-delimited protein accessions recorded for {phrase}."
    elif lower.endswith("_accession"):
        definition = f"Protein or source-record accession used for {phrase}."
    elif lower.endswith("_path"):
        definition = f"Recorded file or resource location for {phrase}."
    elif lower.endswith("_sha256"):
        definition = f"SHA-256 checksum used to verify the byte identity of {phrase}."
    elif lower.endswith("_reason"):
        definition = f"Recorded explanation for {phrase}."
    elif lower.endswith("_interpretation"):
        definition = f"Plain-language interpretation supplied for {phrase}."
    else:
        definition = f"Source field reporting {phrase}."
    caution = (
        "This definition is generated from the exported header because no exact curated "
        "field entry was present. Interpret it with the source relation and methods annotation."
    )
    return definition, caution


def _inferred_type_or_unit(column_name: str, declared_type: str = "") -> str:
    """Infer a conservative type or unit from schema and field-name evidence."""
    if declared_type.strip():
        return declared_type.strip()
    lower = column_name.lower()
    for pattern, label in _TYPE_OR_UNIT_PATTERNS:
        if pattern.search(lower):
            return label
    return "Text or source-declared value"


def column_definition_row(
    *, column_name: str, declared_type: str = "", relations: Sequence[str] = ()
) -> dict[str, str]:
    """Return a complete dictionary row for any exported table header.

    Exact curated glossary entries take precedence. A clearly labelled,
    deterministic fallback ensures a new source column can never disappear from
    either an Excel workbook's dictionary sheet or the database-wide glossary.
    """
    name = str(column_name).strip()
    if not name:
        raise ValueError("Column dictionary headers must be non-empty.")
    exact = [entry for entry in GLOSSARY_ENTRIES if entry.term == name]
    if not exact:
        exact = [
            entry
            for entry in GLOSSARY_ENTRIES
            if entry.term.casefold() == name.casefold()
        ]
    if exact:
        entry = exact[-1]
        return {
            "Column": name,
            "Type / unit": entry.type_or_unit or _inferred_type_or_unit(
                name, declared_type
            ),
            "Plain-language definition": entry.definition,
            "Recorded rule": entry.recorded_rule,
            "Interpretation / caution": entry.interpretation_or_caution,
            "Definition source": entry.source,
            "Relations / exports": ";".join(sorted(set(relations))),
        }
    definition, caution = _inferred_column_definition(name)
    return {
        "Column": name,
        "Type / unit": _inferred_type_or_unit(name, declared_type),
        "Plain-language definition": definition,
        "Recorded rule": "",
        "Interpretation / caution": caution,
        "Definition source": "Deterministic exported-header definition",
        "Relations / exports": ";".join(sorted(set(relations))),
    }


def database_column_dictionary_rows(
    *, relation_schemas: Mapping[str, Mapping[str, str]]
) -> list[dict[str, str]]:
    """Return one complete glossary row per distinct loaded relation header."""
    relations_by_column: dict[str, list[str]] = {}
    types_by_column: dict[str, set[str]] = {}
    for relation, schema in relation_schemas.items():
        for column, declared_type in schema.items():
            relations_by_column.setdefault(str(column), []).append(str(relation))
            types_by_column.setdefault(str(column), set()).add(str(declared_type))
    rows = []
    for column in sorted(relations_by_column, key=lambda value: value.casefold()):
        types = ";".join(sorted(types_by_column[column]))
        rows.append(
            column_definition_row(
                column_name=column,
                declared_type=types,
                relations=relations_by_column[column],
            )
        )
    return rows


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
            "Type / unit": entry.type_or_unit,
            "Plain-language definition": entry.definition,
            "Recorded top-200 rule": entry.recorded_rule,
            "Interpretation / caution": entry.interpretation_or_caution,
            "Source": entry.source,
        }
        for entry in GLOSSARY_ENTRIES
        if entry.section == section
    ]
