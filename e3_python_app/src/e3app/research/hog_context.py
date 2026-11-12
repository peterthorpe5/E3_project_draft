"""Preserve published HOG provenance and exact member taxonomy across research jobs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping

import pandas as pd

from e3app.taxonomy import load_taxonomy_authority

from .common import ResearchError, iter_fasta
from .jobs import source_manifests

LOGGER = logging.getLogger(__name__)


def hog_source(*, workspace: Path | None, parameters: Mapping[str, object]) -> Mapping | None:
    """Find the nearest request that records a published HOG.

    Args:
        workspace: Optional workspace for following completed source jobs.
        parameters: Parameters of the current request.

    Returns:
        Saved parameters of the HOG selection, or None when no HOG was recorded.
    """
    if isinstance(parameters.get("e3_hog_id"), str) and parameters["e3_hog_id"].strip():
        return parameters
    source_job = parameters.get("source_job")
    if workspace is not None and isinstance(source_job, str):
        for manifest in source_manifests(workspace=workspace, source_job=source_job):
            source = manifest.get("parameters", {})
            if isinstance(source.get("e3_hog_id"), str) and source["e3_hog_id"].strip():
                return source
    return None


def job_hog(*, record: Mapping[str, object], workspace: Path | None = None) -> str:
    """Resolve a job's recorded HOG for display, including older descendant jobs.

    Args:
        record: Completed manifest or job summary.
        workspace: Optional workspace for following saved inputs.

    Returns:
        Recorded HOG identifier, or an empty string for unavailable provenance.
    """
    parameters = record.get("parameters")
    if not isinstance(parameters, Mapping):
        return ""
    try:
        source = hog_source(workspace=workspace, parameters=parameters)
    except ResearchError as exc:
        LOGGER.warning("Could not resolve HOG for job %s: %s", record.get("job_id"), exc)
        return ""
    return str(source["e3_hog_id"]) if source else ""


def hog_input_parameters(
    *, hog_id: str, members: pd.DataFrame, taxonomy_map: Path | None = None,
) -> dict[str, object]:
    """Snapshot selected released member IDs and species for worker-independent use.

    Args:
        hog_id: Exact selected published HOG.
        members: Selected sequence-bearing rows from the released HOG.
        taxonomy_map: Optional reviewed species-to-taxon mapping configured in E3.

    Returns:
        HOG ID, taxonomy source and exact member IDs grouped by recorded species.
    """
    authority = load_taxonomy_authority(taxonomy_map=taxonomy_map)
    taxon_ids = authority.species_taxonomy.set_index("source_species_name")["taxon_id"]
    return {
        "e3_hog_id": hog_id,
        "e3_taxonomy_source": authority.source_label,
        "e3_hog_members": {
            species: {
                "taxon_id": int(taxon_ids[species]) if species in taxon_ids else None,
                "sequence_ids": ids.tolist(),
            }
            for species, ids in members.groupby("member_species")["fasta_identifier"]
        },
    }


def hog_member_metadata(
    *, workspace: Path | None, parameters: Mapping[str, object], fasta: Path,
    aligned: bool = False,
) -> dict[str, dict[str, object]]:
    """Read recorded species for the exact IDs present in a HOG-derived FASTA.

    Args:
        workspace: Optional queue workspace for inherited HOG inputs.
        parameters: Current request parameters.
        fasta: Exact saved protein sequences for this job or its selected subset.
        aligned: Allow alignment gaps in the saved FASTA.

    Returns:
        Exact member IDs mapped to released species labels and optional reviewed taxon IDs.

    Raises:
        ResearchError: If the saved HOG metadata is malformed or ambiguous.
    """
    try:
        source = hog_source(workspace=workspace, parameters=parameters)
    except ResearchError as exc:
        LOGGER.warning("Saved HOG taxonomy ancestry is unavailable: %s", exc)
        return {}
    if not source or "e3_hog_members" not in source:
        return {}
    groups = source["e3_hog_members"]
    if not isinstance(groups, dict):
        raise ResearchError("Invalid saved HOG member metadata")
    metadata = {}
    for species, group in groups.items():
        if not isinstance(species, str) or not species.strip() or not isinstance(group, dict):
            raise ResearchError("Invalid saved HOG species metadata")
        taxon_id, identifiers = group.get("taxon_id"), group.get("sequence_ids")
        if taxon_id is not None and (type(taxon_id) is not int or taxon_id <= 0):
            raise ResearchError("Invalid saved HOG taxon ID")
        if not isinstance(identifiers, list):
            raise ResearchError("Invalid saved HOG sequence identifiers")
        for identifier in identifiers:
            if not isinstance(identifier, str) or not identifier or identifier in metadata:
                raise ResearchError("Saved HOG taxonomy requires distinct sequence identifiers")
            metadata[identifier] = {"species": species, "taxon_id": taxon_id}
    return {
        identifier: metadata[identifier]
        for identifier, _ in iter_fasta(path=fasta, aligned=aligned)
        if identifier in metadata
    }


def recover_hog_metadata(
    *, connection: object, hog_id: str, fasta: Path, taxonomy_map: Path | None = None,
) -> dict[str, dict[str, object]]:
    """Match older saved proteins to the current release using both member ID and sequence.

    Args:
        connection: Published E3 resource used for matching.
        hog_id: HOG identifier recovered from the job's saved provenance.
        fasta: Checksummed unaligned input used by the completed job.
        taxonomy_map: Optional reviewed species-to-taxon mapping configured in E3.

    Returns:
        Species evidence for exact matches to sequence-bearing released HOG members.
    """
    from e3app.external_hog import collect_external_hog_members

    members = collect_external_hog_members(
        connection=connection, hog_id=hog_id, maximum_members=10_000,
    )
    saved = dict(iter_fasta(path=fasta))
    matched = members.loc[
        members["sequence_status"].eq("AVAILABLE")
        & members["fasta_identifier"].map(saved).eq(members["protein_sequence"])
        & ~members["fasta_identifier"].duplicated(keep=False)
    ]
    parameters = hog_input_parameters(hog_id=hog_id, members=matched, taxonomy_map=taxonomy_map)
    metadata = hog_member_metadata(workspace=None, parameters=parameters, fasta=fasta)
    LOGGER.info("Matched %d of %d saved proteins in HOG %s", len(metadata), len(saved), hog_id)
    return metadata
