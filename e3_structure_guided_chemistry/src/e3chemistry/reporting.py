"""Self-contained HTML reporting for the open chemistry hand-off."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from e3chemistry.models import ChemistryConfig


def _table(records: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    """Render a bounded HTML table."""
    if not records:
        return "<p>No rows were produced.</p>"
    headings = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    rows = []
    for record in records[:500]:
        cells = "".join(
            f"<td>{html.escape(str(record.get(field, '')))}</td>" for field in fields
        )
        rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def write_report(
    *,
    path: Path,
    config: ChemistryConfig,
    targets: Sequence[Mapping[str, Any]],
    group_summaries: Sequence[Mapping[str, Any]],
    fragment_rankings: Sequence[Mapping[str, Any]],
) -> None:
    """Write a concise, method-bounded HTML report."""
    ready = sum(
        row.get("chemistry_handoff_status")
        == "READY_FOR_OPEN_FRAGMENT_PRIORITISATION"
        for row in group_summaries
    )
    biology_supported = sum(
        bool(row.get("biology_and_structure_supported"))
        for row in group_summaries
    )
    tier_one = sum(
        row.get("chemistry_review_tier") == "TIER_1_HIGH_CONFIDENCE_REVIEW"
        for row in group_summaries
    )
    target_table = _table(
        targets,
        (
            "evolutionary_group_rank",
            "evolutionary_group_key",
            "candidate_accession",
            "pocket_number",
            "druggability_score",
            "mapping_fraction",
            "pocket_plddt_fraction",
            "mapped_residue_count",
            "target_status",
        ),
    )
    summary_table = _table(
        group_summaries,
        (
            "evolutionary_group_rank",
            "evolutionary_group_key",
            "feature_count",
            "conserved_component_fraction",
            "mean_chemical_group_conservation",
            "druggability_score",
            "mapped_residue_count",
            "pocket_plddt_fraction",
            "pharmacophore_uniqueness_score",
            "chemistry_review_tier",
            "chemistry_handoff_status",
            "chemistry_handoff_failure_reasons",
        ),
    )
    fragment_table = _table(
        fragment_rankings,
        (
            "evolutionary_group_key",
            "fragment_rank",
            "fragment_id",
            "open_fragment_priority_score",
            "screening_status",
        ),
    )
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>E3 structure-guided chemistry</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1200px;margin:2rem auto;line-height:1.45}}
table{{border-collapse:collapse;width:100%;font-size:0.85rem}}
th,td{{border:1px solid #bbb;padding:0.35rem;text-align:left;vertical-align:top}}
th{{background:#e9eef5}}.warning{{border-left:5px solid #b26a00;padding:0.8rem;background:#fff4df}}
</style></head><body>
<h1>E3 structure-guided chemistry</h1>
<p>Method: <code>{html.escape(config.method_name)}</code>. Explicit candidate
panel: {len(targets)} groups. Groups ready for open fragment prioritisation: {ready} of
{len(group_summaries)}. Biology/structure-supported groups before the druggability and
mapped-residue hand-off gates: {biology_supported}. High-confidence review tier: {tier_one}.
Fragment ranking rows: {len(fragment_rankings)}.</p>
<div class="warning"><strong>Method boundary.</strong> FMOPhore, FrAncestor and
AlphaFold3 were not run. The reported features are residue-derived hypotheses
from existing checksum-bound structures and predicted pockets. Scores do not
establish binding, affinity, selectivity, E3 activity or PROTAC efficacy.</div>
<h2>How to interpret the result</h2>
<p>The workflow converts chemically relevant pocket residues into transparent three-dimensional
feature points and asks whether each feature pattern is sufficiently conserved, structurally
credible and distinct from the other screened groups. Mapping and pocket pLDDT are eligibility
floors. Among eligible Stage 09 representative pockets, the most druggable pocket is selected.
The open-fragment hand-off additionally requires the configured FPocket druggability score and
minimum mapped-residue count. These are prioritisation filters, not evidence that a ligand
binds.</p>
<p><strong>Review tiers.</strong> Tier 1 satisfies the configured hand-off and the stricter
high-confidence conservation, chemical-conservation, pLDDT, druggability and pocket-size review
thresholds. Tier 2 satisfies the configured hand-off. Structurally supported lower tiers preserve
groups that pass biological/structural gates but have weaker representative-pocket chemistry.</p>
<h2>Target preparation</h2>
{target_table}
<h2>Pharmacophore hand-off</h2>
{summary_table}
<h2>Open fragment priorities</h2>
{fragment_table}
</body></html>"""
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(destination)
