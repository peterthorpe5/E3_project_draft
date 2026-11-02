"""Verified taxonomy inheritance through retrieval, subclustering and alignment jobs."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .common import ResearchConfig, ResearchError, iter_fasta
from .jobs import artifact_path, job_directory


def _taxonomy_view(*, config: ResearchConfig, source_job: str, connection: object) -> bool:
    """Expose reviewed, unambiguous taxonomy as a lazy view when configured."""
    path = taxonomy_artifact(config=config, source_job=source_job) if source_job else None
    if path is None and config.taxonomy:
        path = Path(config.taxonomy).expanduser()
    if path is None:
        return False
    table = (connection.read_csv(str(path), delimiter="\t", header=True, all_varchar=True)
             if path.suffix == ".tsv" else connection.read_parquet(str(path)))
    if not {"sequence_id", "species", "taxon_id"}.issubset(table.columns):
        raise ResearchError("Reviewed taxonomy requires sequence_id/species/taxon_id")
    table.create_view(view_name="source_taxonomy")
    review = " AND upper(mapping_status)='REVIEWED'" if "mapping_status" in table.columns else ""
    connection.execute(
        "CREATE VIEW reviewed_taxonomy AS SELECT sequence_id,min(species) AS species,"
        "min(TRY_CAST(taxon_id AS BIGINT)) AS taxon_id FROM source_taxonomy "
        "WHERE TRY_CAST(taxon_id AS BIGINT)>0 AND trim(species)<>''" + review
        + " GROUP BY sequence_id HAVING count(DISTINCT TRY_CAST(taxon_id AS BIGINT))=1 "
        "AND count(DISTINCT species)=1"
    )
    return True


def taxonomy_artifact(*, config: ResearchConfig, source_job: str) -> Path | None:
    """Find reviewed per-sequence metadata in a bounded, checksummed source-job ancestry.

    Args:
        config: Current sidecar.
        source_job: Selected completed source job.

    Returns:
        Verified taxonomy artifact, or None when no ancestor provides it.

    Raises:
        ResearchError: If source ancestry is cyclic, excessive or corrupt.
    """
    seen = set()
    while source_job:
        if source_job in seen or len(seen) >= 20:
            raise ResearchError("Taxonomy source-job ancestry is cyclic or exceeds 20 jobs")
        seen.add(source_job)
        root = job_directory(workspace=config.workspace, job_id=source_job)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if "member_taxonomy.tsv" in manifest.get("artifacts", {}):
            return artifact_path(
                workspace=config.workspace, job_id=source_job, artifact="member_taxonomy.tsv",
            )
        source_job = str(manifest.get("parameters", {}).get("source_job", ""))
    return None


def reviewed_metadata(
    *, config: ResearchConfig, source: Path, source_job: str = "",
) -> dict[str, dict[str, object]]:
    """Select exact reviewed metadata for an explicitly bounded protein FASTA.

    Args:
        config: Operator taxonomy profile and resource bounds.
        source: Selected protein sequences.
        source_job: Optional source carrying remote-retrieved taxonomy.

    Returns:
        Positive taxon IDs and original species labels, keyed by exact sequence ID.

    Raises:
        ResearchError: If dimensions, source schemas or reviewed species labels conflict.
    """
    identifiers = []
    for identifier, _sequence in iter_fasta(path=source):
        identifiers.append(identifier)
        if len(identifiers) > config.max_sequences:
            raise ResearchError("Taxonomy selection exceeds max_sequences")
    connection = duckdb.connect(config={"memory_limit": f"{config.memory_gb}GB"})
    try:
        if not _taxonomy_view(config=config, source_job=source_job, connection=connection):
            return {}
        frame = connection.execute(
            "SELECT * FROM reviewed_taxonomy WHERE sequence_id IN (SELECT unnest(?))",
            [identifiers],
        ).fetchdf()
    finally:
        connection.close()
    return {str(row["sequence_id"]): {"species": str(row["species"]),
                                      "taxon_id": int(row["taxon_id"])}
            for row in frame.to_dict(orient="records")}


def subcluster_species(
    *, config: ResearchConfig, membership: Path, source: Path, source_job: str, output: Path,
) -> dict[str, Path]:
    """Publish complete reviewed/unclassified species counts for newly audited subclusters.

    Args:
        config: Current worker profile.
        membership: Audited sequence_id/subcluster_id table.
        source: Complete unaligned family FASTA.
        source_job: Source extraction or ancestor subclustering job.
        output: Owned result directory.

    Returns:
        Count table when taxonomy is available, otherwise no additional artifacts.
    """
    connection = duckdb.connect(config={"memory_limit": f"{config.memory_gb}GB"})
    try:
        if not _taxonomy_view(config=config, source_job=source_job, connection=connection):
            return {}
        connection.read_csv(
            str(membership), delimiter="\t", header=True, all_varchar=True,
        ).create_view(view_name="membership")
        result = connection.sql(
            "SELECT m.subcluster_id AS cluster_id,coalesce(t.species,'UNCLASSIFIED') AS species,"
            "t.taxon_id,count(*) AS member_count FROM membership m LEFT JOIN reviewed_taxonomy t "
            "USING(sequence_id) GROUP BY m.subcluster_id,t.species,t.taxon_id "
            "ORDER BY m.subcluster_id,member_count DESC"
        )
        path = output / "cluster_species.tsv"
        result.write_csv(str(path), sep="\t", header=True)
    finally:
        connection.close()
    return {path.name: path}
