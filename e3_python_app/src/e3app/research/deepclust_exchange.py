"""Exact identifier exchange and audited imports of selected DeepClust exports."""

from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path
from typing import Sequence

from .analysis import index_fasta
from .catalogue import sequence_aliases
from .common import ResearchConfig, ResearchError, bounded_number, file_sha256, write_tsv

LOGGER = logging.getLogger(__name__)
RETRIEVAL_URL = "https://github.com/drostlab/deepclust_dataretrieval"


def centroid_list(*, identifiers: Sequence[str]) -> str:
    """Format exact global centroid IDs for the upstream --centroid_file option.

    Args:
        identifiers: One to 1,000 global centroid IDs, including their source prefixes.

    Returns:
        Headerless text with one unique, unchanged centroid ID per line.

    Raises:
        ResearchError: If the request is empty, oversized or contains malformed IDs.
    """
    if isinstance(identifiers, (str, bytes)) or not 1 <= len(identifiers) <= 1000:
        raise ResearchError("Supply between 1 and 1000 exact global centroid IDs")
    values = []
    for identifier in identifiers:
        if not isinstance(identifier, str) or identifier != identifier.strip():
            raise ResearchError("Centroid IDs must be exact strings without surrounding spaces")
        sequence_aliases(identifier=identifier)
        values.append(identifier)
    return "\n".join(dict.fromkeys(values)) + "\n"


def import_cluster(
    *,
    config: ResearchConfig,
    source: Path,
    output: Path,
    cluster_id: str,
    source_label: str,
    expected_members: int | None = None,
) -> dict[str, Path]:
    """Import one per-cluster FASTA without accessing the global DeepClust database.

    Args:
        config: Workspace and maximum complete sequence count.
        source: Private snapshot of a --per-clust-output 1 FASTA export.
        output: New owned job directory, already containing the request and input.
        cluster_id: Exact global centroid ID; it must occur among the FASTA headers.
        source_label: User-declared export provenance, such as the release and provider.
        expected_members: Optional independently supplied published member count.

    Returns:
        Normalised FASTA, exact membership, export audit and length summary artifacts.

    Raises:
        ResearchError: If IDs repeat, the centroid is absent or a supplied count differs.
            A missing count leaves completeness explicitly unassessed.
    """
    centroid_list(identifiers=[cluster_id])
    if (
        not isinstance(source_label, str)
        or not source_label.strip()
        or len(source_label) > 2000
        or any(ord(character) < 32 or ord(character) == 127 for character in source_label)
    ):
        raise ResearchError("Supply a non-empty export source label without control characters")
    expected = (
        bounded_number(
            value=expected_members,
            label="Expected members",
            minimum=1,
            maximum=config.max_sequences,
            integer=True,
        )
        if expected_members is not None
        else None
    )
    artifacts = {
        name: output / name
        for name in ("cluster.fasta", "members.tsv", "clusters.tsv", "cluster_summary.tsv")
    }
    if any(path.exists() for path in [*artifacts.values(), output / "import.sqlite"]):
        raise ResearchError("Refusing to overwrite an existing cluster import")
    connection, count = index_fasta(
        source=source, destination=output / "import.sqlite", maximum=config.max_sequences
    )
    try:
        if (
            connection.execute("SELECT 1 FROM sequences WHERE id=?", (cluster_id,)).fetchone()
            is None
        ):
            raise ResearchError(
                "Exact centroid ID is absent from the FASTA. Use --per-clust-output 1 "
                "and preserve source prefixes; combined upstream output renames headers."
            )
        if expected is not None and count != expected:
            raise ResearchError("Imported member count differs from the supplied expected count")
        with artifacts["cluster.fasta"].open(mode="x", encoding="utf-8") as fasta:
            with artifacts["members.tsv"].open(mode="x", encoding="utf-8", newline="") as table:
                writer = csv.writer(table, delimiter="\t", lineterminator="\n")
                writer.writerow(["sequence_id", "cluster_id", "sequence_length", "sequence_sha256"])
                for identifier, sequence in connection.execute(
                    "SELECT id,sequence FROM sequences ORDER BY id"
                ):
                    sequence_aliases(identifier=identifier)
                    fasta.write(f">{identifier}\n{sequence}\n")
                    writer.writerow(
                        [
                            identifier,
                            cluster_id,
                            len(sequence),
                            hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                        ]
                    )
        minimum, maximum, mean = connection.execute(
            "SELECT min(length(sequence)),max(length(sequence)),avg(length(sequence)) "
            "FROM sequences"
        ).fetchone()
    finally:
        connection.close()
    audit = {
        "cluster_id": cluster_id,
        "imported_members": count,
        "expected_members": expected,
        "count_status": "MATCHES_SUPPLIED_COUNT" if expected is not None else "COUNT_NOT_SUPPLIED",
        "membership_evidence": "USER_SUPPLIED_PER_CLUSTER_EXPORT",
        "source_label": source_label.strip(),
        "input_sha256": file_sha256(path=source),
        "fasta_artifact": "cluster.fasta",
        "compatible_tool": RETRIEVAL_URL,
        "normalisation": "Upper case; whitespace and terminal stop symbols removed",
    }
    write_tsv(path=artifacts["clusters.tsv"], rows=[audit], columns=list(audit))
    summary = {
        "cluster_id": cluster_id,
        "sequence_count": count,
        "minimum_length": minimum,
        "maximum_length": maximum,
        "mean_length": mean,
        "scope": "IMPORTED_EXPORT_ONLY",
    }
    write_tsv(path=artifacts["cluster_summary.tsv"], rows=[summary], columns=list(summary))
    LOGGER.info("Imported selected DeepClust export %s (%d proteins)", cluster_id, count)
    return artifacts
