"""Typed generic job dispatch, checksummed artifacts and local/Slurm worker execution."""

from __future__ import annotations

import csv
import json
import logging
from importlib.metadata import version
from pathlib import Path
import shutil
import sys
import traceback
from typing import Mapping

import duckdb

from .analysis import REALIGN_FIELDS, align_family, index_fasta, run_command, subcluster
from .catalogue import (
    build_cluster_taxonomy,
    extract_clusters,
    open_catalogue,
    resolve_sequence_ids,
)
from .common import ResearchConfig, ResearchError, atomic_json, file_sha256, utc_now
from .deepclust_exchange import import_cluster
from .jobs import artifact_path, claim_job, finish_job, job_directory
from .providers import annotate_batch, predict_batch

LOGGER = logging.getLogger(__name__)


def prepare_input(*, config: ResearchConfig, job: Mapping[str, object], output: Path) -> Path:
    """Resolve only uploaded input or checksummed artifacts from completed jobs.

    Args:
        config: Workspace profile.
        job: Claimed job record with named parameters.
        output: Current owned job directory.

    Returns:
        Existing input protein FASTA; arbitrary browser-supplied filesystem paths are not accepted.

    Raises:
        ResearchError: If input was changed or the source artifact is unavailable.
    """
    uploaded = output / "input.fasta"
    if uploaded.is_file():
        request = json.loads((output / "request.json").read_text(encoding="utf-8"))
        if file_sha256(path=uploaded) != request["input_sha256"]:
            raise ResearchError("Uploaded protein input changed after job submission")
        return uploaded
    parameters = job["parameters"]
    if not isinstance(parameters.get("source_job"), str) or not isinstance(
        parameters.get("source_artifact"), str
    ):
        raise ResearchError("Select a protein FASTA or a completed source job artifact")
    path = artifact_path(
        workspace=config.workspace,
        job_id=parameters["source_job"],
        artifact=parameters["source_artifact"],
    )
    if path.suffix.lower() not in {".fa", ".faa", ".fasta"}:
        raise ResearchError("Selected input artifact must be protein FASTA")
    return path


def selected_input(
    *, config: ResearchConfig, source: Path, output: Path, parameters: Mapping[str, object]
) -> Path:
    """Create a complete selected-ID subset for annotation/model/search jobs when requested.

    Args:
        config: Workspace and sequence bounds.
        source: Uploaded or prior-job FASTA.
        output: Current job directory.
        parameters: Optional sequence_ids list; an empty list explicitly selects the whole input.

    Returns:
        Original input or an audited exact selected-ID FASTA.

    Raises:
        ResearchError: If a requested ID does not occur or the selection exceeds bounds.
    """
    identifiers = parameters.get("sequence_ids", [])
    if not isinstance(identifiers, list) or any(
        not isinstance(value, str) for value in identifiers
    ):
        raise ResearchError("sequence_ids must be an explicit list of protein identifiers")
    if not identifiers:
        return source
    if len(identifiers) > 100_000:
        raise ResearchError("Select at most 100000 exact protein identifiers per job")
    connection, _ = index_fasta(
        source=source, destination=output / "selection.sqlite", maximum=config.max_sequences
    )
    try:
        connection.execute("CREATE TABLE requested(id TEXT PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO requested VALUES (?)", [(value,) for value in sorted(set(identifiers))]
        )
        missing = connection.execute(
            "SELECT id FROM requested WHERE id NOT IN (SELECT id FROM sequences) LIMIT 1"
        ).fetchone()
        if missing:
            raise ResearchError(f"Requested protein is absent from the dataset: {missing[0]}")
        destination = output / "selected.fasta"
        with destination.open(mode="w", encoding="utf-8") as handle:
            for identifier, sequence in connection.execute(
                "SELECT id,sequence FROM sequences JOIN requested USING(id) ORDER BY id"
            ):
                handle.write(f">{identifier}\n{sequence}\n")
    finally:
        connection.close()
    return destination


def search_representatives(
    *, config: ResearchConfig, source: Path, output: Path
) -> dict[str, Path]:
    """Search representatives, keeping homology evidence separate from exact membership.

    Args:
        config: Installed DIAMOND and global representative database.
        source: Query protein FASTA.
        output: Owned job directory.

    Returns:
        Ranked representative-search hits with actual alignment statistics.

    Raises:
        ResearchError: If the search database is not configured.
    """
    if not config.centroid_database or not Path(config.centroid_database).is_file():
        raise ResearchError(
            "Configure a DIAMOND database of global cluster representatives for homology search"
        )
    connection, _ = index_fasta(
        source=source, destination=output / "queries.sqlite", maximum=10_000
    )
    normalised = output / "queries.fasta"
    try:
        with normalised.open(mode="w", encoding="utf-8") as handle:
            for identifier, sequence in connection.execute(
                "SELECT id,sequence FROM sequences ORDER BY id"
            ):
                handle.write(f">{identifier}\n{sequence}\n")
    finally:
        connection.close()
    command = [
        config.diamond,
        "blastp",
        "--db",
        config.centroid_database,
        "--query",
        str(normalised),
        "--out",
        str(output / "representative_hits.raw.tsv"),
        "--outfmt",
        "6",
        *REALIGN_FIELDS,
        "--threads",
        str(config.threads),
        "--max-target-seqs",
        "100",
        "--evalue",
        "1e-5",
        "--sensitive",
        "--query-cover",
        "50",
        "--subject-cover",
        "50",
    ]
    run_command(arguments=command, output=output, config=config)
    raw = output / "representative_hits.raw.tsv"
    with raw.open(encoding="utf-8") as handle:
        with (output / "representative_hits.tsv").open(
            mode="w", encoding="utf-8", newline=""
        ) as destination:
            writer = csv.writer(destination, delimiter="\t", lineterminator="\n")
            writer.writerow([*REALIGN_FIELDS, "mapping_evidence"])
            for fields in csv.reader(handle, delimiter="\t"):
                if len(fields) != len(REALIGN_FIELDS):
                    raise ResearchError("Representative search returned an invalid alignment row")
                writer.writerow([*fields, "HOMOLOGY_TO_GLOBAL_CENTROID_NOT_EXACT_MEMBERSHIP"])
    return {
        "representative_hits.tsv": output / "representative_hits.tsv",
        "queries.fasta": normalised,
    }


def family_metadata(
    *, config: ResearchConfig, source: Path, subcluster_id: str = ""
) -> dict[str, dict[str, object]]:
    """Collect reviewed tip metadata for bounded alignment input, without guessing species names.

    Args:
        config: Optional sequence taxonomy source.
        source: Protein FASTA selected for alignment.
        subcluster_id: Explicit selected family identifier.

    Returns:
        Reviewed taxonomic traits by exact input ID; unclassified IDs remain unclassified.
    """
    if not config.taxonomy:
        return {}
    from .common import iter_fasta

    identifiers = []
    for identifier, _ in iter_fasta(path=source):
        identifiers.append(identifier)
        if len(identifiers) > config.max_sequences:
            raise ResearchError("Taxonomic metadata selection exceeds max_sequences")
    with open_catalogue(config=config, require_index=False) as connection:
        result = connection.execute(
            "SELECT sequence_id,min(species) AS species,min(taxon_id) AS taxon_id "
            "FROM taxonomy WHERE taxon_id>0 AND sequence_id IN (SELECT unnest(?)) "
            "GROUP BY sequence_id "
            "HAVING count(DISTINCT taxon_id)=1",
            [identifiers],
        ).fetchdf()
    return {
        str(row["sequence_id"]): {
            "species": row["species"],
            "taxon_id": int(row["taxon_id"]),
            "subcluster_id": subcluster_id,
        }
        for row in result.to_dict(orient="records")
        if row["taxon_id"] is not None
    }


def execute_job(*, config: ResearchConfig, job: Mapping[str, object]) -> dict[str, Path]:
    """Dispatch a supported generic job and return only its scientific artifacts.

    Args:
        config: Trusted operator profile.
        job: Atomically claimed job record.

    Returns:
        Artifact names and paths, ready for checksum publication.

    Raises:
        ResearchError: If operation or input contracts are invalid.
    """
    output = job_directory(workspace=config.workspace, job_id=str(job["job_id"]))
    parameters = job["parameters"]
    operation = job["operation"]
    if operation == "resolve":
        identifiers = parameters.get("identifiers")
        if not isinstance(identifiers, list) or any(
            not isinstance(item, str) for item in identifiers
        ):
            raise ResearchError("Resolution requires an explicit identifiers list")
        with open_catalogue(config=config) as connection:
            result = resolve_sequence_ids(
                connection=connection, identifiers=identifiers, prefixes=config.identifier_prefixes
            )
        context = parameters.get("context", [])
        if context:
            import pandas as pd

            frame = pd.DataFrame(context)
            if "input_id" not in frame or not set(frame["input_id"]).issubset(identifiers):
                raise ResearchError("Source context must reference the submitted input IDs")
            result = result.merge(frame, how="left", on="input_id", validate="many_to_many")
        path = output / "global_cluster_mapping.tsv"
        result.to_csv(path, sep="\t", index=False)
        return {path.name: path}
    if operation == "retrieve":
        identifiers = parameters.get("cluster_ids")
        if not isinstance(identifiers, list) or any(
            not isinstance(value, str) for value in identifiers
        ):
            raise ResearchError("Retrieval requires an explicit cluster_ids list")
        return extract_clusters(config=config, cluster_ids=identifiers, output=output)
    if operation == "taxonomy_index":
        path = build_cluster_taxonomy(config=config, output=output)
        return {path.name: path}
    source = prepare_input(config=config, job=job, output=output)
    if operation == "import_cluster":
        return import_cluster(
            config=config,
            source=source,
            output=output,
            cluster_id=parameters.get("cluster_id", ""),
            source_label=parameters.get("source_label", ""),
            expected_members=parameters.get("expected_members"),
        )
    if operation == "subcluster":
        return subcluster(config=config, source=source, output=output, parameters=parameters)
    if operation == "align":
        membership = None
        if parameters.get("subcluster_id"):
            membership = artifact_path(
                workspace=config.workspace,
                job_id=parameters["source_job"],
                artifact="membership.tsv",
            )
        result = align_family(
            config=config,
            source=source,
            output=output,
            parameters=parameters,
            membership=membership,
        )
        if "tree.nwk" in result:
            from .analysis import auspice_dataset

            metadata = family_metadata(
                config=config,
                source=output / "sequences.fasta",
                subcluster_id=str(parameters.get("subcluster_id", "")),
            )
            dataset = auspice_dataset(
                newick=result["tree.nwk"].read_text(encoding="utf-8"),
                metadata=metadata,
                title="Protein family phylogeny",
            )
            atomic_json(path=output / "auspice.json", value=dataset)
        return result
    source = selected_input(config=config, source=source, output=output, parameters=parameters)
    if operation == "predict":
        return predict_batch(config=config, source=source, output=output, parameters=parameters)
    if operation == "annotate":
        return annotate_batch(config=config, source=source, output=output, parameters=parameters)
    if operation == "search":
        return search_representatives(config=config, source=source, output=output)
    raise ResearchError("Unsupported research operation")


def run_next_job(*, config: ResearchConfig, job_id: str | None = None) -> str | None:
    """Run one atomically claimed task and publish a complete checksummed manifest.

    Args:
        config: Operator profile.
        job_id: Optional exact queued job.

    Returns:
        Executed job identifier, or None when no queued job exists. Failed jobs
        retain their diagnostic files and never publish a successful manifest.
    """
    job = claim_job(workspace=config.workspace, job_id=job_id)
    if job is None:
        return None
    selected = str(job["job_id"])
    output = job_directory(workspace=config.workspace, job_id=selected)
    try:
        artifacts = execute_job(config=config, job=job)
        for name in (
            "request.json",
            "commands.jsonl",
            "worker.log",
            "annotation_tool_version.txt",
            "interpro_service_job.json",
        ):
            if (output / name).is_file():
                artifacts[name] = output / name
        manifest = {
            "schema_version": 1,
            "job_id": selected,
            "operation": job["operation"],
            "completed_at": utc_now(),
            "parameters": job["parameters"],
            "artifacts": {},
            "runtime": {
                "python": sys.version.split()[0],
                "application": version("e3-python-app"),
                "duckdb": version("duckdb"),
                "pyarrow": version("pyarrow"),
                "biopython": version("biopython"),
            },
            "data_sources": {
                name: {
                    "path": str(Path(getattr(config, name)).expanduser().resolve()),
                    "bytes": Path(getattr(config, name)).expanduser().stat().st_size,
                    "mtime_ns": Path(getattr(config, name)).expanduser().stat().st_mtime_ns,
                }
                for name in (
                    "index",
                    "sequences",
                    "sequence_map",
                    "taxonomy",
                    "cluster_taxonomy",
                    "identifier_bridge",
                )
                if getattr(config, name) and Path(getattr(config, name)).expanduser().is_file()
            },
        }
        for name, path in artifacts.items():
            if not path.is_file() or not path.resolve().is_relative_to(output.resolve()):
                raise ResearchError("Worker returned an absent or uncontained scientific artifact")
            manifest["artifacts"][name] = {
                "path": str(path.relative_to(output)),
                "sha256": file_sha256(path=path),
                "bytes": path.stat().st_size,
            }
        atomic_json(path=output / "manifest.json", value=manifest)
        if "auspice.json" in artifacts:
            datasets = config.workspace / "datasets"
            datasets.mkdir(exist_ok=True)
            shutil.copyfile(artifacts["auspice.json"], datasets / f"{selected}.json")
        finish_job(workspace=config.workspace, job_id=selected)
    except KeyboardInterrupt:
        finish_job(
            workspace=config.workspace,
            job_id=selected,
            error="Worker interrupted; inspect partial outputs before resubmitting",
        )
        raise
    except Exception as exc:
        diagnostic = f"{type(exc).__name__}: {exc}"
        with (output / "worker.log").open(mode="a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc())
        LOGGER.exception("Research job %s failed", selected)
        finish_job(workspace=config.workspace, job_id=selected, error=diagnostic)
    return selected
