"""Native production adapters for reusable evidence and pre-structure ranking."""

from __future__ import annotations

import gzip
import json
import logging
import re
import shutil
import sqlite3
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import duckdb

from e3workflow.config import WorkflowConfig
from e3workflow.domain_annotations import (
    InterProSettings,
    flatten_interpro_results,
    retrieve_annotations,
)
from e3workflow.errors import StageError
from e3workflow.io_utils import read_tsv, sha256_file, write_tsv
from e3workflow.orthology_groups import (
    candidate_mapping_rows,
    choose_primary_groups,
    selected_group_members,
)
from e3workflow.resources import (
    EXPRESSION_RESOURCE_TYPES,
    read_resource_manifest,
)
from e3workflow.tabular import (
    copy_query_to_parquet,
    parquet_columns,
    parquet_row_count,
    quote_literal,
    write_records,
)

LOGGER = logging.getLogger("e3workflow.production")

CANDIDATE_REQUIRED_COLUMNS = frozenset(
    {
        "representative_id",
        "matched_seed_ids_calculated",
        "matched_seed_id_count",
        "reviewed_seed_count",
        "ubiquitin_go_positive_seed_count",
        "seed_with_exclusion_go_term_count",
        "strict_member_count",
        "strict_named_species_count",
    }
)

DOMAIN_HIT_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "member_accession",
    "species_column",
    "raw_identifier",
    "source_database",
    "entry_accession",
    "entry_name",
    "entry_type",
    "integrated_interpro_accession",
    "location_start",
    "location_end",
    "discontinuity_status",
    "model",
    "score",
    "protein_length",
    "protein_source_database",
    "organism_tax_id",
    "in_alphafold",
    "catalogue_match",
    "e3_family",
    "evidence_role",
    "interpretation",
    "retrieval_status",
    "interpro_version",
)

DOMAIN_SUMMARY_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "member_accession",
    "species_column",
    "raw_identifier",
    "identifier_mapping_status",
    "annotation_availability_status",
    "annotation_status_detail",
    "pfam_hit_count",
    "interpro_hit_count",
    "domain_hit_count",
    "e3_domain_hit_count",
    "e3_families",
    "e3_domain_accessions",
    "domain_support_status",
    "interpro_version",
)

EXPRESSION_MAPPING_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "member_accession",
    "member_identifier",
    "species_column",
    "mapping_status",
    "mapping_tier",
    "matched_gene_count",
    "matched_gene_ids",
    "matched_gene_names",
    "matched_aliases",
    "reason",
)

EXPRESSION_SUMMARY_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "member_accession",
    "member_identifier",
    "species_column",
    "mapping_status",
    "gene_id",
    "gene_name",
    "experiment_count",
    "selected_expression_units",
    "expression_unit_count",
    "context_count",
    "positive_context_count",
    "positive_context_fraction",
    "minimum_context_expression_value",
    "maximum_expression_value",
    "median_expression_value",
    "broad_expression_supported",
    "evidence_status",
)

EXPRESSION_CONTEXT_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "member_accession",
    "member_identifier",
    "species_column",
    "gene_id",
    "gene_name",
    "experiment_accession",
    "expression_unit",
    "sample_or_condition",
    "atlas_group_label",
    "assay_ids",
    "assay_count",
    "organism_part",
    "developmental_stage",
    "genotype",
    "cultivar",
    "treatment",
    "condition",
    "expression_context",
    "metadata_status",
    "expression_value_statistic",
    "expression_value",
    "expression_minimum",
    "expression_lower_quartile",
    "expression_median",
    "expression_upper_quartile",
    "expression_maximum",
    "expression_positive",
)
EXPRESSION_CONTEXT_PREVIEW_LIMIT = 10_000


def find_one(root: Path, name: str) -> Path:
    """Find exactly one named file below a completed stage root."""
    matches = sorted(Path(root).rglob(name))
    if len(matches) != 1:
        raise StageError(
            f"Expected exactly one {name!r} below {root}; observed {len(matches)}"
        )
    return matches[0]


def find_orthology_table(*, root: Path, name: str) -> Path:
    """Resolve one public orthology table without scanning component provenance.

    The master workflow supports both its ``orthology/tables`` component-adapter contract and the
    direct ``tables`` contract used by other external adapters. Independently restartable
    orthology components retain internal stage products below ``orthology/stages``; those files
    are provenance copies rather than additional downstream authorities.

    Args:
        root: Completed master stage-05 directory.
        name: Basename of the required public table.

    Returns:
        The single non-empty table at a supported public contract path.

    Raises:
        StageError: If ``name`` is not a basename, or zero or multiple public contract files
            exist.
    """
    relative_name = Path(name)
    if not name or relative_name.name != name or name in {".", ".."}:
        raise StageError(f"Orthology table name must be a safe basename: {name!r}")
    stage_root = Path(root)
    candidates = (
        stage_root / "orthology" / "tables" / name,
        stage_root / "tables" / name,
    )
    matches = [path for path in candidates if path.is_file() and path.stat().st_size > 0]
    if len(matches) != 1:
        expected = ", ".join(str(path) for path in candidates)
        raise StageError(
            f"Expected exactly one non-empty public orthology table {name!r}; "
            f"observed {len(matches)} at supported paths: {expected}"
        )
    return matches[0]


def split_accessions(value: Any) -> tuple[str, ...]:
    """Return unique accessions from one semicolon-delimited candidate field."""
    if value is None:
        return ()
    return tuple(sorted({token.strip() for token in str(value).split(";") if token.strip()}))


def candidate_accessions(path: Path) -> tuple[str, ...]:
    """Return every unique accession represented in candidate-evidence Parquet."""
    source = Path(path).expanduser().resolve()
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            "SELECT DISTINCT TRIM(token) AS accession "
            f"FROM read_parquet({quote_literal(source)}), "
            "UNNEST(string_split(CAST(matched_seed_ids_calculated AS VARCHAR), ';')) AS t(token) "
            "WHERE TRIM(token) <> '' ORDER BY accession"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)
    except duckdb.Error as exc:
        raise StageError(f"Could not read candidate accessions from {source}: {exc}") from exc
    finally:
        connection.close()


def run_reused_discovery_stage(
    *, config: WorkflowConfig, stage_root: Path
) -> None:
    """Record the validated external Discovery Engine authority without recomputing it."""
    candidate_manifest = config.resources.candidate_evidence_manifest
    candidate_path = config.resources.candidate_evidence
    if candidate_manifest is None or candidate_path is None:
        raise StageError("Reused discovery requires candidate evidence and its provenance manifest")
    try:
        manifest = json.loads(candidate_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"Candidate evidence manifest is not readable JSON: {exc}") from exc
    write_tsv(
        stage_root / "discovery_authority.tsv",
        [
            {
                "authority": "completed_e3_discovery_engine_and_candidate_evidence",
                "candidate_evidence": candidate_path,
                "candidate_evidence_sha256": sha256_file(candidate_path),
                "candidate_manifest": candidate_manifest,
                "candidate_manifest_sha256": sha256_file(candidate_manifest),
                "manifest_package_version": manifest.get("package_version", ""),
                "reuse_decision": "validated_external_authority_not_recomputed",
                "scientific_limit": (
                    "E3-seeded sequence clustering is candidate evidence, not proof that every "
                    "member is an E3 ligase"
                ),
            }
        ],
        (
            "authority",
            "candidate_evidence",
            "candidate_evidence_sha256",
            "candidate_manifest",
            "candidate_manifest_sha256",
            "manifest_package_version",
            "reuse_decision",
            "scientific_limit",
        ),
    )


def run_candidate_evidence_stage(
    *, config: WorkflowConfig, stage_root: Path
) -> None:
    """Validate and publish the compact candidate-evidence authority."""
    source = config.resources.candidate_evidence
    if source is None:
        raise StageError("inputs.candidate_evidence is required")
    columns = parquet_columns(path=source)
    missing = sorted(CANDIDATE_REQUIRED_COLUMNS.difference(columns))
    if missing:
        raise StageError("Candidate evidence is missing columns: " + ", ".join(missing))
    row_count = parquet_row_count(path=source)
    if row_count < 1:
        raise StageError("Candidate evidence contains no rows")
    accessions = candidate_accessions(path=source)
    if not accessions:
        raise StageError("Candidate evidence contains no parsed candidate accessions")
    destination = stage_root / "candidate_evidence" / "e3_cluster_candidate_evidence.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256_file(destination) != sha256_file(source):
        raise StageError("Published candidate evidence differs from its controlled source")
    write_tsv(
        stage_root / "candidate_evidence_summary.tsv",
        [
            {
                "row_count": row_count,
                "column_count": len(columns),
                "candidate_accession_count": len(accessions),
                "source_path": source,
                "source_sha256": sha256_file(source),
                "published_relative_path": destination.relative_to(stage_root),
            }
        ],
        (
            "row_count",
            "column_count",
            "candidate_accession_count",
            "source_path",
            "source_sha256",
            "published_relative_path",
        ),
    )


ORTHOFINDER_REQUIRED_RELATIVE_PATHS = (
    "WorkingDirectory/SpeciesIDs.txt",
    "WorkingDirectory/SequenceIDs.txt",
    "Orthogroups/Orthogroups.tsv",
    "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
    "Species_Tree/SpeciesTree_rooted_node_labels.txt",
)


def _validate_tar_members(archive: tarfile.TarFile, extraction_root: Path) -> None:
    """Reject archive members and links that would escape the extraction directory."""
    root = extraction_root.resolve()
    for member in archive.getmembers():
        member_path = (root / member.name).resolve()
        if not member_path.is_relative_to(root):
            raise StageError(f"Unsafe path in OrthoFinder archive: {member.name}")
        if member.issym() or member.islnk():
            link_path = (member_path.parent / member.linkname).resolve()
            if not link_path.is_relative_to(root):
                raise StageError(
                    f"Unsafe link in OrthoFinder archive: {member.name} -> {member.linkname}"
                )


def _find_orthofinder_result_root(extraction_root: Path) -> Path:
    """Find exactly one extracted directory satisfying the OrthoFinder 2.5.5 contract."""
    candidates: list[Path] = []
    for orthogroups in extraction_root.rglob("Orthogroups/Orthogroups.tsv"):
        root = orthogroups.parent.parent
        if all((root / relative).is_file() for relative in ORTHOFINDER_REQUIRED_RELATIVE_PATHS):
            candidates.append(root)
    unique = sorted(set(path.resolve() for path in candidates))
    if len(unique) != 1:
        raise StageError(
            "Expected exactly one complete OrthoFinder result in the archive; observed "
            f"{len(unique)}"
        )
    return unique[0]


def run_reused_orthofinder_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Extract and validate the checksum-bound reviewed Results_Feb26 authority."""
    archive_path = config.resources.orthofinder_archive
    if archive_path is None:
        raise StageError("Reused stage 04 requires inputs.orthofinder_archive")
    extraction_root = stage_root / "archive_extraction"
    extraction_root.mkdir(parents=True)
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            _validate_tar_members(archive, extraction_root)
            archive.extractall(extraction_root, filter="fully_trusted")
    except (OSError, tarfile.TarError) as exc:
        raise StageError(f"Could not extract OrthoFinder archive {archive_path}: {exc}") from exc
    result_root = _find_orthofinder_result_root(extraction_root)
    published_root = stage_root / "Results"
    shutil.move(str(result_root), published_root)
    shutil.rmtree(extraction_root)
    validation_rows = []
    for relative in ORTHOFINDER_REQUIRED_RELATIVE_PATHS:
        path = published_root / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise StageError(f"Extracted OrthoFinder authority lacks {relative}")
        validation_rows.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "status": "VALID",
            }
        )
    _, input_rows = read_tsv(config.run_root / "00_inputs" / "input_validation.tsv")
    archive_records = [
        row for row in input_rows if row.get("manifest") == "orthofinder_archive"
    ]
    if len(archive_records) != 1:
        raise StageError("Stage 00 did not publish one OrthoFinder archive validation record")
    archive_sha256 = archive_records[0]["sha256"]
    write_tsv(
        stage_root / "orthofinder_reuse_validation.tsv",
        validation_rows,
        ("relative_path", "size_bytes", "sha256", "status"),
    )
    write_tsv(
        stage_root / "orthofinder_authority.tsv",
        [
            {
                "mode": "reused_reviewed_archive",
                "archive_path": archive_path,
                "archive_size_bytes": archive_path.stat().st_size,
                "archive_sha256": archive_sha256,
                "published_results": published_root.relative_to(stage_root),
                "orthofinder_version": "2.5.5",
                "decision_basis": (
                    "project-reviewed Results_Feb26 phylogeny was preferred for this dataset"
                ),
            }
        ],
        (
            "mode",
            "archive_path",
            "archive_size_bytes",
            "archive_sha256",
            "published_results",
            "orthofinder_version",
            "decision_basis",
        ),
    )


def parse_fasta_identifier(header: str) -> tuple[str, ...]:
    """Return conservative candidate-accession tokens from one FASTA header."""
    primary = header.split(maxsplit=1)[0]
    tokens = {primary}
    parts = primary.split("|")
    if len(parts) >= 3 and parts[0].lower() in {"sp", "tr"}:
        tokens.add(parts[1])
    return tuple(sorted(token for token in tokens if token))


def iter_fasta(path: Path) -> Iterator[tuple[str, str]]:
    """Yield header and sequence pairs from one plain or gzip-compressed FASTA."""
    source = Path(path).expanduser().resolve()
    opener = gzip.open if source.suffix == ".gz" else Path.open
    kwargs = {"mode": "rt", "encoding": "utf-8"} if source.suffix == ".gz" else {
        "mode": "r",
        "encoding": "utf-8",
    }
    header = ""
    sequence_parts: list[str] = []
    with opener(source, **kwargs) as handle:  # type: ignore[arg-type]
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header:
                    yield header, "".join(sequence_parts)
                header = line[1:]
                sequence_parts = []
            elif not header:
                raise StageError(f"Sequence data precede the first FASTA header: {source}")
            else:
                sequence_parts.append(line)
    if header:
        yield header, "".join(sequence_parts)


def load_domain_catalogue(path: Path) -> dict[str, dict[str, str]]:
    """Load the curated E3-domain catalogue by versionless Pfam accession."""
    fields, rows = read_tsv(path)
    required = {
        "pfam_accession",
        "domain_name",
        "e3_family",
        "evidence_role",
        "interpretation",
        "source_url",
    }
    missing = sorted(required.difference(fields))
    if missing:
        raise StageError("E3 domain catalogue is missing columns: " + ", ".join(missing))
    catalogue: dict[str, dict[str, str]] = {}
    for row in rows:
        accession = row["pfam_accession"].split(".", maxsplit=1)[0]
        if not accession or accession in catalogue:
            raise StageError(f"Empty or duplicate Pfam accession in domain catalogue: {accession}")
        catalogue[accession] = row
    if not catalogue:
        raise StageError("E3 domain catalogue contains no records")
    return catalogue


def _load_annotation_manifest(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load checksum-validated InterPro cache JSON files from a resource manifest."""
    records = read_resource_manifest(
        path=path,
        allowed_resource_types={"interpro_annotation_cache"},
        verify_checksums=True,
    )
    payloads: dict[str, dict[str, Any]] = {}
    inventory: list[dict[str, Any]] = []
    for record in records:
        source = Path(record["path"])
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageError(f"Could not read InterPro annotation cache {source}: {exc}") from exc
        accession = str(payload.get("requested_accession", "")).strip().upper()
        status = str(payload.get("retrieval_status", ""))
        if not accession or accession in payloads:
            raise StageError(f"Empty or duplicate accession in annotation manifest: {source}")
        if status not in {"ANNOTATED", "PROTEIN_WITHOUT_ENTRIES", "NOT_FOUND"}:
            raise StageError(f"Unsupported retrieval status {status!r} in {source}")
        payloads[accession] = payload
        inventory.append(
            {
                "candidate_accession": accession,
                "retrieval_status": status,
                "network_used": False,
                "cache_path": source,
                "cache_sha256": record["sha256"],
                "retrieved_at_utc": payload.get("retrieved_at_utc", ""),
                "interpro_version": payload.get("release", {}).get(
                    "interpro_version", ""
                ),
                "result_count": len(payload.get("results", [])),
                "error": payload.get("error", ""),
            }
        )
    return payloads, inventory


def _domain_group_members(config: WorkflowConfig) -> list[dict[str, Any]]:
    """Return target-species members of each selected candidate OrthoFinder group."""
    orthology_root = config.run_root / "05_orthology"
    mapping = find_orthology_table(
        root=orthology_root,
        name="candidate_membership_mapping.parquet",
    )
    orthogroups = find_orthology_table(
        root=orthology_root,
        name="orthogroup_membership.parquet",
    )
    hierarchical = find_orthology_table(
        root=orthology_root,
        name="hierarchical_membership.parquet",
    )
    selected, _ = choose_primary_groups(mapping_rows=candidate_mapping_rows(path=mapping))
    if not selected:
        raise StageError("No candidate cluster could be assigned an exact OrthoFinder group")
    members = selected_group_members(
        selected=selected,
        orthogroup_membership=orthogroups,
        hierarchical_membership=hierarchical,
        target_species=config.analysis.prioritisation.target_species,
    )
    if not members:
        raise StageError("Selected OrthoFinder groups contain no configured target-species members")
    return members


def _catalogue_annotation(
    *, hit: Mapping[str, Any], catalogue: Mapping[str, Mapping[str, str]]
) -> Mapping[str, str]:
    """Return an E3 catalogue record matching a Pfam or integrated InterPro accession."""
    candidates = (
        str(hit.get("entry_accession", "")).split(".", maxsplit=1)[0],
        str(hit.get("integrated_interpro_accession", "")).split(".", maxsplit=1)[0],
    )
    for accession in candidates:
        if accession in catalogue:
            return catalogue[accession]
    return {}


def _downloaded_domain_records(
    *,
    members: Sequence[Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
    catalogue: Mapping[str, Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build per-hit and per-member domain tables with tri-state availability semantics."""
    hits: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for member in members:
        accession = str(member.get("member_accession", "")).strip().upper()
        payload = payloads.get(accession, {}) if accession else {}
        retrieval_status = str(payload.get("retrieval_status", "IDENTIFIER_UNPARSED"))
        release = str(payload.get("release", {}).get("interpro_version", ""))
        flattened = flatten_interpro_results(payload)
        member_hits: list[dict[str, Any]] = []
        for flattened_hit in flattened:
            annotation = _catalogue_annotation(hit=flattened_hit, catalogue=catalogue)
            hit = {
                "cluster_id": member["cluster_id"],
                "primary_group_type": member["primary_group_type"],
                "primary_group_id": member["primary_group_id"],
                "member_accession": accession,
                "species_column": member["species_column"],
                "raw_identifier": member["raw_identifier"],
                **flattened_hit,
                "catalogue_match": bool(annotation),
                "e3_family": annotation.get("e3_family", ""),
                "evidence_role": annotation.get("evidence_role", ""),
                "interpretation": annotation.get("interpretation", ""),
                "retrieval_status": retrieval_status,
                "interpro_version": release,
            }
            hits.append(hit)
            member_hits.append(hit)
        e3_hits = [hit for hit in member_hits if hit["catalogue_match"]]
        annotation_available = retrieval_status in {
            "ANNOTATED",
            "PROTEIN_WITHOUT_ENTRIES",
        }
        if e3_hits:
            domain_status = "SUPPORTED"
        elif annotation_available:
            domain_status = "ANNOTATED_NO_CATALOGUED_E3_DOMAIN"
        else:
            domain_status = "ANNOTATION_UNAVAILABLE"
        detail = {
            "ANNOTATED": "InterPro protein entry annotations retrieved",
            "PROTEIN_WITHOUT_ENTRIES": "protein record exists but has no InterPro entries",
            "NOT_FOUND": "accession was not found by the InterPro protein API",
            "CACHE_UNAVAILABLE": "no cached annotation and network retrieval was disabled",
            "DOWNLOAD_ERROR": "InterPro retrieval failed after bounded retries",
            "IDENTIFIER_UNPARSED": (
                "OrthoFinder member identifier did not yield a UniProt accession"
            ),
        }.get(retrieval_status, f"unrecognised retrieval status: {retrieval_status}")
        summaries.append(
            {
                "cluster_id": member["cluster_id"],
                "primary_group_type": member["primary_group_type"],
                "primary_group_id": member["primary_group_id"],
                "member_accession": accession,
                "species_column": member["species_column"],
                "raw_identifier": member["raw_identifier"],
                "identifier_mapping_status": member["identifier_mapping_status"],
                "annotation_availability_status": (
                    "AVAILABLE" if annotation_available else "UNAVAILABLE"
                ),
                "annotation_status_detail": detail,
                "pfam_hit_count": sum(
                    hit["source_database"] == "pfam" for hit in member_hits
                ),
                "interpro_hit_count": sum(
                    hit["source_database"] == "interpro" for hit in member_hits
                ),
                "domain_hit_count": len(member_hits),
                "e3_domain_hit_count": len(e3_hits),
                "e3_families": ";".join(
                    sorted({str(hit["e3_family"]) for hit in e3_hits})
                ),
                "e3_domain_accessions": ";".join(
                    sorted({str(hit["entry_accession"]) for hit in e3_hits})
                ),
                "domain_support_status": domain_status,
                "interpro_version": release,
            }
        )
    return hits, summaries


def cache_domain_annotations(*, config: WorkflowConfig) -> dict[str, Any]:
    """Prefetch annotations after stage 05 so stage 06 can run from the persistent cache."""
    if config.analysis.domains.mode != "interpro_api_cache":
        raise StageError("cache-domain-annotations requires interpro_api_cache mode")
    cache_root = config.resources.domain_cache_root
    if cache_root is None:
        raise StageError("inputs.domain_cache_root is required")
    members = _domain_group_members(config=config)
    accessions = sorted(
        {
            str(member["member_accession"]).strip().upper()
            for member in members
            if str(member["member_accession"]).strip()
        }
    )
    settings = config.analysis.domains
    payloads, inventory = retrieve_annotations(
        accessions=accessions,
        settings=InterProSettings(
            api_base_url=settings.interpro_api_base_url,
            cache_root=cache_root,
            allow_network=settings.allow_network,
            workers=settings.workers,
            request_timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
            retry_delay_seconds=settings.retry_delay_seconds,
        ),
    )
    status_counts: dict[str, int] = defaultdict(int)
    for payload in payloads.values():
        status_counts[str(payload.get("retrieval_status", "UNKNOWN"))] += 1
    return {
        "status": "cache_complete",
        "cache_root": str(cache_root),
        "selected_group_member_count": len(members),
        "unique_accession_count": len(accessions),
        "inventory_count": len(inventory),
        "retrieval_status_counts": dict(sorted(status_counts.items())),
    }


def run_domain_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Reuse downloaded InterPro/Pfam annotations without treating missing data as absence."""
    catalogue_path = config.resources.e3_domain_catalogue
    if catalogue_path is None:
        raise StageError("Domain stage requires inputs.e3_domain_catalogue")
    members = _domain_group_members(config=config)
    accessions = sorted(
        {
            str(member["member_accession"]).strip().upper()
            for member in members
            if str(member["member_accession"]).strip()
        }
    )
    settings = config.analysis.domains
    if settings.mode == "downloaded_manifest":
        manifest = config.resources.domain_annotation_manifest
        if manifest is None:
            raise StageError("downloaded_manifest mode requires inputs.domain_annotation_manifest")
        payloads, inventory = _load_annotation_manifest(path=manifest)
    else:
        cache_root = config.resources.domain_cache_root
        if cache_root is None:
            raise StageError("interpro_api_cache mode requires inputs.domain_cache_root")
        payloads, inventory = retrieve_annotations(
            accessions=accessions,
            settings=InterProSettings(
                api_base_url=settings.interpro_api_base_url,
                cache_root=cache_root,
                allow_network=settings.allow_network,
                workers=settings.workers,
                request_timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.max_retries,
                retry_delay_seconds=settings.retry_delay_seconds,
            ),
        )
    catalogue = load_domain_catalogue(path=catalogue_path)
    hits, summaries = _downloaded_domain_records(
        members=members,
        payloads=payloads,
        catalogue=catalogue,
    )
    tables = stage_root / "tables"
    write_records(
        tsv_path=tables / "domain_hits.tsv",
        parquet_path=tables / "domain_hits.parquet",
        fieldnames=DOMAIN_HIT_FIELDS,
        records=hits,
    )
    write_records(
        tsv_path=tables / "domain_summary.tsv",
        parquet_path=tables / "domain_summary.parquet",
        fieldnames=DOMAIN_SUMMARY_FIELDS,
        records=summaries,
    )
    write_tsv(
        stage_root / "raw" / "interpro_cache_inventory.tsv",
        inventory,
        (
            "candidate_accession",
            "retrieval_status",
            "network_used",
            "cache_path",
            "cache_sha256",
            "retrieved_at_utc",
            "interpro_version",
            "result_count",
            "error",
        ),
    )
    statuses: dict[str, int] = defaultdict(int)
    for summary in summaries:
        statuses[str(summary["domain_support_status"])] += 1
    write_tsv(
        stage_root / "qc" / "domain_validation.tsv",
        [
            {
                "selected_group_count": len({row["cluster_id"] for row in members}),
                "target_group_member_count": len(members),
                "unique_accession_count": len(accessions),
                "domain_hit_count": len(hits),
                "supported_member_count": statuses["SUPPORTED"],
                "annotated_without_catalogued_e3_domain_count": statuses[
                    "ANNOTATED_NO_CATALOGUED_E3_DOMAIN"
                ],
                "annotation_unavailable_member_count": statuses[
                    "ANNOTATION_UNAVAILABLE"
                ],
                "missing_data_policy": (
                    "ANNOTATION_UNAVAILABLE is excluded from biological-negative denominators"
                ),
                "interpretation": (
                    "downloaded Pfam/InterPro support is independent family evidence and does "
                    "not establish complete architecture or E3 activity"
                ),
            }
        ],
        (
            "selected_group_count",
            "target_group_member_count",
            "unique_accession_count",
            "domain_hit_count",
            "supported_member_count",
            "annotated_without_catalogued_e3_domain_count",
            "annotation_unavailable_member_count",
            "missing_data_policy",
            "interpretation",
        ),
    )


def _normalise_species(value: str) -> str:
    """Normalise an organism label to the Expression Atlas partition convention."""
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", value).strip()
    words = re.findall(r"[A-Za-z][A-Za-z0-9.-]*", cleaned)
    normalised = "_".join(words[:2]) if len(words) >= 2 else "_".join(words)
    aliases = {
        "Lycopersicon_esculentum": "Solanum_lycopersicum",
        "Oryza_sativa_subsp": "Oryza_sativa",
    }
    return aliases.get(normalised, normalised)


def _split_aliases(value: str) -> tuple[str, ...]:
    """Split one inherited gene-name field into stable exact-match tokens."""
    return tuple(sorted({token for token in re.split(r"[;|,\s]+", value) if token}))


def _find_e3_sqlite_table(connection: sqlite3.Connection) -> tuple[str, set[str]]:
    """Find the inherited SQLite table containing the required E3 identity columns."""
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    required = {"entry", "gene_names", "organism"}
    candidates: list[tuple[str, set[str]]] = []
    for table in tables:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            continue
        columns = {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if required.issubset(columns):
            candidates.append((table, columns))
    if len(candidates) != 1:
        raise StageError(
            "Expected exactly one inherited SQLite E3 table containing entry, gene_names and "
            f"organism; observed {len(candidates)}"
        )
    return candidates[0]


def build_candidate_aliases(
    *, sqlite_path: Path, accessions: Iterable[str]
) -> list[dict[str, str]]:
    """Build audited protein/gene aliases from the inherited SQLite authority."""
    requested = set(accessions)
    connection = sqlite3.connect(f"file:{Path(sqlite_path).resolve()}?mode=ro", uri=True)
    try:
        table, columns = _find_e3_sqlite_table(connection=connection)
        selected = ["entry", "gene_names", "organism"]
        selected.extend(
            column
            for column in ("entry_name", "protein_names", "category")
            if column in columns
        )
        sql = "SELECT " + ", ".join(f'"{column}"' for column in selected) + f' FROM "{table}"'
        rows = connection.execute(sql).fetchall()
    except sqlite3.Error as exc:
        raise StageError(f"Could not read inherited SQLite aliases: {exc}") from exc
    finally:
        connection.close()
    aliases: list[dict[str, str]] = []
    for values in rows:
        row = dict(zip(selected, values))
        entry = "" if row.get("entry") is None else str(row["entry"]).strip()
        if entry not in requested:
            continue
        species = _normalise_species(str(row.get("organism") or ""))
        direct = [("candidate_accession", entry, "1")]
        entry_name = str(row.get("entry_name") or "").strip()
        if entry_name:
            direct.append(("entry_name", entry_name, "3"))
        for identifier_type, identifier_value, tier in direct:
            aliases.append(
                {
                    "candidate_accession": entry,
                    "species_column": species,
                    "identifier_type": identifier_type,
                    "identifier_value": identifier_value,
                    "mapping_tier": tier,
                    "source_table": table,
                }
            )
        for token in _split_aliases(str(row.get("gene_names") or "")):
            aliases.append(
                {
                    "candidate_accession": entry,
                    "species_column": species,
                    "identifier_type": "gene_name",
                    "identifier_value": token,
                    "mapping_tier": "2",
                    "source_table": table,
                }
            )
    unique = {
        (
            row["candidate_accession"],
            row["species_column"],
            row["identifier_type"],
            row["identifier_value"].upper(),
        ): row
        for row in aliases
        if row["identifier_value"]
    }
    return [unique[key] for key in sorted(unique)]


def build_group_member_aliases(
    *, members: Sequence[Mapping[str, Any]], sqlite_aliases: Sequence[Mapping[str, str]]
) -> list[dict[str, str]]:
    """Combine OrthoFinder identifiers and inherited aliases for each selected group member."""
    sqlite_by_accession: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for alias in sqlite_aliases:
        sqlite_by_accession[str(alias["candidate_accession"]).upper()].append(alias)
    records: list[dict[str, str]] = []
    for member in members:
        accession = str(member.get("member_accession", "")).strip().upper()
        common = {
            "cluster_id": str(member["cluster_id"]),
            "primary_group_type": str(member["primary_group_type"]),
            "primary_group_id": str(member["primary_group_id"]),
            "member_accession": accession,
            "member_identifier": str(member["member_identifier"]),
            "species_column": str(member["species_column"]),
        }
        candidate_aliases: list[tuple[str, str, str, str]] = []
        raw_identifier = str(member.get("raw_identifier", "")).strip()
        if raw_identifier:
            candidate_aliases.append(
                ("orthofinder_raw_identifier", raw_identifier, "1", "orthofinder_membership")
            )
            first_token = raw_identifier.split(maxsplit=1)[0]
            candidate_aliases.append(
                ("orthofinder_primary_token", first_token, "1", "orthofinder_membership")
            )
        parsed_entry = str(member.get("parsed_entry", "")).strip()
        if parsed_entry:
            candidate_aliases.append(
                ("parsed_entry", parsed_entry, "2", "orthofinder_membership")
            )
        if accession:
            candidate_aliases.append(
                ("uniprot_accession", accession, "2", "orthofinder_membership")
            )
        for alias in sqlite_by_accession.get(accession, []):
            candidate_aliases.append(
                (
                    str(alias["identifier_type"]),
                    str(alias["identifier_value"]),
                    str(alias["mapping_tier"]),
                    str(alias["source_table"]),
                )
            )
        for identifier_type, identifier_value, tier, source_table in candidate_aliases:
            if not identifier_value:
                continue
            records.append(
                {
                    **common,
                    "identifier_type": identifier_type,
                    "identifier_value": identifier_value,
                    "mapping_tier": tier,
                    "source_table": source_table,
                }
            )
    unique = {
        (
            row["cluster_id"],
            row["primary_group_type"],
            row["primary_group_id"],
            row["member_accession"],
            row["member_identifier"],
            row["species_column"],
            row["identifier_value"].upper(),
        ): row
        for row in records
    }
    return [unique[key] for key in sorted(unique)]


def _create_alias_table(
    *, connection: duckdb.DuckDBPyConnection, aliases: Sequence[Mapping[str, str]]
) -> None:
    """Create and populate the small in-memory candidate alias table."""
    connection.execute(
        "CREATE TABLE candidate_aliases (cluster_id VARCHAR, primary_group_type VARCHAR, "
        "primary_group_id VARCHAR, member_accession VARCHAR, member_identifier VARCHAR, "
        "species_column VARCHAR, "
        "identifier_type VARCHAR, identifier_value VARCHAR, mapping_tier INTEGER, "
        "source_table VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO candidate_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["cluster_id"],
                row["primary_group_type"],
                row["primary_group_id"],
                row["member_accession"],
                row["member_identifier"],
                row["species_column"],
                row["identifier_type"],
                row["identifier_value"],
                int(row["mapping_tier"]),
                row["source_table"],
            )
            for row in aliases
        ],
    )


def _parquet_list_literal(paths: Sequence[Path]) -> str:
    """Return a DuckDB list literal for controlled Parquet paths."""
    if not paths:
        raise StageError("At least one Parquet path is required")
    return "[" + ", ".join(quote_literal(path) for path in paths) + "]"


def _expression_paths_for_species(
    *,
    manifest_records: Sequence[Mapping[str, str]],
    selected_species: Iterable[str],
    resource_type: str = "atlas_expression_long",
) -> tuple[Path, ...]:
    """Return only expression partitions needed by selected orthology-group members.

    Args:
        manifest_records: Validated Expression Atlas resource-manifest records.
        selected_species: Species labels present among selected group members.

    Returns:
        Sorted, de-duplicated paths for relevant ``atlas_expression_long`` partitions.
    """
    species_keys = {
        str(species).strip().upper()
        for species in selected_species
        if str(species).strip()
    }
    return tuple(
        sorted(
            {
                Path(record["path"])
                for record in manifest_records
                if record["resource_type"] == resource_type
                and record["species_column"].strip().upper() in species_keys
            }
        )
    )


def _configure_expression_duckdb(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: WorkflowConfig,
    stage_root: Path,
) -> tuple[int, Path]:
    """Bound DuckDB memory and enable disk spilling within the atomic stage directory.

    DuckDB's memory limit does not include every allocation made by DuckDB, Python or linked
    libraries. Reserving one quarter of the Slurm request prevents the analytical engine from
    deliberately approaching the scheduler's hard cgroup limit.

    Args:
        connection: Open DuckDB connection used by Stage 07.
        config: Validated workflow configuration.
        stage_root: Atomic Stage 07 working directory.

    Returns:
        Configured memory limit in MiB and the spill-directory path.
    """
    stage = config.stage("07_expression")
    memory_limit_mb = max(256, stage.memory_mb * 3 // 4)
    spill_directory = (Path(stage_root) / "duckdb_spill").resolve()
    spill_directory.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads = {stage.threads}")
    connection.execute(f"SET memory_limit = '{memory_limit_mb}MB'")
    connection.execute(f"SET temp_directory = {quote_literal(spill_directory)}")
    connection.execute("SET preserve_insertion_order = false")
    return memory_limit_mb, spill_directory


def _create_empty_expression_view(
    *, connection: duckdb.DuckDBPyConnection
) -> None:
    """Create a typed empty Atlas relation when selected species lack a compatible partition."""
    connection.execute(
        "CREATE TEMP VIEW atlas_expression AS SELECT "
        "CAST(NULL AS VARCHAR) AS experiment_accession, "
        "CAST(NULL AS VARCHAR) AS species_column, "
        "CAST(NULL AS VARCHAR) AS gene_id, "
        "CAST(NULL AS VARCHAR) AS gene_name, "
        "CAST(NULL AS VARCHAR) AS sample_or_condition, "
        "CAST(NULL AS DOUBLE) AS expression_value, "
        "CAST(NULL AS DOUBLE) AS expression_minimum, "
        "CAST(NULL AS DOUBLE) AS expression_lower_quartile, "
        "CAST(NULL AS DOUBLE) AS expression_median, "
        "CAST(NULL AS DOUBLE) AS expression_upper_quartile, "
        "CAST(NULL AS DOUBLE) AS expression_maximum, "
        "CAST(NULL AS VARCHAR) AS expression_value_statistic, "
        "CAST(NULL AS VARCHAR) AS expression_summary_type, "
        "CAST(NULL AS VARCHAR) AS expression_unit, "
        "CAST(NULL AS VARCHAR) AS source_file, "
        "CAST(NULL AS VARCHAR) AS source_file_sha256 WHERE FALSE"
    )


def _create_empty_sample_metadata_view(
    *, connection: duckdb.DuckDBPyConnection
) -> None:
    """Create a typed empty sample-metadata relation for context joins."""
    connection.execute(
        "CREATE TEMP VIEW atlas_sample_metadata AS SELECT "
        "CAST(NULL AS VARCHAR) AS experiment_accession, "
        "CAST(NULL AS VARCHAR) AS species_column, "
        "CAST(NULL AS VARCHAR) AS sample_or_condition, "
        "CAST(NULL AS VARCHAR) AS atlas_group_label, "
        "CAST(NULL AS VARCHAR) AS assay_ids, "
        "CAST(NULL AS INTEGER) AS assay_count, "
        "CAST(NULL AS VARCHAR) AS organism_part, "
        "CAST(NULL AS VARCHAR) AS developmental_stage, "
        "CAST(NULL AS VARCHAR) AS genotype, "
        "CAST(NULL AS VARCHAR) AS cultivar, "
        "CAST(NULL AS VARCHAR) AS treatment, "
        "CAST(NULL AS VARCHAR) AS condition, "
        "CAST(NULL AS VARCHAR) AS source_file, "
        "CAST(NULL AS VARCHAR) AS source_file_sha256, "
        "CAST(NULL AS VARCHAR) AS configuration_file, "
        "CAST(NULL AS VARCHAR) AS configuration_file_sha256, "
        "CAST(NULL AS VARCHAR) AS expression_file_sha256 WHERE FALSE"
    )


def run_expression_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Map candidate protein aliases to Atlas genes and quantify expression breadth."""
    manifest_path = config.resources.expression_manifest
    sqlite_path = config.resources.inherited_sqlite
    if manifest_path is None or sqlite_path is None:
        raise StageError("Expression stage requires expression_manifest and inherited_sqlite")
    manifest_records = read_resource_manifest(
        path=manifest_path,
        allowed_resource_types=EXPRESSION_RESOURCE_TYPES,
        verify_checksums=True,
    )
    all_expression_paths = [
        Path(record["path"])
        for record in manifest_records
        if record["resource_type"] == "atlas_expression_long"
    ]
    if not all_expression_paths:
        raise StageError(
            "Expression resource manifest contains no atlas_expression_long files"
        )
    members = _domain_group_members(config=config)
    selected_species = {
        str(member["species_column"]).strip()
        for member in members
        if str(member["species_column"]).strip()
    }
    expression_paths = _expression_paths_for_species(
        manifest_records=manifest_records,
        selected_species=selected_species,
    )
    sample_metadata_paths = _expression_paths_for_species(
        manifest_records=manifest_records,
        selected_species=selected_species,
        resource_type="atlas_sample_metadata_wide",
    )
    accessions = sorted(
        {
            str(member["member_accession"]).strip().upper()
            for member in members
            if str(member["member_accession"]).strip()
        }
    )
    sqlite_aliases = build_candidate_aliases(
        sqlite_path=sqlite_path, accessions=accessions
    )
    aliases = build_group_member_aliases(
        members=members, sqlite_aliases=sqlite_aliases
    )
    if not aliases:
        raise StageError(
            "No selected group-member identifiers were available for expression mapping"
        )
    tables = stage_root / "tables"
    LOGGER.info(
        "Expression partition pruning selected %s of %s expression files for %s member species",
        len(expression_paths),
        len(all_expression_paths),
        len(selected_species),
    )
    write_records(
        tsv_path=tables / "candidate_identifier_aliases.tsv",
        parquet_path=tables / "candidate_identifier_aliases.parquet",
        fieldnames=(
            "cluster_id",
            "primary_group_type",
            "primary_group_id",
            "member_accession",
            "member_identifier",
            "species_column",
            "identifier_type",
            "identifier_value",
            "mapping_tier",
            "source_table",
        ),
        records=aliases,
    )
    connection = duckdb.connect(":memory:")
    memory_limit_mb = 0
    spill_directory = Path(stage_root) / "duckdb_spill"
    try:
        memory_limit_mb, spill_directory = _configure_expression_duckdb(
            connection=connection,
            config=config,
            stage_root=stage_root,
        )
        LOGGER.info(
            "DuckDB expression engine configured with threads=%s, memory_limit_mb=%s and "
            "spill_directory=%s",
            config.stage("07_expression").threads,
            memory_limit_mb,
            spill_directory,
        )
        _create_alias_table(connection=connection, aliases=aliases)
        schema_sql = (
            "SELECT * FROM read_parquet("
            + _parquet_list_literal(all_expression_paths)
            + ", union_by_name=true, hive_partitioning=true)"
        )
        expression_columns = {
            str(row[0])
            for row in connection.execute(f"DESCRIBE {schema_sql}").fetchall()
        }
        required = {
            "experiment_accession",
            "species_column",
            "gene_id",
            "gene_name",
            "sample_or_condition",
            "expression_value",
            "expression_minimum",
            "expression_lower_quartile",
            "expression_median",
            "expression_upper_quartile",
            "expression_maximum",
            "expression_value_statistic",
            "expression_summary_type",
            "expression_unit",
            "source_file",
            "source_file_sha256",
        }
        missing = sorted(required.difference(expression_columns))
        if missing:
            raise StageError("Expression Parquet is missing columns: " + ", ".join(missing))
        if expression_paths:
            expression_sql = (
                "SELECT * FROM read_parquet("
                + _parquet_list_literal(expression_paths)
                + ", union_by_name=true, hive_partitioning=true)"
            )
            connection.execute(
                f"CREATE TEMP VIEW atlas_expression AS {expression_sql}"
            )
        else:
            _create_empty_expression_view(connection=connection)
        if sample_metadata_paths:
            metadata_sql = (
                "SELECT * FROM read_parquet("
                + _parquet_list_literal(sample_metadata_paths)
                + ", union_by_name=true, hive_partitioning=true)"
            )
            metadata_columns = {
                str(row[0])
                for row in connection.execute(f"DESCRIBE {metadata_sql}").fetchall()
            }
            required_metadata = {
                "experiment_accession",
                "species_column",
                "sample_or_condition",
                "atlas_group_label",
                "assay_ids",
                "assay_count",
                "organism_part",
                "developmental_stage",
                "genotype",
                "cultivar",
                "treatment",
                "condition",
                "source_file",
                "source_file_sha256",
                "configuration_file",
                "configuration_file_sha256",
                "expression_file_sha256",
            }
            missing_metadata = sorted(required_metadata.difference(metadata_columns))
            if missing_metadata:
                raise StageError(
                    "Expression sample metadata is missing columns: "
                    + ", ".join(missing_metadata)
                )
            connection.execute(
                f"CREATE TEMP VIEW atlas_sample_metadata AS {metadata_sql}"
            )
        else:
            _create_empty_sample_metadata_view(connection=connection)
        duplicate_metadata_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM (SELECT species_column, experiment_accession, "
                "sample_or_condition, COUNT(*) AS row_count FROM atlas_sample_metadata "
                "WHERE sample_or_condition <> '' GROUP BY ALL HAVING COUNT(*) <> 1)"
            ).fetchone()[0]
        )
        if duplicate_metadata_count:
            raise StageError(
                "Expression metadata contains duplicate group keys: "
                f"{duplicate_metadata_count} duplicated species/experiment/group keys"
            )
        invalid_unit_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM atlas_expression WHERE "
                "upper(CAST(expression_unit AS VARCHAR)) NOT IN ('TPM', 'FPKM')"
            ).fetchone()[0]
        )
        if invalid_unit_count:
            raise StageError(
                "Expression input contains unsupported units: "
                f"{invalid_unit_count} rows are not TPM or FPKM"
            )
        invalid_expression_provenance_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM atlas_expression WHERE "
                "COALESCE(CAST(source_file AS VARCHAR), '') = '' OR "
                "NOT regexp_full_match(COALESCE(CAST(source_file_sha256 AS VARCHAR), ''), "
                "'^[0-9a-f]{64}$')"
            ).fetchone()[0]
        )
        if invalid_expression_provenance_count:
            raise StageError(
                "Expression input contains invalid raw-source provenance: "
                f"{invalid_expression_provenance_count} rows"
            )
        conflicting_expression_hash_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM (SELECT source_file FROM atlas_expression "
                "GROUP BY source_file HAVING COUNT(DISTINCT source_file_sha256) <> 1)"
            ).fetchone()[0]
        )
        if conflicting_expression_hash_count:
            raise StageError(
                "Expression input maps one source file to conflicting checksums: "
                f"{conflicting_expression_hash_count} files"
            )
        invalid_metadata_provenance_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM atlas_sample_metadata WHERE "
                "COALESCE(CAST(source_file AS VARCHAR), '') = '' OR "
                "NOT regexp_full_match(COALESCE(CAST(source_file_sha256 AS VARCHAR), ''), "
                "'^[0-9a-f]{64}$') OR (COALESCE(CAST(configuration_file AS VARCHAR), '') "
                "<> '' AND NOT regexp_full_match(COALESCE(CAST("
                "configuration_file_sha256 AS VARCHAR), ''), '^[0-9a-f]{64}$')) OR "
                "(regexp_full_match(CAST(sample_or_condition AS VARCHAR), '^g[1-9][0-9]*$') "
                "AND NOT regexp_full_match(COALESCE(CAST(expression_file_sha256 AS "
                "VARCHAR), ''), '^[0-9a-f]{64}$'))"
            ).fetchone()[0]
        )
        if invalid_metadata_provenance_count:
            raise StageError(
                "Expression metadata contain invalid raw-source provenance: "
                f"{invalid_metadata_provenance_count} rows"
            )
        connection.execute(
            "CREATE TEMP TABLE expression_unit_selection AS SELECT "
            "upper(CAST(species_column AS VARCHAR)) AS species_key, "
            "CAST(experiment_accession AS VARCHAR) AS experiment_accession, "
            "CASE WHEN bool_or(upper(CAST(expression_unit AS VARCHAR)) = 'TPM') "
            "THEN 'TPM' WHEN bool_or(upper(CAST(expression_unit AS VARCHAR)) = 'FPKM') "
            "THEN 'FPKM' ELSE NULL END AS selected_expression_unit "
            "FROM atlas_expression GROUP BY ALL"
        )
        connection.execute(
            "CREATE TEMP VIEW atlas_expression_preferred AS SELECT e.*, "
            "s.selected_expression_unit, "
            "s.selected_expression_unit = 'FPKM' AS used_fpkm_fallback "
            "FROM atlas_expression e JOIN expression_unit_selection s ON "
            "upper(CAST(e.species_column AS VARCHAR)) = s.species_key AND "
            "CAST(e.experiment_accession AS VARCHAR) = s.experiment_accession "
            "WHERE upper(CAST(e.expression_unit AS VARCHAR)) = "
            "s.selected_expression_unit"
        )
        invalid_summary_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM atlas_expression_preferred WHERE "
                "expression_value < 0 OR NOT isfinite(expression_value) OR "
                "CASE WHEN expression_summary_type = 'atlas_five_number_summary' THEN ("
                "expression_value_statistic <> 'median' OR expression_minimum IS NULL OR "
                "expression_lower_quartile IS NULL OR expression_median IS NULL OR "
                "expression_upper_quartile IS NULL OR expression_maximum IS NULL OR "
                "expression_value <> expression_median OR NOT (expression_minimum <= "
                "expression_lower_quartile AND expression_lower_quartile <= "
                "expression_median AND expression_median <= expression_upper_quartile "
                "AND expression_upper_quartile <= expression_maximum)) WHEN "
                "expression_summary_type IN ('single_value', 'atlas_zero_code') THEN NOT ("
                "expression_minimum IS NULL AND expression_lower_quartile IS NULL AND "
                "expression_median IS NULL AND expression_upper_quartile IS NULL AND "
                "expression_maximum IS NULL) ELSE TRUE END"
            ).fetchone()[0]
        )
        if invalid_summary_count:
            raise StageError(
                "Expression input violates the Atlas summary-statistic contract: "
                f"{invalid_summary_count} preferred rows are invalid"
            )
        duplicate_context_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM (SELECT species_column, experiment_accession, "
                "gene_id, sample_or_condition, COUNT(*) AS row_count "
                "FROM atlas_expression_preferred GROUP BY ALL HAVING COUNT(*) <> 1)"
            ).fetchone()[0]
        )
        if duplicate_context_count:
            raise StageError(
                "Preferred expression input contains duplicate gene contexts: "
                f"{duplicate_context_count} duplicated keys"
            )
        connection.execute(
            "CREATE TEMP TABLE candidate_identifier_keys AS "
            "SELECT DISTINCT upper(species_column) AS species_key, "
            "upper(identifier_value) AS identifier_key FROM candidate_aliases "
            "WHERE identifier_value <> ''"
        )
        connection.execute(
            "CREATE TEMP TABLE atlas_candidate_genes AS SELECT DISTINCT species_key, "
            "gene_id, gene_name FROM (SELECT "
            "upper(CAST(e.species_column AS VARCHAR)) AS species_key, "
            "CAST(e.gene_id AS VARCHAR) AS gene_id, "
            "CAST(e.gene_name AS VARCHAR) AS gene_name "
            "FROM atlas_expression_preferred e JOIN candidate_identifier_keys k "
            "ON upper(CAST(e.species_column AS VARCHAR)) = k.species_key "
            "AND upper(CAST(e.gene_id AS VARCHAR)) = k.identifier_key "
            "UNION ALL SELECT "
            "upper(CAST(e.species_column AS VARCHAR)) AS species_key, "
            "CAST(e.gene_id AS VARCHAR) AS gene_id, "
            "CAST(e.gene_name AS VARCHAR) AS gene_name "
            "FROM atlas_expression_preferred e JOIN candidate_identifier_keys k "
            "ON upper(CAST(e.species_column AS VARCHAR)) = k.species_key "
            "AND upper(COALESCE(CAST(e.gene_name AS VARCHAR), '')) = k.identifier_key)"
        )
        connection.execute(
            "CREATE TEMP TABLE alias_gene_matches AS "
            "SELECT DISTINCT a.cluster_id, a.primary_group_type, a.primary_group_id, "
            "a.member_accession, a.member_identifier, a.species_column, a.identifier_type, "
            "a.identifier_value, "
            "a.mapping_tier, CAST(e.gene_id AS VARCHAR) AS gene_id, "
            "CAST(e.gene_name AS VARCHAR) AS gene_name "
            "FROM candidate_aliases a JOIN atlas_candidate_genes e "
            "ON e.species_key = upper(a.species_column) "
            "AND (upper(e.gene_id) = upper(a.identifier_value) "
            "OR upper(COALESCE(e.gene_name, '')) = upper(a.identifier_value))"
        )
        mapping_query = (
            "WITH candidates AS (SELECT DISTINCT cluster_id, primary_group_type, "
            "primary_group_id, member_accession, member_identifier, species_column "
            "FROM candidate_aliases), "
            "best_tier AS (SELECT cluster_id, primary_group_type, primary_group_id, "
            "member_accession, member_identifier, species_column, "
            "MIN(mapping_tier) AS mapping_tier "
            "FROM alias_gene_matches GROUP BY ALL), "
            "best_matches AS (SELECT m.* FROM alias_gene_matches m JOIN best_tier b USING "
            "(cluster_id, primary_group_type, primary_group_id, member_accession, "
            "member_identifier, "
            "species_column, mapping_tier)), summaries AS (SELECT cluster_id, "
            "primary_group_type, primary_group_id, member_accession, member_identifier, "
            "species_column, "
            "MIN(mapping_tier) AS mapping_tier, "
            "COUNT(DISTINCT gene_id) AS matched_gene_count, "
            "string_agg(DISTINCT gene_id, ';' ORDER BY gene_id) AS matched_gene_ids, "
            "string_agg(DISTINCT COALESCE(gene_name, ''), ';' ORDER BY COALESCE(gene_name, '')) "
            "AS matched_gene_names, string_agg(DISTINCT identifier_value, ';' ORDER BY "
            "identifier_value) AS matched_aliases FROM best_matches GROUP BY cluster_id, "
            "primary_group_type, primary_group_id, member_accession, member_identifier, "
            "species_column) "
            "SELECT c.cluster_id, c.primary_group_type, c.primary_group_id, "
            "c.member_accession, c.member_identifier, c.species_column, CASE "
            "WHEN s.matched_gene_count IS NULL THEN 'NOT_MAPPED' WHEN s.matched_gene_count = 1 "
            "THEN 'MAPPED_UNIQUE' ELSE 'AMBIGUOUS' END AS mapping_status, "
            "COALESCE(CAST(s.mapping_tier AS VARCHAR), '') AS mapping_tier, "
            "COALESCE(s.matched_gene_count, 0) AS matched_gene_count, "
            "COALESCE(s.matched_gene_ids, '') AS matched_gene_ids, "
            "COALESCE(s.matched_gene_names, '') AS matched_gene_names, "
            "COALESCE(s.matched_aliases, '') AS matched_aliases, CASE "
            "WHEN s.matched_gene_count IS NULL THEN 'no_exact_identifier_or_gene_name_match' "
            "WHEN s.matched_gene_count = 1 THEN 'unique_best_tier_exact_match' "
            "ELSE 'multiple_genes_at_best_mapping_tier' END AS reason "
            "FROM candidates c LEFT JOIN summaries s USING (cluster_id, primary_group_type, "
            "primary_group_id, member_accession, member_identifier, species_column)"
        )
        connection.execute(
            f"CREATE TEMP TABLE candidate_mapping AS {mapping_query}"
        )
        copy_query_to_parquet(
            connection=connection,
            query="SELECT * FROM candidate_mapping",
            path=tables / "candidate_expression_mapping.parquet",
        )
        summary_query = (
            "WITH unique_mapping AS (SELECT cluster_id, primary_group_type, primary_group_id, "
            "member_accession, member_identifier, species_column, matched_gene_ids AS "
            "gene_id FROM candidate_mapping WHERE mapping_status = 'MAPPED_UNIQUE'), "
            "evidence AS (SELECT m.cluster_id, m.primary_group_type, m.primary_group_id, "
            "m.member_accession, m.member_identifier, m.species_column, m.gene_id, "
            "max(CAST(e.gene_name AS VARCHAR)) AS gene_name, "
            "COUNT(DISTINCT e.experiment_accession) AS experiment_count, "
            "string_agg(DISTINCT e.selected_expression_unit, ';' ORDER BY "
            "e.selected_expression_unit) AS selected_expression_units, "
            "COUNT(DISTINCT e.selected_expression_unit) AS expression_unit_count, "
            "COUNT(*) AS context_count, COUNT(*) FILTER (WHERE e.expression_value >= "
            f"{config.analysis.expression.minimum_expression_value}) AS positive_context_count, "
            "COUNT(*) FILTER (WHERE e.expression_value >= "
            f"{config.analysis.expression.minimum_expression_value})::DOUBLE / "
            "NULLIF(COUNT(*), 0) AS positive_context_fraction, "
            "CASE WHEN COUNT(DISTINCT e.selected_expression_unit) = 1 THEN "
            "min(e.expression_value) ELSE NULL END AS minimum_context_expression_value, "
            "CASE WHEN COUNT(DISTINCT e.selected_expression_unit) = 1 THEN "
            "max(e.expression_value) ELSE NULL END AS maximum_expression_value, "
            "CASE WHEN COUNT(DISTINCT e.selected_expression_unit) = 1 THEN "
            "median(e.expression_value) ELSE NULL END AS median_expression_value "
            "FROM unique_mapping m JOIN atlas_expression_preferred e ON "
            "upper(CAST(e.species_column AS VARCHAR)) = upper(m.species_column) AND "
            "upper(CAST(e.gene_id AS VARCHAR)) = upper(m.gene_id) GROUP BY "
            "m.cluster_id, m.primary_group_type, m.primary_group_id, m.member_accession, "
            "m.member_identifier, m.species_column, m.gene_id) SELECT m.cluster_id, "
            "m.primary_group_type, m.primary_group_id, m.member_accession, "
            "m.member_identifier, m.species_column, m.mapping_status, "
            "COALESCE(e.gene_id, '') AS gene_id, COALESCE(e.gene_name, '') AS gene_name, "
            "CASE WHEN m.mapping_status = 'MAPPED_UNIQUE' THEN "
            "COALESCE(e.experiment_count, 0) ELSE NULL END AS experiment_count, "
            "CASE WHEN m.mapping_status = 'MAPPED_UNIQUE' THEN "
            "COALESCE(e.selected_expression_units, '') ELSE NULL END AS "
            "selected_expression_units, CASE WHEN m.mapping_status = 'MAPPED_UNIQUE' THEN "
            "COALESCE(e.expression_unit_count, 0) ELSE NULL END AS expression_unit_count, "
            "CASE WHEN m.mapping_status = 'MAPPED_UNIQUE' THEN COALESCE(e.context_count, 0) "
            "ELSE NULL END AS context_count, CASE WHEN m.mapping_status = 'MAPPED_UNIQUE' "
            "THEN COALESCE(e.positive_context_count, 0) ELSE NULL END AS "
            "positive_context_count, e.positive_context_fraction, "
            "e.minimum_context_expression_value, e.maximum_expression_value, "
            "e.median_expression_value, CASE WHEN m.mapping_status <> 'MAPPED_UNIQUE' OR "
            "e.context_count IS NULL THEN NULL WHEN e.positive_context_fraction >= "
            f"{config.analysis.expression.broad_positive_fraction} THEN true ELSE false END "
            "AS broad_expression_supported, CASE WHEN m.mapping_status <> 'MAPPED_UNIQUE' "
            "THEN m.mapping_status WHEN e.context_count IS NULL THEN "
            "'NO_EXPRESSION_RECORDS' WHEN e.positive_context_fraction >= "
            f"{config.analysis.expression.broad_positive_fraction} THEN "
            "'BROAD_EXPRESSION_SUPPORTED' ELSE 'LIMITED_OR_ZERO_EXPRESSION' END AS "
            "evidence_status FROM candidate_mapping m LEFT JOIN evidence e USING "
            "(cluster_id, primary_group_type, primary_group_id, member_accession, "
            "member_identifier, species_column)"
        )
        connection.execute(
            f"CREATE TEMP TABLE candidate_expression_summary AS {summary_query}"
        )
        context_query = (
            "WITH unique_mapping AS (SELECT cluster_id, primary_group_type, "
            "primary_group_id, member_accession, member_identifier, species_column, "
            "matched_gene_ids AS gene_id FROM candidate_mapping WHERE mapping_status = "
            "'MAPPED_UNIQUE'), joined AS (SELECT m.cluster_id, m.primary_group_type, "
            "m.primary_group_id, m.member_accession, m.member_identifier, m.species_column, "
            "m.gene_id, CAST(e.gene_name AS VARCHAR) AS gene_name, "
            "CAST(e.experiment_accession AS VARCHAR) AS experiment_accession, "
            "CAST(e.selected_expression_unit AS VARCHAR) AS expression_unit, "
            "CAST(e.sample_or_condition AS VARCHAR) AS sample_or_condition, "
            "COALESCE(CAST(meta.atlas_group_label AS VARCHAR), '') AS atlas_group_label, "
            "COALESCE(CAST(meta.assay_ids AS VARCHAR), '') AS assay_ids, "
            "COALESCE(CAST(meta.assay_count AS INTEGER), 0) AS assay_count, "
            "COALESCE(CAST(meta.organism_part AS VARCHAR), '') AS organism_part, "
            "COALESCE(CAST(meta.developmental_stage AS VARCHAR), '') AS "
            "developmental_stage, COALESCE(CAST(meta.genotype AS VARCHAR), '') AS genotype, "
            "COALESCE(CAST(meta.cultivar AS VARCHAR), '') AS cultivar, "
            "COALESCE(CAST(meta.treatment AS VARCHAR), '') AS treatment, "
            "COALESCE(CAST(meta.condition AS VARCHAR), '') AS condition, "
            "COALESCE(NULLIF(CAST(meta.organism_part AS VARCHAR), ''), "
            "NULLIF(CAST(meta.condition AS VARCHAR), ''), "
            "NULLIF(CAST(meta.atlas_group_label AS VARCHAR), ''), "
            "CAST(e.sample_or_condition AS VARCHAR), 'UNSPECIFIED') AS expression_context, "
            "CASE WHEN meta.sample_or_condition IS NULL THEN 'METADATA_NOT_MAPPED' "
            "WHEN COALESCE(CAST(meta.organism_part AS VARCHAR), '') = '' THEN "
            "'MAPPED_WITHOUT_TISSUE' ELSE 'MAPPED_WITH_TISSUE' END AS metadata_status, "
            "CAST(e.expression_value_statistic AS VARCHAR) AS expression_value_statistic, "
            "CAST(e.expression_value AS DOUBLE) AS expression_value, "
            "CAST(e.expression_minimum AS DOUBLE) AS expression_minimum, "
            "CAST(e.expression_lower_quartile AS DOUBLE) AS expression_lower_quartile, "
            "CAST(e.expression_median AS DOUBLE) AS expression_median, "
            "CAST(e.expression_upper_quartile AS DOUBLE) AS expression_upper_quartile, "
            "CAST(e.expression_maximum AS DOUBLE) AS expression_maximum, "
            "CAST(e.expression_value AS DOUBLE) >= "
            f"{config.analysis.expression.minimum_expression_value} AS expression_positive "
            "FROM unique_mapping m JOIN atlas_expression_preferred e ON "
            "upper(CAST(e.species_column AS VARCHAR)) = "
            "upper(m.species_column) AND upper(CAST(e.gene_id AS VARCHAR)) = "
            "upper(m.gene_id) LEFT JOIN atlas_sample_metadata meta ON "
            "upper(CAST(meta.species_column AS VARCHAR)) = upper(m.species_column) AND "
            "CAST(meta.experiment_accession AS VARCHAR) = "
            "CAST(e.experiment_accession AS VARCHAR) AND "
            "CAST(meta.sample_or_condition AS VARCHAR) = "
            "CAST(e.sample_or_condition AS VARCHAR) AND "
            "CAST(meta.expression_file_sha256 AS VARCHAR) = "
            "CAST(e.source_file_sha256 AS VARCHAR)) SELECT * FROM joined"
        )
        connection.execute(
            f"CREATE TEMP TABLE candidate_expression_context_summary AS {context_query}"
        )
        copy_query_to_parquet(
            connection=connection,
            query="SELECT * FROM candidate_expression_summary",
            path=tables / "candidate_expression_summary.parquet",
        )
        copy_query_to_parquet(
            connection=connection,
            query="SELECT * FROM candidate_expression_context_summary",
            path=tables / "candidate_expression_context_summary.parquet",
        )
        mapping_rows = connection.execute(
            "SELECT * FROM candidate_mapping "
            "ORDER BY cluster_id, species_column, member_accession"
        ).fetchall()
        mapping_columns = [str(item[0]) for item in connection.description]
        summary_rows = connection.execute(
            "SELECT * FROM candidate_expression_summary "
            "ORDER BY cluster_id, species_column, member_accession"
        ).fetchall()
        summary_columns = [str(item[0]) for item in connection.description]
        context_rows = connection.execute(
            "SELECT * FROM candidate_expression_context_summary ORDER BY "
            "cluster_id, species_column, member_accession, experiment_accession, "
            f"expression_context LIMIT {EXPRESSION_CONTEXT_PREVIEW_LIMIT}"
        ).fetchall()
        context_columns = [str(item[0]) for item in connection.description]
        context_total_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM candidate_expression_context_summary"
            ).fetchone()[0]
        )
        organism_part_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT organism_part) FROM "
                "candidate_expression_context_summary WHERE organism_part <> ''"
            ).fetchone()[0]
        )
        mapped_tissue_context_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM candidate_expression_context_summary WHERE "
                "metadata_status = 'MAPPED_WITH_TISSUE'"
            ).fetchone()[0]
        )
        metadata_unmapped_context_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM candidate_expression_context_summary WHERE "
                "metadata_status = 'METADATA_NOT_MAPPED'"
            ).fetchone()[0]
        )
        selected_experiment_count, fpkm_fallback_experiment_count = (
            int(value)
            for value in connection.execute(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE selected_expression_unit = "
                "'FPKM') FROM expression_unit_selection"
            ).fetchone()
        )
    except duckdb.Error as exc:
        raise StageError(f"Expression mapping failed: {exc}") from exc
    finally:
        connection.close()
    shutil.rmtree(spill_directory, ignore_errors=True)
    write_tsv(
        tables / "candidate_expression_mapping.tsv",
        (dict(zip(mapping_columns, row)) for row in mapping_rows),
        EXPRESSION_MAPPING_FIELDS,
    )
    write_tsv(
        tables / "candidate_expression_summary.tsv",
        (dict(zip(summary_columns, row)) for row in summary_rows),
        EXPRESSION_SUMMARY_FIELDS,
    )
    write_tsv(
        tables / "candidate_expression_context_summary.preview.tsv",
        (dict(zip(context_columns, row)) for row in context_rows),
        EXPRESSION_CONTEXT_FIELDS,
    )
    write_tsv(
        stage_root / "qc" / "expression_validation.tsv",
        [
            {
                "selected_group_count": len({row["cluster_id"] for row in members}),
                "target_group_member_count": len(members),
                "member_accession_count": len(accessions),
                "sqlite_alias_candidate_count": len(
                    {row["candidate_accession"] for row in sqlite_aliases}
                ),
                "unique_expression_mapping_count": sum(
                    row[mapping_columns.index("mapping_status")] == "MAPPED_UNIQUE"
                    for row in mapping_rows
                ),
                "broad_expression_supported_count": sum(
                    bool(row[summary_columns.index("broad_expression_supported")])
                    for row in summary_rows
                ),
                "not_mapped_member_count": sum(
                    row[mapping_columns.index("mapping_status")] == "NOT_MAPPED"
                    for row in mapping_rows
                ),
                "candidate_expression_context_count": context_total_count,
                "candidate_expression_context_preview_count": len(context_rows),
                "mapped_tissue_context_count": mapped_tissue_context_count,
                "metadata_unmapped_context_count": metadata_unmapped_context_count,
                "organism_part_count": organism_part_count,
                "selected_experiment_count": selected_experiment_count,
                "fpkm_fallback_experiment_count": fpkm_fallback_experiment_count,
                "minimum_median_expression_value": (
                    config.analysis.expression.minimum_expression_value
                ),
                "minimum_positive_context_fraction": (
                    config.analysis.expression.broad_positive_fraction
                ),
                "expression_species_count": len(
                    {
                        record["species_column"]
                        for record in manifest_records
                        if record["resource_type"] == "atlas_expression_long"
                    }
                ),
                "target_member_species_count": len(selected_species),
                "expression_manifest_file_count": len(all_expression_paths),
                "sample_metadata_scanned_file_count": len(
                    sample_metadata_paths
                ),
                "expression_scanned_file_count": len(expression_paths),
                "expression_skipped_file_count": (
                    len(all_expression_paths) - len(expression_paths)
                ),
                "expression_scanned_species_count": len(
                    {
                        record["species_column"]
                        for record in manifest_records
                        if record["resource_type"] == "atlas_expression_long"
                        and Path(record["path"]) in expression_paths
                    }
                ),
                "duckdb_threads": config.stage("07_expression").threads,
                "duckdb_memory_limit_mb": memory_limit_mb,
                "partition_pruning_policy": (
                    "scan only checksum-validated expression partitions matching "
                    "selected group-member species"
                ),
                "interpretation": (
                    "Atlas five-number summaries are represented by their median expression "
                    "level; TPM is selected per experiment with FPKM only as a recorded "
                    "fallback; contexts are counted once and tissue absence remains unavailable"
                ),
            }
        ],
        (
            "selected_group_count",
            "target_group_member_count",
            "member_accession_count",
            "sqlite_alias_candidate_count",
            "unique_expression_mapping_count",
            "broad_expression_supported_count",
            "not_mapped_member_count",
            "candidate_expression_context_count",
            "candidate_expression_context_preview_count",
            "mapped_tissue_context_count",
            "metadata_unmapped_context_count",
            "organism_part_count",
            "selected_experiment_count",
            "fpkm_fallback_experiment_count",
            "minimum_median_expression_value",
            "minimum_positive_context_fraction",
            "expression_species_count",
            "target_member_species_count",
            "expression_manifest_file_count",
            "sample_metadata_scanned_file_count",
            "expression_scanned_file_count",
            "expression_skipped_file_count",
            "expression_scanned_species_count",
            "duckdb_threads",
            "duckdb_memory_limit_mb",
            "partition_pruning_policy",
            "interpretation",
        ),
    )
