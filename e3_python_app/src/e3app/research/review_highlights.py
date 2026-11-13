"""Attach validated sequence and domain coordinates to portable structural reviews."""

from __future__ import annotations

import json
import logging
import re
from typing import Mapping

import duckdb
import pandas as pd

from e3app.errors import AppError
from e3app.pocket_review import _embedded_json_script

from .common import ResearchError, normalise_protein
from .feature_catalogue import published_features
from .linked_features import MAX_LINKED_RESIDUES, linked_domain_features, model_residues
from .viewers import json_for_html, viewer_asset

LOGGER = logging.getLogger(__name__)
MARKER = 'id="e3ReviewHighlights"'
MAX_HIGHLIGHT_BYTES = 5_000_000


def review_highlight_payload(
    *, group: dict, pair: dict | None, group_id: str, connection: object | None,
    pair_members: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, dict[str, object]]:
    """Match sequence and optional domain features to the visible review structures.

    Args:
        group: Portable group JSON with the alignment and per-member models.
        pair: Pairwise superposition JSON, when viewing reference and mobile models.
        group_id: Exact group for looking up released domain coordinates.
        connection: Optional E3 release containing recorded domains.
        pair_members: Recorded accession and species for each pair-viewer role.

    Returns:
        Only targets with one unambiguous sequence and a matching C-alpha chain.
    """
    records = group.get("alignment", {}).get("records", [])
    proteins = group.get("proteins", [])
    by_member: dict[tuple[str, str], set[str]] = {}
    for row in records:
        member = (str(row.get("accession", "")), str(row.get("species", "")))
        try:
            sequence = normalise_protein(
                sequence=re.sub(r"[-.]", "", str(row.get("sequence") or "")),
            )
        except ResearchError:
            continue
        by_member.setdefault(member, set()).add(sequence)
    if pair is None:
        targets = [
            (row.get("accession"), (row.get("accession"), row.get("species")), row.get("atoms"))
            for row in proteins
        ]
    else:
        targets = [
            (role, member, pair.get(role)) for role, member in (pair_members or {}).items()
            if role in {"reference", "mobile"}
            and pair.get("metadata", {}).get(role) == member[0]
        ]
    domains_by_member: dict[tuple[str, str], list[dict[str, object]]] = {}
    if connection is not None:
        try:
            rows = published_features(connection=connection, accession=None, group_id=group_id)
            for row in rows.to_dict(orient="records"):
                key = (str(row["member_accession"]).strip().upper(), str(row["species_column"]))
                domains_by_member.setdefault(key, []).append(row)
        except (ResearchError, duckdb.Error) as exc:
            LOGGER.debug("No recorded domains for %s: %s", group_id, exc)
    seen = set()
    result = {}
    for target, member, atoms in targets:
        if target in seen:
            result.pop(target, None)
            continue
        seen.add(target)
        options = by_member.get(member, set())
        if not target or not all(member) or len(options) != 1 or not isinstance(atoms, list):
            continue
        sequence = next(iter(options))
        if len(sequence) > MAX_LINKED_RESIDUES:
            continue
        try:
            model_residues(atoms=atoms, sequence=sequence)
        except ResearchError as exc:
            LOGGER.info("Review highlights unavailable for %s in %s: %s", target, group_id, exc)
            continue
        context = (member[0].strip().upper(), member[1])
        features = []
        try:
            features = linked_domain_features(
                rows=pd.DataFrame(domains_by_member.get(context, ())), sequence=sequence,
            )
        except ResearchError as exc:
            LOGGER.debug("No usable domain coordinates for %s in %s: %s", target, group_id, exc)
        result[target] = {"sequence": sequence, "features": features}
    return result


def add_review_highlights(
    *, document: str, group_id: str, connection: object | None = None,
    group_document: str | None = None,
    pair_members: Mapping[str, tuple[str, str]] | None = None,
) -> str:
    """Add offline highlights and a PDF action to a compatible review.

    Args:
        document: Trusted app-loaded group or pair HTML with terminal controls.
        group_id: Selected release group.
        connection: Optional release to query for recorded domains.
        group_document: Original group page for a pairwise view.
        pair_members: Exact reference and mobile accessions and species.

    Returns:
        Idempotently augmented HTML, or the original for an unsupported review.
    """
    if MARKER in document or 'data-e3-terminal-trimming="true"' not in document:
        return document
    group = _embedded_json_script(document=group_document or document, element_id="reviewData")
    pair = _embedded_json_script(document=document, element_id="alignmentData")
    if group is None and pair is None:
        return document
    try:
        group_data = json.loads(group.group("payload")) if group else {}
        pair_data = json.loads(pair.group("payload")) if pair else None
        if not isinstance(group_data, dict) or (pair and not isinstance(pair_data, dict)):
            return document
        source_group = group_data.get("group_key", {}).get("primary_group_id")
        if source_group is not None and source_group != group_id:
            LOGGER.warning("Mismatched group payload while preparing viewer for %s", group_id)
            return document
        targets = review_highlight_payload(
            group=group_data, pair=pair_data, group_id=group_id, connection=connection,
            pair_members=pair_members,
        )
        payload = json_for_html(value={"group": group_id, "targets": targets})
        if len(payload) > MAX_HIGHLIGHT_BYTES:
            LOGGER.warning("Review highlights exceed their display bound for %s", group_id)
            return document
        script = viewer_asset(name="review-highlights.js")
    except (AttributeError, TypeError, ValueError, AppError) as exc:
        LOGGER.warning("Could not add review highlights for %s: %s", group_id, exc)
        return document
    script = re.sub(r"</script", r"<\\/script", script, flags=re.IGNORECASE)
    injection = (
        f'<script {MARKER} type="application/json">{payload}</script>'
        f"<script>{script}</script>"
    )
    before, close, after = document.rpartition("</body>")
    return before + injection + close + after if close else document + injection
