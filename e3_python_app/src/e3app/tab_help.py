"""Contextual operating help for every top-level application tab."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TabHelpEntry:
    """Operating instruction and expected output for one tab."""

    instruction: str
    yields: str


TOP_LEVEL_TAB_HELP = {
    "Overview": TabHelpEntry(
        instruction=(
            "Review the release-wide counts and evidence scope first; counts describe "
            "computational groups, not experimentally validated E3 ligases."
        ),
        yields=(
            "A compact release summary showing the number of evolutionary groups, candidate "
            "stages, available evidence classes and key Milestone 1 and 2 outcomes in the "
            "currently loaded resource."
        ),
    ),
    "Workflow schematic": TabHelpEntry(
        instruction=(
            "Follow the workflow from controlled inputs to reporting to identify where each "
            "result was calculated and which evidence streams are independent."
        ),
        yields=(
            "A stage-by-stage process map linking discovery, orthology, domains, expression, "
            "structures, pockets, conservation, ranking and reporting, including the main "
            "handoff files between stages."
        ),
    ),
    "Glossary": TabHelpEntry(
        instruction=(
            "Choose a section or search the browser table to define fields, thresholds and "
            "statuses before interpreting or exporting results."
        ),
        yields=(
            "Searchable definitions, recorded threshold values, missing-evidence states and "
            "field-level interpretations, plus a downloadable glossary for use outside the app."
        ),
    ),
    "Computational recommendations": TabHelpEntry(
        instruction=(
            "Review the recorded final ranking, gate outcomes and exclusion reasons; sensitivity "
            "controls do not overwrite the authoritative recommendation."
        ),
        yields=(
            "The authoritative recommendation table, a focused all-members druggability "
            "sensitivity analysis, the complete ranking formulas and an optional exploratory "
            "reweighting table with TSV and Excel downloads."
        ),
    ),
    "Threshold explorer": TabHelpEntry(
        instruction=(
            "Change documented gates only when creating a sensitivity list, and compare the "
            "separate pre-structure and structurally informed results."
        ),
        yields=(
            "Matched pre-structure and structural candidate tables labelled PASS, NEAR_MISS or "
            "FAIL under the active controls, with counts, reasons, HOG context and downloadable "
            "TSV and Excel files."
        ),
    ),
    "Independent structural-review shortlist": TabHelpEntry(
        instruction=(
            "Choose the top 200 to 500 HOGs from the complete recorded pre-structure evidence "
            "ranking; existing pocket and structural results are deliberately excluded."
        ),
        yields=(
            "An independent root-HOG review queue with authoritative pre-structure rank, pass "
            "status, candidate and seed context, species coverage, domain and expression evidence, "
            "human, Arabidopsis, rice and barley representatives and table downloads."
        ),
    ),
    "Visual explorer": TabHelpEntry(
        instruction=(
            "Choose candidate metrics and a group to connect overview plots to the exact "
            "candidate, expression and differential-expression eligibility evidence."
        ),
        yields=(
            "Interactive candidate-landscape, expression and volcano-style views, a selected-group "
            "evidence table and reproducible PDF figures with supporting TSV or Excel downloads."
        ),
    ),
    "Candidates": TabHelpEntry(
        instruction=(
            "Select a candidate relation and the columns required for review, increasing the "
            "bounded row count before downloading when more records are needed."
        ),
        yields=(
            "A configurable preview of candidate-level source fields from the selected relation, "
            "with the displayed bounded rows available as TSV and formatted Excel."
        ),
    ),
    "Orthology": TabHelpEntry(
        instruction=(
            "Choose root HOGs or legacy orthogroups, then apply species, taxonomy, breadth and "
            "seed filters; group membership does not prove conserved function."
        ),
        yields=(
            "OrthoFinder release metrics, group-size plots, filtered HOG or OG summaries and "
            "member tables, plus a separate DeepClust and 1KP sequence-neighbourhood view and "
            "downloadable supporting data."
        ),
    ),
    "Human HOGs": TabHelpEntry(
        instruction=(
            "Load root HOGs containing human sequence input, search identifiers or names and "
            "inspect human annotations alongside every other member."
        ),
        yields=(
            "A one-row-per-HOG summary, the matching human member records and the complete "
            "cross-species membership for each selected HOG, with TSV, Excel and available FASTA "
            "downloads."
        ),
    ),
    "Plant & human HOGs": TabHelpEntry(
        instruction=(
            "Load HOGs containing human and at least one curated target plant, using the member "
            "rows rather than the summary alone for exact species composition."
        ),
        yields=(
            "A filtered HOG summary with ranking and human context, plus human members and all "
            "plant and non-plant co-members for the selected evolutionary groups and matching "
            "downloads."
        ),
    ),
    "Seed & HOG explorer": TabHelpEntry(
        instruction=(
            "Paste one or several E3 seed identifiers, choose Any or All matching and inspect "
            "every member of the matching HOGs before downloading sequence data."
        ),
        yields=(
            "A seed-to-group match summary, complete group-member table, associated evidence for "
            "a single selected group and downloadable protein FASTA where sequences are available."
        ),
    ),
    "E3 seed catalogue": TabHelpEntry(
        instruction=(
            "Search inherited known-E3 identifiers, names and source annotations, noting whether "
            "the release provides exact seed authority or a cluster-associated fallback."
        ),
        yields=(
            "One searchable row per available seed record with source-scope provenance, associated "
            "annotations where necessary, TSV and Excel tables and accession-matched FASTA only "
            "where an exact sequence is available."
        ),
    ),
    "Domains": TabHelpEntry(
        instruction=(
            "Select summary or hit-level domain evidence, keeping assessed negatives separate "
            "from unavailable annotation when interpreting support fractions."
        ),
        yields=(
            "Group or member domain-support summaries and exact InterPro/Pfam hit rows, including "
            "catalogue matches, E3-family interpretation, availability states and downloadable "
            "source fields."
        ),
    ),
    "Expression": TabHelpEntry(
        instruction=(
            "Filter by species, tissue and identifier; median TPM is used where available and "
            "missing mappings remain unavailable rather than measured zero."
        ),
        yields=(
            "Candidate-by-experiment-context expression rows with tissue and metadata filters, "
            "evidence-state fields, selected statistics and TSV or Excel downloads from the "
            "currently loaded Expression Atlas resource."
        ),
    ),
    "Ligandability": TabHelpEntry(
        instruction=(
            "Inspect retained pockets, predictor evidence and member-level druggability, treating "
            "predicted pockets as computational starting points rather than binding validation."
        ),
        yields=(
            "Selected and ranked pocket tables with FPocket and P2Rank evidence, druggability, "
            "residue-mapping quality, pocket-local pLDDT and explicit pass or availability fields "
            "for each assessed structural representative."
        ),
    ),
    "Pocket conservation": TabHelpEntry(
        instruction=(
            "Use summaries for group status and detailed rows for residues and sequence "
            "coordinates; conserved sequence position is distinct from conserved 3D shape."
        ),
        yields=(
            "Group-level pocket-region conservation summaries, member and residue mappings, "
            "aligned coordinate evidence, conservation scores and tables suitable for tracing a "
            "call back to the selected pocket residues."
        ),
    ),
    "3D structures & pockets": TabHelpEntry(
        instruction=(
            "Select a group and member, rotate the structure and inspect the mapped pocket "
            "location before using the download controls for review evidence."
        ),
        yields=(
            "Portable interactive C-alpha and pocket-residue views, selected-group and member "
            "summaries, downloadable review images where supported and links to the exact recorded "
            "structure and pocket evidence."
        ),
    ),
    "Pocket-aligned sequences": TabHelpEntry(
        instruction=(
            "Select a group to inspect its pocket-annotated alignment and use aligned FASTA, not "
            "unaligned member FASTA, for alignment-aware downstream work."
        ),
        yields=(
            "A portable alignment view highlighting the selected pocket-associated residues, a "
            "member summary and the exact aligned protein FASTA used for the pocket-region "
            "analysis."
        ),
    ),
    "3D alignment": TabHelpEntry(
        instruction=(
            "Select an alignment relation and group to inspect global and pocket-local "
            "comparisons; TM-scores and pocket overlap answer different questions."
        ),
        yields=(
            "An interactive TM-score versus 3D pocket-overlap evidence map, the exact plotted "
            "rows, group and pairwise alignment tables, local residue evidence and a vector PDF "
            "of the summary plot."
        ),
    ),
    "Computational chemistry": TabHelpEntry(
        instruction=(
            "Review chemistry readiness, pharmacophore features and method status, recognising "
            "that blank or NOT_RUN does not mean a chemistry criterion failed."
        ),
        yields=(
            "The available group readiness summaries, residue-derived pharmacophore feature "
            "rows, method execution states and hand-off fields prepared for computational "
            "chemistry review."
        ),
    ),
    "Search": TabHelpEntry(
        instruction=(
            "Paste one or several HOG IDs, seeds, accessions or names; smart search reports every "
            "matching relation and matched column, so one term may return several rows."
        ),
        yields=(
            "A term-level match summary and bounded exact source rows carrying the matched value, "
            "relation and field provenance, with downloadable summary and result tables."
        ),
    ),
    "All results": TabHelpEntry(
        instruction=(
            "Use the enriched HOG overview for one row per HOG, member detail for every HOG member "
            "and raw relations for exact source-level audit."
        ),
        yields=(
            "Joined HOG overview and member-detail views containing rankings, human and "
            "Arabidopsis, rice and barley representatives, membership and species context, plus "
            "every raw DuckDB relation under bounded preview and download controls."
        ),
    ),
    "Provenance and QC": TabHelpEntry(
        instruction=(
            "Inspect release identifiers, source files, checksums and validation outcomes before "
            "citing or transferring results; any failed QC requires investigation."
        ),
        yields=(
            "Run, source-manifest, software-version, checksum, validation and quality-control "
            "tables that identify the producing stage and evidence state behind the scientific "
            "outputs."
        ),
    ),
}


def tab_help_entry(*, tab_name: str) -> TabHelpEntry:
    """Return structured operating help for one top-level tab.

    Args:
        tab_name: Exact user-facing tab label.

    Returns:
        Maintained operating instruction and expected output.

    Raises:
        AppError: If no maintained help entry exists.
    """
    try:
        entry = TOP_LEVEL_TAB_HELP[tab_name]
    except KeyError as exc:
        raise AppError(f"No contextual help is defined for tab: {tab_name}") from exc
    LOGGER.debug("Loaded operating help for tab=%s", tab_name)
    return entry


def tab_help_text(*, tab_name: str) -> str:
    """Return formatted operating help for one top-level tab.

    Args:
        tab_name: Exact user-facing tab label.

    Returns:
        Markdown with an instruction and explicit description of yielded content.
    """
    entry = tab_help_entry(tab_name=tab_name)
    return f"{entry.instruction}\n\n**What this tab yields:** {entry.yields}"
