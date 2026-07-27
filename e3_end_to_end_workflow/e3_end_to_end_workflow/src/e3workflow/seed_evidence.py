"""Derive the compact, version-controlled known-E3 evidence resource."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from e3workflow.errors import ManifestError
from e3workflow.io_utils import read_tsv, sha256_file, write_tsv

SOURCE_COLUMNS = frozenset(
    {
        "seed_id",
        "source_value",
        "source_column",
        "source_row",
        "source_path",
        "seed_metadata_json",
    }
)
EVIDENCE_COLUMNS = (
    "accession",
    "evidence_type",
    "source",
    "e3_category",
    "ubiquitin_go_term",
    "exclusion_go_term",
    "organism",
    "taxon_id",
    "sequence_md5",
    "source_value",
    "source_column",
    "source_row",
    "source_path",
)
METADATA_FIELDS = {
    "e3_category": "category",
    "ubiquitin_go_term": "ubiquitin_go_term",
    "exclusion_go_term": "exclusion_go_term",
    "organism": "organism",
    "taxon_id": "organism_id",
    "sequence_md5": "sequence_md5",
}


def _metadata_object(value: str, source: Path, line_number: int) -> dict[str, Any]:
    """Parse and validate one inherited seed-metadata JSON object."""
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"Invalid seed_metadata_json at {source}:{line_number}: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"seed_metadata_json is not an object at {source}:{line_number}")
    return payload


def derive_seed_evidence(source: Path) -> list[dict[str, str]]:
    """Derive compact evidence rows from an authoritative discovery seed table.

    Args:
        source: Discovery-engine ``known_e3_seeds.tsv`` path.

    Returns:
        Evidence records in source order.

    Raises:
        ManifestError: If required columns, accessions or metadata are invalid.
    """
    fields, rows = read_tsv(source)
    missing = SOURCE_COLUMNS.difference(fields)
    if missing:
        raise ManifestError(
            f"Missing source seed columns in {source}: {', '.join(sorted(missing))}"
        )
    if not rows:
        raise ManifestError(f"Source seed table contains no rows: {source}")
    evidence_rows = []
    seen = set()
    for line_number, row in enumerate(rows, start=2):
        accession = row["seed_id"].strip()
        if not accession or accession in seen:
            raise ManifestError(f"Empty or duplicate seed_id at {source}:{line_number}")
        seen.add(accession)
        metadata = _metadata_object(row["seed_metadata_json"], source, line_number)
        record = {
            "accession": accession,
            "evidence_type": "inherited_known_E3_seed",
            "source": "inherited_E3_discovery_engine_known_e3_seeds",
            "source_value": row["source_value"],
            "source_column": row["source_column"],
            "source_row": row["source_row"],
            "source_path": row["source_path"],
        }
        for output_column, metadata_key in METADATA_FIELDS.items():
            value = metadata.get(metadata_key, "")
            record[output_column] = "" if value is None else str(value)
        evidence_rows.append(record)
    return evidence_rows


def default_provenance_path(output: Path) -> Path:
    """Return the standard provenance path beside one evidence archive."""
    suffix = ".tsv.gz"
    if not output.name.endswith(suffix):
        raise ManifestError(f"Evidence output must end in {suffix}: {output}")
    stem = output.name[: -len(suffix)]
    return output.with_name(f"{stem}.provenance.tsv")


def build_seed_evidence(
    source: Path,
    output: Path,
    provenance_output: Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Build deterministic seed evidence and its checksum provenance table.

    Args:
        source: Authoritative discovery-engine seed table.
        output: Destination ending in ``.tsv.gz``.
        provenance_output: Optional destination for the provenance TSV.
        force: Replace existing destinations when true.

    Returns:
        JSON-compatible build summary.

    Raises:
        ManifestError: If inputs are invalid or replacement was not authorised.
    """
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    provenance = (
        default_provenance_path(output)
        if provenance_output is None
        else provenance_output.expanduser().resolve()
    )
    for destination in (output, provenance):
        if destination.exists() and not force:
            message = f"Destination already exists; use --force to replace: {destination}"
            raise ManifestError(message)
    rows = derive_seed_evidence(source)
    write_tsv(output, rows, EVIDENCE_COLUMNS)
    evidence_sha256 = sha256_file(output)
    write_tsv(
        provenance,
        [
            {
                "asset": output.name,
                "source_path": source,
                "source_sha256": sha256_file(source),
                "evidence_sha256": evidence_sha256,
                "rows": len(rows),
            }
        ],
        ("asset", "source_path", "source_sha256", "evidence_sha256", "rows"),
    )
    return {
        "status": "built",
        "output": str(output),
        "provenance": str(provenance),
        "rows": len(rows),
        "sha256": evidence_sha256,
    }
