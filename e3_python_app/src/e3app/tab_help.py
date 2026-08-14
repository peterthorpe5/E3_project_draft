"""Contextual help for every top-level application tab."""

from __future__ import annotations

from e3app.errors import AppError

TOP_LEVEL_TAB_HELP = {
    "Overview": (
        "Review the release-wide counts and evidence scope first. Counts describe "
        "computational groups, not experimentally validated E3 ligases."
    ),
    "Workflow schematic": (
        "Follow the workflow from controlled inputs to reporting. Use it to identify "
        "where each result was calculated and which evidence streams are independent."
    ),
    "Glossary": (
        "Choose a section or search the browser table to define fields, thresholds "
        "and statuses. Download the glossary when interpreting results externally."
    ),
    "Computational recommendations": (
        "Review the recorded final ranking, gate outcomes and exclusion reasons. "
        "Sensitivity controls do not overwrite the authoritative recommendation."
    ),
    "Threshold explorer": (
        "Change documented gates to create sensitivity lists. Compare the separate "
        "pre-structure and structural tables and download the active result set."
    ),
    "Pre-structure ranked HOGs": (
        "Choose the number of HOGs required. Results use the recorded pre-structure "
        "HOG rank directly and apply no biological, pocket or structural gate."
    ),
    "Visual explorer": (
        "Choose candidate metrics and a group to connect the overview plot to exact "
        "candidate, expression and differential-expression eligibility evidence."
    ),
    "Candidates": (
        "Select a candidate relation and the columns required for review. Increase "
        "the bounded row count before downloading when more records are needed."
    ),
    "Orthology": (
        "Choose root HOGs or legacy orthogroups, then use species, taxonomy, breadth "
        "and seed filters. Group membership does not prove conserved function."
    ),
    "Human HOGs": (
        "Load the view to find every root HOG containing human sequence input. Search "
        "identifiers or names and inspect both human annotations and all co-members."
    ),
    "Plant & human HOGs": (
        "Load HOGs containing human and at least one curated target plant. Use the "
        "summary for ranking and the member table for exact species composition."
    ),
    "Seed & HOG explorer": (
        "Paste one or several E3 seed identifiers, choose Any or All matching and "
        "inspect every member of the matching HOGs before downloading FASTA."
    ),
    "Domains": (
        "Select summary or hit-level domain evidence. Keep assessed negatives "
        "separate from unavailable annotation when interpreting support fractions."
    ),
    "Expression": (
        "Filter by species, tissue and identifier. Median TPM is used where available; "
        "missing mappings are unavailable evidence rather than measured zero."
    ),
    "Ligandability": (
        "Inspect retained pockets, predictor evidence and member-level druggability. "
        "Predicted pockets are computational starting points, not binding validation."
    ),
    "Pocket conservation": (
        "Use summaries for group status and detailed rows for residues and sequence "
        "coordinates. Conserved sequence position is distinct from conserved 3D shape."
    ),
    "3D structures & pockets": (
        "Select a group and member, then rotate the structure and inspect mapped pocket "
        "surfaces. Use the download controls for review images and source evidence."
    ),
    "Pocket-aligned sequences": (
        "Select a group to inspect its pocket-annotated alignment. Download the aligned "
        "FASTA, not the unaligned member FASTA, for alignment-aware downstream work."
    ),
    "3D alignment": (
        "Select an alignment relation and group to inspect global and pocket-local "
        "comparisons. TM-scores and pocket overlap answer different questions."
    ),
    "Computational chemistry": (
        "Review chemistry readiness, pharmacophore features and method status. A blank "
        "or NOT_RUN method is not evidence that the chemistry criterion failed."
    ),
    "Search": (
        "Paste one or several HOG IDs, seeds, accessions or names. Smart search reports "
        "every matching relation and matched column, so one term may return several rows."
    ),
    "All results": (
        "Choose any loaded relation for schema-level audit. Select columns before "
        "previewing; downloads contain only the bounded rows currently requested."
    ),
    "Provenance and QC": (
        "Inspect release identifiers, source files, checksums and validation outcomes "
        "before citing or transferring results. Any failed QC requires investigation."
    ),
}


def tab_help_text(*, tab_name: str) -> str:
    """Return contextual instructions for one top-level tab.

    Args:
        tab_name: Exact user-facing tab label.

    Returns:
        Concise help text for the requested tab.

    Raises:
        AppError: If no maintained help entry exists.
    """
    try:
        return TOP_LEVEL_TAB_HELP[tab_name]
    except KeyError as exc:
        raise AppError(f"No contextual help is defined for tab: {tab_name}") from exc
