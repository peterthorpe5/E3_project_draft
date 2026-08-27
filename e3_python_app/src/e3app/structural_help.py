"""Contextual help for structural-reference and pocket-pair evidence."""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Mapping

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

PAIR_EVIDENCE_DEFINITIONS: Mapping[str, str] = {
    "Minimum TM-score": (
        "The lower of the TM-scores normalised by the two protein lengths. Values "
        "approach 1 for highly similar global structures; the recorded global-fold "
        "threshold is 0.50."
    ),
    "RMSD (Å)": (
        "Root-mean-square distance between aligned atoms after superposition, in "
        "Angstrom. Lower is closer, but the value depends on alignment length and "
        "outliers and is not itself a Boolean production gate."
    ),
    "Pocket centroid distance (Å)": (
        "Distance between the arithmetic centres of the selected pocket C-alpha "
        "coordinates after superposition. Same-position support requires at most 8 "
        "Angstrom."
    ),
    "Symmetric pocket overlap": (
        "Mean of the two directional fractions of pocket C-alpha residues lying within "
        "4 Angstrom of the other pocket. Same-position support requires at least 0.50; "
        "this is not a cavity-volume overlap."
    ),
    "Local structural-residue match": (
        "Fraction 2M/(N-reference + N-mobile), where M is the number of mutual-nearest "
        "pocket C-alpha pairs within 4 Angstrom. Local conservation requires at least "
        "0.50."
    ),
    "Local chemical-group conservation": (
        "Fraction of exactly mapped, structurally paired residues retaining the same "
        "broad biochemical class. Local conservation requires at least 0.60; this is "
        "not sequence identity or experimental binding evidence."
    ),
    "Same pocket position supported": (
        "True only when minimum TM-score is at least 0.50, pocket-centroid distance is "
        "at most 8 Angstrom and symmetric pocket overlap is at least 0.50."
    ),
    "Locally conserved pocket supported": (
        "True only when same-position support passes and the local structural-residue "
        "match and chemical-group conservation thresholds also pass."
    ),
}

STRUCTURAL_COLUMN_HELP: Mapping[str, str] = {
    "reference_accession": (
        "Fixed protein model defining the coordinate frame. Other models are transformed "
        "onto this reference; reference status is not a claim of biological superiority."
    ),
    "mobile_accession": (
        "Protein model transformed onto the fixed reference by the recorded structural "
        "alignment matrix."
    ),
    "reference_species": "Species supplying the fixed structural reference model.",
    "mobile_species": "Species supplying the transformed, aligned member model.",
    "alignment_tool": (
        "Structural aligner that generated this transformation. The strict analysis "
        "retains agreement between US-align and TM-align."
    ),
    "minimum_tm_score": PAIR_EVIDENCE_DEFINITIONS["Minimum TM-score"],
    "rmsd_angstrom": PAIR_EVIDENCE_DEFINITIONS["RMSD (Å)"],
    "centroid_distance_angstrom": PAIR_EVIDENCE_DEFINITIONS[
        "Pocket centroid distance (Å)"
    ],
    "symmetric_overlap_fraction": PAIR_EVIDENCE_DEFINITIONS[
        "Symmetric pocket overlap"
    ],
    "symmetric_pocket_overlap_fraction": PAIR_EVIDENCE_DEFINITIONS[
        "Symmetric pocket overlap"
    ],
    "structural_residue_match_fraction": PAIR_EVIDENCE_DEFINITIONS[
        "Local structural-residue match"
    ],
    "structural_chemical_group_conservation": PAIR_EVIDENCE_DEFINITIONS[
        "Local chemical-group conservation"
    ],
    "same_pocket_position_supported": PAIR_EVIDENCE_DEFINITIONS[
        "Same pocket position supported"
    ],
    "same_pocket_supported": PAIR_EVIDENCE_DEFINITIONS[
        "Same pocket position supported"
    ],
    "pocket_structure_conserved": PAIR_EVIDENCE_DEFINITIONS[
        "Locally conserved pocket supported"
    ],
}

_HELP_STYLE = """<style id="e3-pair-evidence-help-style">
.e3-metric-help{position:relative;display:inline-flex;align-items:center;justify-content:center;
width:1.05rem;height:1.05rem;margin-left:.3rem;border:1px solid #58758d;border-radius:50%;
background:#eef5fa;color:#173f5f;font-size:.72rem;font-weight:700;cursor:help;outline:none}
.e3-metric-help-text{visibility:hidden;opacity:0;position:absolute;right:0;top:1.35rem;
z-index:20;width:270px;padding:.55rem .65rem;border:1px solid #9db2c2;border-radius:6px;
background:#ffffff;color:#18212b;font-size:.78rem;font-weight:400;line-height:1.35;
box-shadow:0 4px 14px rgba(23,63,95,.22);transition:opacity .12s ease}
.e3-metric-help:hover .e3-metric-help-text,
.e3-metric-help:focus .e3-metric-help-text,
.e3-metric-help:focus-within .e3-metric-help-text{visibility:visible;opacity:1}
</style>"""


def _normalised_nonempty_text(*, value: object, label: str) -> str:
    """Return a non-empty stripped string.

    Args:
        value: Candidate value.
        label: Field name used in a controlled error.

    Returns:
        Non-empty text.

    Raises:
        AppError: If the value is empty.
    """
    text = str(value).strip()
    if not text:
        raise AppError(f"{label} must be non-empty when rendering structural help")
    return text


def structural_column_help(*, column_name: object) -> str | None:
    """Return focused help for a recognised structural table column.

    Args:
        column_name: Source column name.

    Returns:
        Help text, or ``None`` when the column requires no maintained help.
    """
    return STRUCTURAL_COLUMN_HELP.get(str(column_name).strip())


def pair_evidence_help_markdown() -> str:
    """Return readable definitions for every pair-evidence viewer metric."""
    blocks = [
        f"- **{label}:** {definition}"
        for label, definition in PAIR_EVIDENCE_DEFINITIONS.items()
    ]
    blocks.extend(
        [
            "",
            (
                "Broad biochemical classes are hydrophobic (A, V, L, I, M, F, W, Y), "
                "polar (S, T, N, Q), positive (K, R, H), negative (D, E) and special "
                "(C, G, P)."
            ),
            "",
            (
                "These are computational support measures for the selected model and pocket "
                "pair. They do not demonstrate shared ligand binding, E3 activity or "
                "experimental PROTAC behaviour."
            ),
        ]
    )
    return "\n".join(blocks)


def reference_selection_help_markdown(
    *,
    reference_accession: object,
    reference_species: object,
    preserved_from_parent: bool,
) -> str:
    """Explain why one eligible protein supplies the fixed coordinate frame.

    Args:
        reference_accession: Selected reference accession.
        reference_species: Selected reference species.
        preserved_from_parent: Whether a human extension inherited the reference.

    Returns:
        Streamlit-compatible Markdown explanation.
    """
    accession = _normalised_nonempty_text(
        value=reference_accession,
        label="reference_accession",
    )
    species = _normalised_nonempty_text(
        value=reference_species,
        label="reference_species",
    ).replace("_", " ")
    blocks = [
        (
            f"`{accession}` ({species}) defines the common coordinate frame for this "
            "group. It was not chosen because its species has biological priority."
        ),
        "",
        (
            "First, the parent campaign selected one auditable representative per plant "
            "species so paralogue-rich species could not dominate the comparison."
        ),
        "",
        (
            "Among representatives with an eligible model, selected pocket and mapped "
            "coordinates, the reference ordering preferred: (1) high-confidence structural "
            "evidence, (2) pocket-predictor agreement, (3) higher pocket-mapping fraction, "
            "(4) higher pocket-pLDDT fraction, (5) higher predicted druggability and then "
            "(6) accession as the reproducible final tie-break."
        ),
        "",
        (
            f"Therefore, a {species} reference means that this particular representative "
            "ranked first under those recorded evidence rules. It does not mean that it is "
            "ancestral, closest to every member, closest to human, or biologically superior."
        ),
    ]
    if preserved_from_parent:
        blocks.extend(
            [
                "",
                (
                    "The human extension inherited this plant reference unchanged. It did not "
                    "reselect a reference after examining the human models, preventing a "
                    "stronger-looking human comparison from being chosen post hoc."
                ),
            ]
        )
    return "\n".join(blocks)


def human_extension_rank_help_markdown(*, qualifying_group_count: int) -> str:
    """Explain the filtered and non-contiguous human-extension ranks.

    Args:
        qualifying_group_count: Number of groups published in the extension.

    Returns:
        Streamlit-compatible Markdown explanation.

    Raises:
        AppError: If the count is negative.
    """
    if qualifying_group_count < 0:
        raise AppError("qualifying_group_count cannot be negative")
    return (
        f"The menu contains **{qualifying_group_count} qualifying groups**, not every "
        "group within the parent review limit. Inclusion required parent structural-analysis "
        "authority, at least one exact human accession in the same OrthoFinder HOG and one "
        "unambiguous preserved plant reference. Original parent ranks were retained rather "
        "than renumbered, so gaps are expected. A missing rank is not a drop-down error and "
        "does not prove that no more distant human homologue or structural analogue exists."
    )


def pocket_choice_help_markdown() -> str:
    """Return focused guidance for alternative structure and pocket controls."""
    return (
        "Choose a protein model to inspect that member in the selected HOG. The **rank-one "
        "pocket** is the deterministic primary pocket used for the strict conclusion. Other "
        "retained pockets are available as a top-ranked sensitivity review: displaying one "
        "does not replace the rank-one result or change candidate ordering. FPocket provides "
        "the cavity geometry and P2Rank supplies the linked ranking signal. All displayed "
        "pockets are predictions, not experimentally confirmed ligand-binding sites."
    )


def annotate_pair_evidence_html(*, document: str) -> str:
    """Add accessible question-mark tooltips to a portable pair-evidence table.

    The transformation is presentation-only and leaves metric labels and values
    unchanged. Documents without recognised metric rows are returned unchanged.

    Args:
        document: Trusted, validated portable viewer HTML.

    Returns:
        Viewer HTML with idempotent metric help annotations.
    """
    if not isinstance(document, str):
        raise AppError("Structural viewer document must be text")
    if not document:
        raise AppError("Structural viewer document is empty")
    if 'id="e3-pair-evidence-help-style"' in document:
        return document
    annotated = document
    added = 0
    for label, definition in PAIR_EVIDENCE_DEFINITIONS.items():
        escaped_label = html.escape(label)
        original = f"<th>{escaped_label}</th>"
        if original not in annotated:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        accessible = html.escape(f"Help for {label}: {definition}", quote=True)
        tooltip = html.escape(definition)
        replacement = (
            f"<th>{escaped_label}<span class=\"e3-metric-help\" tabindex=\"0\" "
            f"aria-label=\"{accessible}\">?<span class=\"e3-metric-help-text\" "
            f"id=\"e3-help-{slug}\" role=\"tooltip\">{tooltip}</span></span></th>"
        )
        annotated = annotated.replace(original, replacement, 1)
        added += 1
    if not added:
        return document
    if "</head>" in annotated:
        annotated = annotated.replace("</head>", f"{_HELP_STYLE}</head>", 1)
    else:
        annotated = f"{_HELP_STYLE}{annotated}"
    LOGGER.debug("Annotated %d structural pair-evidence metrics", added)
    return annotated
