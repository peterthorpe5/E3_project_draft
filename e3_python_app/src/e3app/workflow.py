"""Static, accessible schematic of the end-to-end E3 evidence workflow."""

from __future__ import annotations

from html import escape
from typing import Final, TypedDict


class WorkflowStage(TypedDict):
    """User-facing content for one workflow stage."""

    stage: str
    title: str
    operation: str
    output: str
    phase: str
    optional: bool


WORKFLOW_STAGES: Final[dict[str, WorkflowStage]] = {
    "inputs": {
        "stage": "Stages 00–01",
        "title": "Controlled inputs and prepared proteomes",
        "operation": (
            "Validate manifests and checksums, then create consistently named "
            "proteomes so discovery and OrthoFinder use the same species panel."
        ),
        "output": "Provenance-bound, analysis-ready protein sequences.",
        "phase": "preparation",
        "optional": False,
    },
    "discovery": {
        "stage": "Stages 02–03",
        "title": "E3-seeded sequence discovery",
        "operation": (
            "Use reviewed and ubiquitin-associated seeds, tantan masking, "
            "DeepClust clustering and alignment reconciliation to expand the "
            "candidate set without declaring every cluster member to be an E3."
        ),
        "output": "Stable DeepClust candidate and seed-evidence authority.",
        "phase": "sequence",
        "optional": False,
    },
    "orthofinder": {
        "stage": "Stage 04",
        "title": "Independent evolutionary grouping",
        "operation": (
            "Run or reuse OrthoFinder 2.5.5 on the same proteome panel to define "
            "orthogroups and hierarchical orthogroups independently of DeepClust."
        ),
        "output": "Run-specific OrthoFinder group membership.",
        "phase": "sequence",
        "optional": False,
    },
    "orthology": {
        "stage": "Stage 05",
        "title": "Candidate-to-orthology reconciliation",
        "operation": (
            "Reconcile protein identifiers explicitly and map DeepClust candidates "
            "to primary OrthoFinder groups, members and target-species breadth."
        ),
        "output": "Evolutionary groups with traceable member proteins.",
        "phase": "sequence",
        "optional": False,
    },
    "domains": {
        "stage": "Stage 06",
        "title": "E3-associated domain evidence",
        "operation": (
            "Collect Pfam and InterPro annotations and assess the fraction of "
            "domain-assessable species with a catalogued E3-associated domain."
        ),
        "output": "Domain support, availability and gate fields.",
        "phase": "biology",
        "optional": False,
    },
    "expression": {
        "stage": "Stage 07",
        "title": "Expression evidence",
        "operation": (
            "Map members uniquely to Expression Atlas records and retain tissue "
            "context. Broad support uses the recorded median-TPM threshold of 0.5."
        ),
        "output": "Expression support, mapping status and missingness.",
        "phase": "biology",
        "optional": False,
    },
    "shortlist": {
        "stage": "Stage 08",
        "title": "Pre-structure prioritisation",
        "operation": (
            "Apply mandatory discovery, orthology, domain and expression gates "
            "separately from the weighted pre-structure score."
        ),
        "output": "Traceable shortlist for computationally expensive structure work.",
        "phase": "integration",
        "optional": False,
    },
    "ligandability": {
        "stage": "Stage 09",
        "title": "Structures, pockets and pocket conservation",
        "operation": (
            "Assess AlphaFold model confidence; define FPocket cavities; rescore "
            "those cavities with P2Rank; map lining residues; and measure "
            "druggability, predictor agreement and pocket-region conservation."
        ),
        "output": "Selected-pocket, residue, ligandability and conservation evidence.",
        "phase": "structure",
        "optional": False,
    },
    "alignment": {
        "stage": "Stage 09b",
        "title": "Three-dimensional pocket comparison",
        "operation": (
            "Use US-align and TM-align, 3D pocket overlap and centroid distance to "
            "test whether selected pockets occupy comparable structural positions."
        ),
        "output": "Strict rank-one 3D support plus separate sensitivity evidence.",
        "phase": "structure",
        "optional": False,
    },
    "chemistry": {
        "stage": "Stage 09c · optional",
        "title": "Computational chemistry hand-off",
        "operation": (
            "When enabled, derive residue-based pharmacophore features and optional "
            "open-fragment priorities without changing the recorded Milestone 1 rank."
        ),
        "output": "Chemistry-ready evidence for later ligand investigation.",
        "phase": "optional",
        "optional": True,
    },
    "integration": {
        "stage": "Stage 10",
        "title": "Integrated scoring, gates and consolidation",
        "operation": (
            "Join all evidence; keep hard gates separate from continuous scores; "
            "order deterministically; and consolidate related DeepClust rows under "
            "one lead cluster per primary OrthoFinder group."
        ),
        "output": "Authoritative evolutionary-group prioritisation and audit trail.",
        "phase": "integration",
        "optional": False,
    },
    "reporting": {
        "stage": "Stage 11",
        "title": "App-ready computational recommendations",
        "operation": (
            "Publish validated DuckDB, Parquet, TSV and Excel hand-offs for the R "
            "and Python evidence browsers."
        ),
        "output": "Reviewable recommendations, evidence tables and provenance.",
        "phase": "reporting",
        "optional": False,
    },
}


def _stage_card(*, key: str) -> str:
    """Return escaped HTML for one known workflow stage.

    Args:
        key: Stable key in :data:`WORKFLOW_STAGES`.

    Returns:
        A semantic HTML fragment for the requested stage.

    Raises:
        KeyError: If ``key`` is not a configured workflow stage.
    """
    if key not in WORKFLOW_STAGES:
        raise KeyError(f"Unknown workflow stage: {key}")
    stage = WORKFLOW_STAGES[key]
    optional = " workflow-stage-optional" if stage["optional"] else ""
    return (
        f'<section class="workflow-stage workflow-phase-{escape(stage["phase"])}'
        f'{optional}">'
        f'<div class="workflow-stage-id">{escape(stage["stage"])}</div>'
        f'<h4>{escape(stage["title"])}</h4>'
        f'<p>{escape(stage["operation"])}</p>'
        f'<p class="workflow-output"><strong>Output:</strong> '
        f'{escape(stage["output"])}</p>'
        "</section>"
    )


def workflow_schematic_html() -> str:
    """Return the complete responsive end-to-end workflow schematic.

    Returns:
        Static HTML and scoped CSS suitable for Streamlit rendering.
    """
    def card(key: str) -> str:
        """Return one card while keeping the diagram template concise."""
        return _stage_card(key=key)

    return f"""
<style>
.e3-workflow {{
  --workflow-surface: var(--secondary-background-color);
  --workflow-text: var(--text-color);
  color: var(--workflow-text);
  max-width: 1100px;
  margin: 0 auto;
}}
.e3-workflow .workflow-stage {{
  background: var(--workflow-surface);
  border: 1px solid color-mix(in srgb, var(--workflow-text) 18%, transparent);
  border-inline-start: 0.35rem solid currentColor;
  border-radius: 0.5rem;
  padding: 0.85rem 1rem;
  min-width: 0;
}}
.e3-workflow .workflow-stage h4 {{ margin: 0.15rem 0 0.45rem; }}
.e3-workflow .workflow-stage p {{ margin: 0.3rem 0; }}
.e3-workflow .workflow-stage-id {{
  font-size: 0.82rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}}
.e3-workflow .workflow-output {{
  border-top: 1px solid color-mix(in srgb, var(--workflow-text) 12%, transparent);
  margin-top: 0.65rem !important;
  padding-top: 0.55rem;
}}
.e3-workflow .workflow-arrow {{
  font-size: 1.7rem;
  line-height: 1;
  text-align: center;
  padding: 0.25rem;
}}
.e3-workflow .workflow-branch {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}}
.e3-workflow .workflow-lane {{
  display: grid;
  align-content: start;
  gap: 0.4rem;
}}
.e3-workflow .workflow-lane-arrow {{
  font-size: 1.35rem;
  line-height: 1;
  text-align: center;
}}
.e3-workflow .workflow-merge-label {{
  text-align: center;
  font-size: 0.9rem;
  font-weight: 600;
  margin-top: 0.3rem;
}}
.e3-workflow .workflow-stage-optional {{ border-style: dashed; }}
.e3-workflow .workflow-boundary {{
  border-block: 2px solid currentColor;
  margin-top: 0.75rem;
  padding: 0.75rem 0;
  text-align: center;
  font-weight: 600;
}}
@media (max-width: 720px) {{
  .e3-workflow .workflow-branch {{ grid-template-columns: 1fr; }}
}}
</style>
<div class="e3-workflow" role="figure"
     aria-label="End-to-end ARIA plant E3 computational evidence workflow">
  {card("inputs")}
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  <div class="workflow-branch">
    <div class="workflow-lane">
      {card("discovery")}
    </div>
    <div class="workflow-lane">
      {card("orthofinder")}
    </div>
  </div>
  <div class="workflow-merge-label">Candidate and OrthoFinder evidence reconciled</div>
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  {card("orthology")}
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  <div class="workflow-branch">
    <div class="workflow-lane">{card("domains")}</div>
    <div class="workflow-lane">{card("expression")}</div>
  </div>
  <div class="workflow-merge-label">Independent biological evidence combined</div>
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  {card("shortlist")}
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  {card("ligandability")}
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  <div class="workflow-branch">
    <div class="workflow-lane">{card("alignment")}</div>
    <div class="workflow-lane">{card("chemistry")}</div>
  </div>
  <div class="workflow-merge-label">Recorded structural evidence and optional hand-off</div>
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  {card("integration")}
  <div class="workflow-arrow" aria-hidden="true">↓</div>
  {card("reporting")}
  <div class="workflow-boundary">
    Computational prioritisation → structural, chemical and experimental validation
  </div>
</div>
""".strip()
