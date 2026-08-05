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
    for record in records[:20]:
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
    target_table = _table(
        targets,
        (
            "evolutionary_group_rank",
            "evolutionary_group_key",
            "candidate_accession",
            "pocket_number",
            "target_status",
        ),
    )
    summary_table = _table(
        group_summaries,
        (
            "evolutionary_group_rank",
            "evolutionary_group_key",
            "feature_count",
            "pharmacophore_uniqueness_score",
            "chemistry_handoff_status",
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
<p>Method: <code>{html.escape(config.method_name)}</code>. Selected group limit:
{config.group_limit}. Groups ready for open fragment prioritisation: {ready} of
{len(group_summaries)}. Fragment ranking rows: {len(fragment_rankings)}.</p>
<div class="warning"><strong>Method boundary.</strong> FMOPhore, FrAncestor and
AlphaFold3 were not run. The reported features are residue-derived hypotheses
from existing checksum-bound structures and predicted pockets. Scores do not
establish binding, affinity, selectivity, E3 activity or PROTAC efficacy.</div>
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
