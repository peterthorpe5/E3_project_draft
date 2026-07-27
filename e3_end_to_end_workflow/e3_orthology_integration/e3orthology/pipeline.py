"""Production staged workflow for OrthoFinder identifier reconciliation."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import yaml

from . import __version__
from .candidates import load_candidate_index
from .errors import InputValidationError, ScientificValidationError
from .identifiers import iter_sequence_ids, parse_species_ids
from .io_utils import (
    atomic_write_json,
    atomic_write_text,
    canonical_digest,
    configure_arrow_threads,
    file_record,
    link_or_copy,
    tsv_to_parquet,
    utc_now_iso,
    write_tsv,
)
from .orthofinder import (
    discover_results_directory,
    iter_membership_records,
    read_species_columns,
)
from .species import assess_species_coverage, load_species_manifest, species_name_from_fasta
from .sqlite_audit import lookup_inherited_groups
from .stages import StageSpec, run_stage_plan, stage_directory

_LOGGER = logging.getLogger("e3orthology.pipeline")


def _log_record_count(*, label: str, count: int) -> None:
    """Log a progress count with explicit thousands separators.

    Args:
        label: Description placed before the record count.
        count: Non-negative number of records processed.
    """

    _LOGGER.info("%s: %s records.", label, f"{count:,}")


SEQUENCE_FIELDS = (
    "internal_id",
    "species_index",
    "source_fasta",
    "raw_header",
    "raw_identifier",
    "parsed_accession",
    "parsed_entry",
    "review_status",
    "identifier_format",
    "mapping_status",
    "mapping_reason",
    "source_line",
)

MEMBERSHIP_FIELDS = (
    "record_type",
    "group_id",
    "orthogroup_id",
    "gene_tree_parent_clade",
    "species",
    "raw_identifier",
    "parsed_accession",
    "parsed_entry",
    "review_status",
    "identifier_format",
    "mapping_status",
    "mapping_reason",
    "source_file",
    "source_row",
)

CANDIDATE_MAPPING_FIELDS = (
    "cluster_id",
    "candidate_accession",
    "representative_original_id",
    "representative_entry",
    "mapping_status",
    "mapping_tier",
    "ambiguity_status",
    "sequence_internal_ids",
    "sequence_source_fastas",
    "sequence_mapping_status",
    "sequence_mapping_method",
    "record_type",
    "group_id",
    "orthogroup_id",
    "gene_tree_parent_clade",
    "species",
    "raw_identifier",
    "identifier_format",
    "source_file",
    "source_row",
)

GROUP_MEMBER_SEQUENCE_FIELDS = (
    "cluster_id",
    "record_type",
    "group_id",
    "orthogroup_id",
    "gene_tree_parent_clade",
    "species",
    "internal_id",
    "source_fasta",
    "raw_identifier",
    "parsed_accession",
    "parsed_entry",
    "review_status",
    "identifier_format",
    "mapping_status",
    "is_input_candidate",
    "candidate_accessions_for_cluster",
    "sequence_length",
    "sequence_sha256",
    "protein_sequence",
)

SPECIES_COVERAGE_FIELDS = (
    "canonical_species_name",
    "source_species_name",
    "taxon_id",
    "required",
    "role",
    "aliases",
    "matched_source_name",
    "status",
    "reason",
)


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved formal inputs and run-specific output locations."""

    project_root: Path
    results_directory: Path
    candidate_evidence: Path
    sqlite_database: Path
    species_manifest: Path
    output_root: Path
    run_name: str
    config_path: Path | None

    @property
    def run_root(self) -> Path:
        """Return the run-specific formal output root.

        Returns:
            ``output_root/run_name``.
        """

        return self.output_root / self.run_name

    @property
    def species_ids(self) -> Path:
        """Return the authoritative OrthoFinder species mapping.

        Returns:
            ``WorkingDirectory/SpeciesIDs.txt`` path.
        """

        return self.results_directory / "WorkingDirectory" / "SpeciesIDs.txt"

    @property
    def sequence_ids(self) -> Path:
        """Return the authoritative OrthoFinder sequence mapping.

        Returns:
            ``WorkingDirectory/SequenceIDs.txt`` path.
        """

        return self.results_directory / "WorkingDirectory" / "SequenceIDs.txt"

    @property
    def orthogroups(self) -> Path:
        """Return the authoritative OrthoFinder orthogroup table.

        Returns:
            ``Orthogroups/Orthogroups.tsv`` path.
        """

        return self.results_directory / "Orthogroups" / "Orthogroups.tsv"

    @property
    def hierarchical_orthogroups(self) -> Path:
        """Return the root-level hierarchical orthogroup table.

        Returns:
            ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv`` path.
        """

        return self.results_directory / "Phylogenetic_Hierarchical_Orthogroups" / "N0.tsv"


def build_runtime_paths(
    *,
    project_root: Path,
    orthofinder_source_root: Path,
    results_directory_name: str,
    candidate_evidence: Path,
    sqlite_database: Path,
    species_manifest: Path,
    output_root: Path,
    run_name: str,
    config_path: Path | None,
) -> RuntimePaths:
    """Resolve the unique OrthoFinder result and all formal runtime paths.

    Args:
        project_root: Project root.
        orthofinder_source_root: Direct results path or extraction root.
        results_directory_name: Required results directory basename.
        candidate_evidence: Candidate evidence Parquet.
        sqlite_database: Inherited SQLite database.
        species_manifest: Target species manifest TSV.
        output_root: Parent output directory.
        run_name: Stable run label.
        config_path: Optional YAML configuration.

    Returns:
        Resolved immutable path object.

    Raises:
        InputValidationError: If the run name is unsafe.
    """

    if not run_name or run_name in {".", ".."} or "/" in run_name:
        raise InputValidationError(f"Unsafe run name: {run_name!r}")
    results_directory = discover_results_directory(
        source_root=orthofinder_source_root,
        expected_name=results_directory_name,
    )
    return RuntimePaths(
        project_root=Path(project_root).expanduser().resolve(),
        results_directory=results_directory,
        candidate_evidence=Path(candidate_evidence).expanduser().resolve(),
        sqlite_database=Path(sqlite_database).expanduser().resolve(),
        species_manifest=Path(species_manifest).expanduser().resolve(),
        output_root=Path(output_root).expanduser().resolve(),
        run_name=run_name,
        config_path=(None if config_path is None else Path(config_path).expanduser().resolve()),
    )


def serialisable_runtime(*, paths: RuntimePaths, config: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical runtime object used for provenance and reuse.

    Args:
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        JSON-serialisable runtime mapping.
    """

    return {
        "package_version": __version__,
        "paths": {
            key: None if value is None else str(value) for key, value in asdict(paths).items()
        },
        "config": config,
    }


def _write_summary(*, path: Path, records: Iterable[dict[str, Any]]) -> int:
    """Write two-column metric records.

    Args:
        path: Summary TSV path.
        records: Metric and value mappings.

    Returns:
        Number of summary rows.
    """

    return write_tsv(path=path, fieldnames=("metric", "value"), records=records)


def _read_tsv(*, path: Path) -> list[dict[str, str]]:
    """Read a compact TSV into dictionaries.

    Args:
        path: TSV input.

    Returns:
        Ordered table records.
    """

    with Path(path).open(mode="r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def provide_paths(*, paths: Sequence[Path]) -> tuple[Path, ...]:
    """Return formal stage paths for deferred input checksum calculation.

    Args:
        paths: Formal stage input paths.

    Returns:
        Immutable path tuple.
    """

    return tuple(paths)


def stage_output_path(*, run_root: Path, stage_name: str, filename: str) -> Path:
    """Return one formal output path from an upstream stage.

    Args:
        run_root: Run-specific output root.
        stage_name: Upstream stage name.
        filename: Relative output filename.

    Returns:
        Absolute formal stage output path.
    """

    return stage_directory(run_root=run_root, stage_name=stage_name) / filename


def _mapping_tier(*, candidate_accession: str, membership: dict[str, str]) -> str:
    """Assign an explicit candidate-to-OrthoFinder identifier mapping tier.

    Args:
        candidate_accession: Bare candidate accession.
        membership: Parsed OrthoFinder membership record.

    Returns:
        Stable mapping-tier label.
    """

    if membership["raw_identifier"] == candidate_accession:
        return "TIER_1_RAW_EXACT"
    if membership["identifier_format"] == "UNIPROT_PIPE":
        return "TIER_2_EXACT_PARSED_UNIPROT"
    if membership.get("parsed_entry") == candidate_accession:
        return "TIER_3_EXACT_ENTRY_COLUMN"
    return "TIER_4_CONTROLLED_PARSED_TOKEN"


def load_candidate_sequence_lookup(
    *, identifier_map_path: Path, candidate_accessions: set[str]
) -> dict[str, list[dict[str, str]]]:
    """Load SequenceIDs mappings only for candidate accessions.

    Args:
        identifier_map_path: Stage-one sequence identifier TSV.
        candidate_accessions: Bare candidate accessions of interest.

    Returns:
        Candidate accession to retained SequenceIDs records.
    """

    lookup = {accession: [] for accession in candidate_accessions}
    with Path(identifier_map_path).open(mode="r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            accession = row["parsed_accession"]
            if accession in lookup:
                lookup[accession].append(row)
    return lookup


def _load_requested_fasta_sequences(
    *,
    working_directory: Path,
    requested_internal_ids: set[str],
) -> dict[str, str]:
    """Load only requested OrthoFinder internal sequences from working FASTAs.

    Args:
        working_directory: OrthoFinder ``WorkingDirectory``.
        requested_internal_ids: Internal identifiers required by candidate groups.

    Returns:
        Internal identifier to uppercase protein sequence.

    Raises:
        InputValidationError: If FASTA syntax, identifiers or requested coverage are invalid.
    """
    sequences: dict[str, str] = {}
    for fasta_path in sorted(working_directory.glob("Species*.fa")):
        current_identifier = ""
        chunks: list[str] = []

        def publish_current() -> None:
            if not current_identifier or current_identifier not in requested_internal_ids:
                return
            sequence = "".join(chunks).replace(" ", "").upper()
            if not sequence:
                raise InputValidationError(
                    f"Requested OrthoFinder sequence is empty: {current_identifier}"
                )
            previous = sequences.get(current_identifier)
            if previous is not None and previous != sequence:
                raise InputValidationError(
                    f"Conflicting OrthoFinder sequences for {current_identifier}"
                )
            sequences[current_identifier] = sequence

        with fasta_path.open(mode="r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    publish_current()
                    current_identifier = line[1:].split(maxsplit=1)[0]
                    chunks = []
                    if not current_identifier:
                        raise InputValidationError(
                            f"Empty FASTA identifier at {fasta_path}:{line_number}"
                        )
                else:
                    if not current_identifier:
                        raise InputValidationError(
                            f"Sequence precedes FASTA header at {fasta_path}:{line_number}"
                        )
                    chunks.append(line)
            publish_current()
    missing = sorted(requested_internal_ids.difference(sequences))
    if missing:
        preview = ";".join(missing[:20])
        raise InputValidationError(
            f"Candidate-group members are missing from Species*.fa: {preview}"
        )
    return sequences


def build_candidate_group_member_sequences(
    *,
    mapping_records: Sequence[dict[str, Any]],
    identifier_map_path: Path,
    membership_paths: Sequence[Path],
    working_directory: Path,
) -> list[dict[str, Any]]:
    """Build a candidate-relevant OrthoFinder group-member sequence authority.

    Args:
        mapping_records: Candidate-to-group mapping records.
        identifier_map_path: Parsed ``SequenceIDs.txt`` authority.
        membership_paths: Orthogroup and hierarchical membership TSVs.
        working_directory: Directory containing OrthoFinder ``Species*.fa`` files.

    Returns:
        One record per candidate cluster, selected group and member sequence.

    Raises:
        InputValidationError: If membership-to-sequence identifiers are ambiguous or incomplete.
    """
    group_to_clusters: dict[tuple[str, str], set[str]] = {}
    cluster_candidates: dict[str, set[str]] = {}
    for record in mapping_records:
        cluster_id = str(record["cluster_id"])
        accession = str(record["candidate_accession"])
        cluster_candidates.setdefault(cluster_id, set()).add(accession)
        record_type = str(record.get("record_type") or "")
        group_id = str(record.get("group_id") or "")
        if record_type and group_id and record.get("mapping_status") != "NOT_MATCHED":
            group_to_clusters.setdefault((record_type, group_id), set()).add(
                cluster_id
            )
    sequence_identifier_index: dict[
        tuple[str, str], list[dict[str, str]]
    ] = {}
    with identifier_map_path.open(mode="r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            species = species_name_from_fasta(fasta_name=row["source_fasta"])
            sequence_identifier_index.setdefault(
                (species, row["raw_identifier"]), []
            ).append(row)
    pending: list[tuple[str, dict[str, str], dict[str, str]]] = []
    requested_internal_ids: set[str] = set()
    for membership_path in membership_paths:
        with membership_path.open(mode="r", encoding="utf-8", newline="") as handle:
            for membership in csv.DictReader(handle, delimiter="\t"):
                group_key = (
                    str(membership["record_type"]),
                    str(membership["group_id"]),
                )
                clusters = group_to_clusters.get(group_key)
                if not clusters:
                    continue
                sequence_rows = sequence_identifier_index.get(
                    (
                        str(membership["species"]),
                        str(membership["raw_identifier"]),
                    ),
                    [],
                )
                if len(sequence_rows) != 1:
                    raise InputValidationError(
                        "Candidate-group membership must map to exactly one SequenceIDs "
                        f"record: {group_key}/{membership['species']}/"
                        f"{membership['raw_identifier']} observed={len(sequence_rows)}"
                    )
                sequence_row = sequence_rows[0]
                requested_internal_ids.add(sequence_row["internal_id"])
                for cluster_id in sorted(clusters):
                    pending.append((cluster_id, membership, sequence_row))
    sequences = _load_requested_fasta_sequences(
        working_directory=working_directory,
        requested_internal_ids=requested_internal_ids,
    )
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for cluster_id, membership, sequence_row in pending:
        internal_id = sequence_row["internal_id"]
        key = (
            cluster_id,
            str(membership["record_type"]),
            str(membership["group_id"]),
            internal_id,
        )
        if key in seen:
            continue
        seen.add(key)
        sequence = sequences[internal_id]
        parsed_accession = str(sequence_row.get("parsed_accession") or "")
        records.append(
            {
                "cluster_id": cluster_id,
                "record_type": membership["record_type"],
                "group_id": membership["group_id"],
                "orthogroup_id": membership["orthogroup_id"],
                "gene_tree_parent_clade": membership["gene_tree_parent_clade"],
                "species": membership["species"],
                "internal_id": internal_id,
                "source_fasta": sequence_row["source_fasta"],
                "raw_identifier": membership["raw_identifier"],
                "parsed_accession": parsed_accession,
                "parsed_entry": sequence_row["parsed_entry"],
                "review_status": sequence_row["review_status"],
                "identifier_format": sequence_row["identifier_format"],
                "mapping_status": sequence_row["mapping_status"],
                "is_input_candidate": parsed_accession
                in cluster_candidates.get(cluster_id, set()),
                "candidate_accessions_for_cluster": ";".join(
                    sorted(cluster_candidates.get(cluster_id, set()))
                ),
                "sequence_length": len(sequence),
                "sequence_sha256": hashlib.sha256(
                    sequence.encode("ascii")
                ).hexdigest(),
                "protein_sequence": sequence,
            }
        )
    records.sort(
        key=lambda row: (
            str(row["cluster_id"]),
            str(row["record_type"]),
            str(row["group_id"]),
            str(row["species"]),
            str(row["internal_id"]),
        )
    )
    return records


def run_preflight_stage(
    *,
    staging: Path,
    paths: RuntimePaths,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate formal sources and write inventories and species coverage.

    Args:
        staging: Temporary stage directory.
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Preflight metrics.

    Raises:
        InputValidationError: If core tables disagree or required species are missing.
    """

    _LOGGER.info("Preflight: validating OrthoFinder structure and formal inputs.")
    species_by_index = parse_species_ids(path=paths.species_ids)
    orthogroup_species = read_species_columns(
        table_path=paths.orthogroups,
        metadata_column_count=1,
    )
    hierarchical_species = read_species_columns(
        table_path=paths.hierarchical_orthogroups,
        metadata_column_count=3,
    )
    if orthogroup_species != hierarchical_species:
        raise InputValidationError(
            "Orthogroups.tsv and N0.tsv do not contain the same ordered species columns."
        )
    expected_species = int(config["input"]["expected_species_count"])
    if len(orthogroup_species) != expected_species:
        raise InputValidationError(
            f"Expected {expected_species} species; observed {len(orthogroup_species)}."
        )
    if len(species_by_index) != expected_species:
        raise InputValidationError(
            f"SpeciesIDs contains {len(species_by_index)} species; expected {expected_species}."
        )
    manifest_records = load_species_manifest(path=paths.species_manifest)
    coverage = assess_species_coverage(
        discovered_species=orthogroup_species,
        manifest_records=manifest_records,
    )
    write_tsv(
        path=staging / "species_coverage.tsv",
        fieldnames=SPECIES_COVERAGE_FIELDS,
        records=coverage,
    )
    missing_required = [
        record["canonical_species_name"]
        for record in coverage
        if record["status"] == "MISSING_REQUIRED"
    ]
    if missing_required:
        raise InputValidationError(
            "Required target species are absent: " + "; ".join(missing_required)
        )
    input_paths = (
        paths.species_ids,
        paths.sequence_ids,
        paths.orthogroups,
        paths.hierarchical_orthogroups,
        paths.candidate_evidence,
        paths.sqlite_database,
        paths.species_manifest,
    )
    inventory = [
        {
            "input_role": role,
            **file_record(path=path),
        }
        for role, path in zip(
            (
                "species_ids",
                "sequence_ids",
                "orthogroups",
                "hierarchical_orthogroups",
                "candidate_evidence",
                "inherited_sqlite",
                "species_manifest",
            ),
            input_paths,
            strict=True,
        )
    ]
    for record in inventory:
        _LOGGER.info(
            "Input %s: %s bytes; sha256=%s",
            record["input_role"],
            record["bytes"],
            record["sha256"],
        )
    write_tsv(
        path=staging / "input_inventory.tsv",
        fieldnames=("input_role", "path", "bytes", "sha256"),
        records=inventory,
    )
    runtime = serialisable_runtime(paths=paths, config=config)
    atomic_write_text(
        path=staging / "resolved_config.yaml",
        text=yaml.safe_dump(runtime, sort_keys=True),
    )
    _write_summary(
        path=staging / "preflight_summary.tsv",
        records=(
            {"metric": "orthofinder_species_count", "value": len(orthogroup_species)},
            {"metric": "species_ids_count", "value": len(species_by_index)},
            {"metric": "required_species_missing", "value": len(missing_required)},
            {"metric": "input_file_count", "value": len(inventory)},
        ),
    )
    return {
        "orthofinder_species_count": len(orthogroup_species),
        "species_ids_count": len(species_by_index),
        "required_species_missing": len(missing_required),
    }


def run_identifier_stage(
    *,
    staging: Path,
    paths: RuntimePaths,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build the internal-to-raw-to-parsed sequence identifier resource.

    Args:
        staging: Temporary stage directory.
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Identifier counts and parse metrics.
    """

    _LOGGER.info("Identifier map: parsing %s", paths.sequence_ids)
    species_by_index = parse_species_ids(path=paths.species_ids)
    first_mapping: dict[str, tuple[str, int]] = {}
    ambiguities: dict[str, set[tuple[str, int]]] = {}
    metrics = {"record_count": 0, "parsed_count": 0, "unparsed_count": 0}

    def records() -> Iterator[dict[str, str | int | None]]:
        """Yield table records while collecting parser and ambiguity metrics."""

        for record in iter_sequence_ids(
            path=paths.sequence_ids,
            species_by_index=species_by_index,
        ):
            metrics["record_count"] += 1
            if metrics["record_count"] % 250_000 == 0:
                _log_record_count(
                    label="Identifier map: parsed",
                    count=metrics["record_count"],
                )
            accession = record.parsed.parsed_accession
            if accession is None:
                metrics["unparsed_count"] += 1
            else:
                metrics["parsed_count"] += 1
                mapping = (record.parsed.raw_identifier, record.species_index)
                if accession not in first_mapping:
                    first_mapping[accession] = mapping
                elif first_mapping[accession] != mapping:
                    ambiguities.setdefault(accession, {first_mapping[accession]}).add(mapping)
            yield record.to_record()

    write_tsv(
        path=staging / "sequence_identifier_map.tsv",
        fieldnames=SEQUENCE_FIELDS,
        records=records(),
    )
    ambiguity_records = [
        {
            "parsed_accession": accession,
            "raw_identifier_count": len(mappings),
            "species_index_count": len({mapping[1] for mapping in mappings}),
            "raw_identifiers": ";".join(sorted(mapping[0] for mapping in mappings)),
            "species_indices": ";".join(str(value) for value in sorted({m[1] for m in mappings})),
            "status": "AMBIGUOUS",
            "reason": "parsed_accession_maps_to_multiple_raw_records",
        }
        for accession, mappings in sorted(ambiguities.items())
    ]
    write_tsv(
        path=staging / "parsed_accession_ambiguities.tsv",
        fieldnames=(
            "parsed_accession",
            "raw_identifier_count",
            "species_index_count",
            "raw_identifiers",
            "species_indices",
            "status",
            "reason",
        ),
        records=ambiguity_records,
    )
    block_size = int(config["execution"]["parquet_block_size_bytes"])
    tsv_to_parquet(
        tsv_path=staging / "sequence_identifier_map.tsv",
        parquet_path=staging / "sequence_identifier_map.parquet",
        block_size=block_size,
    )
    total = metrics["record_count"]
    parse_fraction = metrics["parsed_count"] / total if total else 0.0
    _write_summary(
        path=staging / "identifier_map_summary.tsv",
        records=(
            {"metric": "record_count", "value": total},
            {"metric": "parsed_count", "value": metrics["parsed_count"]},
            {"metric": "unparsed_count", "value": metrics["unparsed_count"]},
            {"metric": "parse_fraction", "value": f"{parse_fraction:.12f}"},
            {"metric": "ambiguous_accession_count", "value": len(ambiguities)},
        ),
    )
    return {
        **metrics,
        "parse_fraction": parse_fraction,
        "ambiguous_accession_count": len(ambiguities),
    }


def run_membership_stage(
    *,
    staging: Path,
    paths: RuntimePaths,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build full orthogroup and hierarchical membership resources.

    Args:
        staging: Temporary stage directory.
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Membership row and parsing metrics.
    """

    _LOGGER.info("Membership: expanding orthogroup and hierarchical group cells.")
    metrics: dict[str, int] = {
        "orthogroup_membership_count": 0,
        "hierarchical_membership_count": 0,
        "parsed_count": 0,
        "unparsed_count": 0,
    }

    def membership_records(
        *, table_path: Path, record_type: str, metric_name: str
    ) -> Iterator[dict[str, str | int | None]]:
        """Yield membership records and update stage-level counters."""

        for record in iter_membership_records(
            table_path=table_path,
            record_type=record_type,
        ):
            metrics[metric_name] += 1
            if metrics[metric_name] % 250_000 == 0:
                _log_record_count(
                    label=f"Membership {record_type}",
                    count=metrics[metric_name],
                )
            if record.parsed.parsed_accession is None:
                metrics["unparsed_count"] += 1
            else:
                metrics["parsed_count"] += 1
            yield record.to_record()

    orthogroup_tsv = staging / "orthogroup_membership.tsv"
    hierarchical_tsv = staging / "hierarchical_membership.tsv"
    write_tsv(
        path=orthogroup_tsv,
        fieldnames=MEMBERSHIP_FIELDS,
        records=membership_records(
            table_path=paths.orthogroups,
            record_type="ORTHOGROUP",
            metric_name="orthogroup_membership_count",
        ),
    )
    write_tsv(
        path=hierarchical_tsv,
        fieldnames=MEMBERSHIP_FIELDS,
        records=membership_records(
            table_path=paths.hierarchical_orthogroups,
            record_type="HIERARCHICAL_ORTHOGROUP",
            metric_name="hierarchical_membership_count",
        ),
    )
    block_size = int(config["execution"]["parquet_block_size_bytes"])
    tsv_to_parquet(
        tsv_path=orthogroup_tsv,
        parquet_path=staging / "orthogroup_membership.parquet",
        block_size=block_size,
    )
    tsv_to_parquet(
        tsv_path=hierarchical_tsv,
        parquet_path=staging / "hierarchical_membership.parquet",
        block_size=block_size,
    )
    total = metrics["parsed_count"] + metrics["unparsed_count"]
    parse_fraction = metrics["parsed_count"] / total if total else 0.0
    _write_summary(
        path=staging / "membership_summary.tsv",
        records=(
            *({"metric": key, "value": value} for key, value in metrics.items()),
            {"metric": "parse_fraction", "value": f"{parse_fraction:.12f}"},
        ),
    )
    return {**metrics, "parse_fraction": parse_fraction}


def run_candidate_mapping_stage(
    *,
    staging: Path,
    paths: RuntimePaths,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Join candidate accessions to parsed OrthoFinder group membership.

    Args:
        staging: Temporary stage directory.
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Candidate, mapping, ambiguity and cluster counts.
    """

    _LOGGER.info("Candidate mapping: loading candidate evidence %s", paths.candidate_evidence)
    candidate_index = load_candidate_index(
        parquet_path=paths.candidate_evidence,
        cluster_column=str(config["input"]["candidate_cluster_column"]),
        accession_column=str(config["input"]["candidate_accession_column"]),
        representative_original_id_column=str(config["input"]["representative_original_id_column"]),
        representative_entry_column=str(config["input"]["representative_entry_column"]),
        delimiter=str(config["identifiers"]["candidate_delimiter"]),
    )
    identifier_map = stage_output_path(
        run_root=paths.run_root,
        stage_name="01_build_identifier_map",
        filename="sequence_identifier_map.tsv",
    )
    sequence_by_accession = load_candidate_sequence_lookup(
        identifier_map_path=identifier_map,
        candidate_accessions=set(candidate_index),
    )
    sequence_by_membership_key: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    sequence_mapping_records: list[dict[str, str]] = []
    for accession, sequence_rows in sorted(sequence_by_accession.items()):
        for row in sequence_rows:
            source_species = species_name_from_fasta(fasta_name=row["source_fasta"])
            sequence_by_membership_key.setdefault(
                (accession, source_species, row["raw_identifier"]), []
            ).append(row)
            sequence_mapping_records.append(
                {
                    "candidate_accession": accession,
                    "internal_id": row["internal_id"],
                    "species_index": row["species_index"],
                    "source_fasta": row["source_fasta"],
                    "source_species": source_species,
                    "raw_header": row["raw_header"],
                    "raw_identifier": row["raw_identifier"],
                    "parsed_accession": row["parsed_accession"],
                    "identifier_format": row["identifier_format"],
                    "mapping_status": row["mapping_status"],
                    "mapping_reason": row["mapping_reason"],
                }
            )
    membership_by_accession: dict[str, list[dict[str, str]]] = {
        accession: [] for accession in candidate_index
    }
    unvalidated_memberships: list[dict[str, str]] = []
    membership_paths = (
        stage_directory(
            run_root=paths.run_root,
            stage_name="02_build_membership",
        )
        / "orthogroup_membership.tsv",
        stage_directory(
            run_root=paths.run_root,
            stage_name="02_build_membership",
        )
        / "hierarchical_membership.tsv",
    )
    for source in membership_paths:
        _LOGGER.info("Candidate mapping: scanning %s", source)
        with source.open(mode="r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                accession = row["parsed_accession"]
                if accession in membership_by_accession:
                    key = (accession, row["species"], row["raw_identifier"])
                    if key in sequence_by_membership_key:
                        membership_by_accession[accession].append(row)
                    else:
                        unvalidated_memberships.append(
                            {
                                **row,
                                "reason": "membership_not_confirmed_by_sequenceids",
                            }
                        )
    mapping_records: list[dict[str, Any]] = []
    ambiguity_records: list[dict[str, Any]] = []
    unmatched_records: list[dict[str, Any]] = []
    cluster_state: dict[str, dict[str, set[str]]] = {}
    for accession, candidates in sorted(candidate_index.items()):
        memberships = membership_by_accession[accession]
        sequence_rows = sequence_by_accession[accession]
        raw_ids = {row["raw_identifier"] for row in sequence_rows}
        species = {species_name_from_fasta(fasta_name=row["source_fasta"]) for row in sequence_rows}
        internal_ids = {row["internal_id"] for row in sequence_rows}
        ambiguous = len(raw_ids) > 1 or len(species) > 1 or len(internal_ids) > 1
        ambiguity_status = "AMBIGUOUS" if ambiguous else "UNAMBIGUOUS"
        if ambiguous:
            ambiguity_records.append(
                {
                    "candidate_accession": accession,
                    "raw_identifier_count": len(raw_ids),
                    "species_count": len(species),
                    "internal_id_count": len(internal_ids),
                    "raw_identifiers": ";".join(sorted(raw_ids)),
                    "species": ";".join(sorted(species)),
                    "internal_ids": ";".join(sorted(internal_ids)),
                    "reason": "candidate_accession_maps_to_multiple_sequenceids_records",
                }
            )
        for candidate in candidates:
            state = cluster_state.setdefault(
                candidate.cluster_id,
                {
                    "candidate_accessions": set(),
                    "mapped_accessions": set(),
                    "orthogroups": set(),
                    "hierarchical_groups": set(),
                    "species": set(),
                },
            )
            state["candidate_accessions"].add(accession)
            if not memberships:
                unmatched_records.append(
                    {
                        "cluster_id": candidate.cluster_id,
                        "candidate_accession": accession,
                        "status": "NOT_MATCHED",
                        "reason": "no_validated_orthofinder_membership",
                    }
                )
                mapping_records.append(
                    {
                        "cluster_id": candidate.cluster_id,
                        "candidate_accession": accession,
                        "representative_original_id": candidate.representative_original_id,
                        "representative_entry": candidate.representative_entry,
                        "mapping_status": "NOT_MATCHED",
                        "mapping_tier": "NOT_MATCHED",
                        "ambiguity_status": ambiguity_status,
                        "sequence_internal_ids": ";".join(sorted(internal_ids)),
                        "sequence_source_fastas": ";".join(
                            sorted({row["source_fasta"] for row in sequence_rows})
                        ),
                        "sequence_mapping_status": (
                            "SEQUENCEIDS_MAPPED" if sequence_rows else "NOT_MAPPED"
                        ),
                        "sequence_mapping_method": (
                            "parsed_accession_from_sequenceids"
                            if sequence_rows
                            else "no_sequenceids_mapping"
                        ),
                        **{field: "" for field in CANDIDATE_MAPPING_FIELDS[11:]},
                    }
                )
                continue
            state["mapped_accessions"].add(accession)
            for membership in memberships:
                sequence_matches = sequence_by_membership_key[
                    (accession, membership["species"], membership["raw_identifier"])
                ]
                if membership["record_type"] == "ORTHOGROUP":
                    state["orthogroups"].add(membership["group_id"])
                else:
                    state["hierarchical_groups"].add(membership["group_id"])
                state["species"].add(membership["species"])
                mapping_records.append(
                    {
                        "cluster_id": candidate.cluster_id,
                        "candidate_accession": accession,
                        "representative_original_id": candidate.representative_original_id,
                        "representative_entry": candidate.representative_entry,
                        "mapping_status": "AMBIGUOUS" if ambiguous else "MAPPED",
                        "mapping_tier": _mapping_tier(
                            candidate_accession=accession,
                            membership=membership,
                        ),
                        "ambiguity_status": ambiguity_status,
                        "sequence_internal_ids": ";".join(
                            sorted(row["internal_id"] for row in sequence_matches)
                        ),
                        "sequence_source_fastas": ";".join(
                            sorted({row["source_fasta"] for row in sequence_matches})
                        ),
                        "sequence_mapping_status": "SEQUENCEIDS_VALIDATED",
                        "sequence_mapping_method": (
                            "species_and_raw_identifier_exact_sequenceids_join"
                        ),
                        "record_type": membership["record_type"],
                        "group_id": membership["group_id"],
                        "orthogroup_id": membership["orthogroup_id"],
                        "gene_tree_parent_clade": membership["gene_tree_parent_clade"],
                        "species": membership["species"],
                        "raw_identifier": membership["raw_identifier"],
                        "identifier_format": membership["identifier_format"],
                        "source_file": membership["source_file"],
                        "source_row": membership["source_row"],
                    }
                )
    cluster_records = [
        {
            "cluster_id": cluster_id,
            "candidate_accession_count": len(state["candidate_accessions"]),
            "mapped_accession_count": len(state["mapped_accessions"]),
            "candidate_accessions": ";".join(sorted(state["candidate_accessions"])),
            "orthogroups": ";".join(sorted(state["orthogroups"])),
            "hierarchical_orthogroups": ";".join(sorted(state["hierarchical_groups"])),
            "species": ";".join(sorted(state["species"])),
            "status": (
                "MAPPED"
                if state["mapped_accessions"] == state["candidate_accessions"]
                else "PARTIALLY_MAPPED"
                if state["mapped_accessions"]
                else "NOT_MATCHED"
            ),
        }
        for cluster_id, state in sorted(cluster_state.items())
    ]
    group_member_sequences = build_candidate_group_member_sequences(
        mapping_records=mapping_records,
        identifier_map_path=identifier_map,
        membership_paths=membership_paths,
        working_directory=paths.results_directory / "WorkingDirectory",
    )
    mapping_tsv = staging / "candidate_membership_mapping.tsv"
    cluster_tsv = staging / "candidate_cluster_orthology_summary.tsv"
    group_sequences_tsv = staging / "candidate_group_member_sequences.tsv"
    write_tsv(
        path=mapping_tsv,
        fieldnames=CANDIDATE_MAPPING_FIELDS,
        records=mapping_records,
    )
    write_tsv(
        path=cluster_tsv,
        fieldnames=(
            "cluster_id",
            "candidate_accession_count",
            "mapped_accession_count",
            "candidate_accessions",
            "orthogroups",
            "hierarchical_orthogroups",
            "species",
            "status",
        ),
        records=cluster_records,
    )
    write_tsv(
        path=group_sequences_tsv,
        fieldnames=GROUP_MEMBER_SEQUENCE_FIELDS,
        records=group_member_sequences,
    )
    write_tsv(
        path=staging / "unmatched_candidate_accessions.tsv",
        fieldnames=("cluster_id", "candidate_accession", "status", "reason"),
        records=unmatched_records,
    )
    write_tsv(
        path=staging / "candidate_sequence_identifier_mappings.tsv",
        fieldnames=(
            "candidate_accession",
            "internal_id",
            "species_index",
            "source_fasta",
            "source_species",
            "raw_header",
            "raw_identifier",
            "parsed_accession",
            "identifier_format",
            "mapping_status",
            "mapping_reason",
        ),
        records=sequence_mapping_records,
    )
    write_tsv(
        path=staging / "candidate_accession_ambiguities.tsv",
        fieldnames=(
            "candidate_accession",
            "raw_identifier_count",
            "species_count",
            "internal_id_count",
            "raw_identifiers",
            "species",
            "internal_ids",
            "reason",
        ),
        records=ambiguity_records,
    )
    write_tsv(
        path=staging / "unvalidated_candidate_memberships.tsv",
        fieldnames=(*MEMBERSHIP_FIELDS, "reason"),
        records=unvalidated_memberships,
    )
    block_size = int(config["execution"]["parquet_block_size_bytes"])
    tsv_to_parquet(
        tsv_path=staging / "candidate_sequence_identifier_mappings.tsv",
        parquet_path=staging / "candidate_sequence_identifier_mappings.parquet",
        block_size=block_size,
    )
    tsv_to_parquet(
        tsv_path=mapping_tsv,
        parquet_path=staging / "candidate_membership_mapping.parquet",
        block_size=block_size,
    )
    tsv_to_parquet(
        tsv_path=cluster_tsv,
        parquet_path=staging / "candidate_cluster_orthology_summary.parquet",
        block_size=block_size,
    )
    tsv_to_parquet(
        tsv_path=group_sequences_tsv,
        parquet_path=staging / "candidate_group_member_sequences.parquet",
        block_size=block_size,
    )
    _write_summary(
        path=staging / "candidate_mapping_summary.tsv",
        records=(
            {"metric": "candidate_accession_count", "value": len(candidate_index)},
            {
                "metric": "mapped_candidate_accession_count",
                "value": sum(bool(value) for value in membership_by_accession.values()),
            },
            {"metric": "unmatched_cluster_accession_count", "value": len(unmatched_records)},
            {"metric": "ambiguous_candidate_accession_count", "value": len(ambiguity_records)},
            {
                "metric": "sequenceids_mapped_candidate_accession_count",
                "value": sum(bool(value) for value in sequence_by_accession.values()),
            },
            {
                "metric": "unvalidated_candidate_membership_count",
                "value": len(unvalidated_memberships),
            },
            {"metric": "candidate_mapping_row_count", "value": len(mapping_records)},
            {
                "metric": "candidate_group_member_sequence_count",
                "value": len(group_member_sequences),
            },
            {"metric": "cluster_count", "value": len(cluster_records)},
        ),
    )
    return {
        "candidate_accession_count": len(candidate_index),
        "candidate_mapping_row_count": len(mapping_records),
        "candidate_group_member_sequence_count": len(group_member_sequences),
        "cluster_count": len(cluster_records),
        "unmatched_cluster_accession_count": len(unmatched_records),
        "ambiguous_candidate_accession_count": len(ambiguity_records),
        "sequenceids_mapped_candidate_accession_count": sum(
            bool(value) for value in sequence_by_accession.values()
        ),
        "unvalidated_candidate_membership_count": len(unvalidated_memberships),
    }


def validation_check(
    *,
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    details: str,
) -> dict[str, str]:
    """Build one portable validation check record.

    Args:
        name: Stable check identifier.
        passed: Check result.
        observed: Observed value.
        expected: Expected value.
        details: Human-readable interpretation.

    Returns:
        Validation record containing PASS or FAIL.
    """

    return {
        "check_name": name,
        "status": "PASS" if passed else "FAIL",
        "observed_value": str(observed),
        "expected_value": str(expected),
        "details": details,
    }


def run_validation_stage(
    *,
    staging: Path,
    paths: RuntimePaths,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run required structural, parser, ambiguity and Q9SA03 regressions.

    Args:
        staging: Temporary stage directory.
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Validation check counts.

    Raises:
        ScientificValidationError: If any required check fails.
    """

    _LOGGER.info("Validation: evaluating structural and scientific regressions.")
    preflight = stage_directory(run_root=paths.run_root, stage_name="00_preflight")
    identifiers = stage_directory(run_root=paths.run_root, stage_name="01_build_identifier_map")
    candidate_stage = stage_directory(run_root=paths.run_root, stage_name="03_map_candidates")
    species_coverage = _read_tsv(path=preflight / "species_coverage.tsv")
    identifier_summary = {
        row["metric"]: row["value"]
        for row in _read_tsv(path=identifiers / "identifier_map_summary.tsv")
    }
    candidate_mappings = _read_tsv(path=candidate_stage / "candidate_membership_mapping.tsv")
    candidate_sequence_mappings = _read_tsv(
        path=candidate_stage / "candidate_sequence_identifier_mappings.tsv"
    )
    candidate_summary = {
        row["metric"]: row["value"]
        for row in _read_tsv(path=candidate_stage / "candidate_mapping_summary.tsv")
    }
    expected_species = int(config["input"]["expected_species_count"])
    observed_species = len(
        read_species_columns(table_path=paths.orthogroups, metadata_column_count=1)
    )
    missing_required = sum(record["status"] == "MISSING_REQUIRED" for record in species_coverage)
    parse_fraction = float(identifier_summary["parse_fraction"])
    minimum_parse = float(config["identifiers"]["minimum_uniprot_parse_fraction"])
    ambiguity_count = int(identifier_summary["ambiguous_accession_count"])
    accession = str(config["regression"]["accession"])
    observed_raw_identifiers = sorted(
        {
            row["raw_identifier"]
            for row in candidate_sequence_mappings
            if row["candidate_accession"] == accession
        }
    )
    expected_raw_identifier = str(config["regression"]["expected_raw_identifier"])
    unvalidated_membership_count = int(candidate_summary["unvalidated_candidate_membership_count"])
    q9_rows = [
        row
        for row in candidate_mappings
        if row["candidate_accession"] == accession and row["mapping_status"] != "NOT_MATCHED"
    ]
    observed_orthogroups = sorted(
        {row["group_id"] for row in q9_rows if row["record_type"] == "ORTHOGROUP"}
    )
    observed_hierarchical = sorted(
        {row["group_id"] for row in q9_rows if row["record_type"] == "HIERARCHICAL_ORTHOGROUP"}
    )
    expected_orthogroup = str(config["regression"]["expected_orthogroup"])
    expected_hierarchical = str(config["regression"]["expected_hierarchical_orthogroup"])
    checks = [
        validation_check(
            name="orthofinder_species_count",
            passed=observed_species == expected_species,
            observed=observed_species,
            expected=expected_species,
            details="Selected OrthoFinder result must contain the configured species count.",
        ),
        validation_check(
            name="required_target_species_present",
            passed=missing_required == 0,
            observed=missing_required,
            expected=0,
            details="Every required manifest species must be analysed in this run.",
        ),
        validation_check(
            name="identifier_parse_fraction",
            passed=parse_fraction >= minimum_parse,
            observed=f"{parse_fraction:.12f}",
            expected=f">={minimum_parse:.12f}",
            details="Controlled identifier parsing must meet the configured minimum.",
        ),
        validation_check(
            name="parsed_accession_ambiguity",
            passed=(
                ambiguity_count == 0
                if config["identifiers"]["fail_on_parsed_accession_ambiguity"]
                else True
            ),
            observed=ambiguity_count,
            expected=(
                0
                if config["identifiers"]["fail_on_parsed_accession_ambiguity"]
                else "reported_only"
            ),
            details="Parsed accessions must not silently collapse incompatible proteins.",
        ),
        validation_check(
            name="candidate_memberships_confirmed_by_sequenceids",
            passed=(
                unvalidated_membership_count == 0
                if config["identifiers"]["fail_on_unvalidated_candidate_membership"]
                else True
            ),
            observed=unvalidated_membership_count,
            expected=(
                0
                if config["identifiers"]["fail_on_unvalidated_candidate_membership"]
                else "reported_only"
            ),
            details=(
                "Candidate memberships must join exactly to SequenceIDs by species and raw ID."
            ),
        ),
        validation_check(
            name="q9sa03_sequenceids_raw_identifier_regression",
            passed=observed_raw_identifiers == [expected_raw_identifier],
            observed=";".join(observed_raw_identifiers) or "NOT_MATCHED",
            expected=expected_raw_identifier,
            details="Q9SA03 must reproduce the retained raw SequenceIDs identifier.",
        ),
        validation_check(
            name="q9sa03_orthogroup_regression",
            passed=observed_orthogroups == [expected_orthogroup],
            observed=";".join(observed_orthogroups) or "NOT_MATCHED",
            expected=expected_orthogroup,
            details="Q9SA03 must reproduce the inherited Results_Feb26 orthogroup.",
        ),
        validation_check(
            name="q9sa03_hierarchical_orthogroup_regression",
            passed=observed_hierarchical == [expected_hierarchical],
            observed=";".join(observed_hierarchical) or "NOT_MATCHED",
            expected=expected_hierarchical,
            details="Q9SA03 must reproduce the inherited root-level hierarchical group.",
        ),
    ]
    if config["input"]["require_sqlite_regression"]:
        inherited = lookup_inherited_groups(path=paths.sqlite_database, accession=accession)
        checks.extend(
            (
                validation_check(
                    name="sqlite_q9sa03_orthogroup_regression",
                    passed=inherited["orthogroup"] == expected_orthogroup,
                    observed=inherited["orthogroup"],
                    expected=expected_orthogroup,
                    details="Read-only inherited SQLite must agree with Results_Feb26.",
                ),
                validation_check(
                    name="sqlite_q9sa03_hierarchical_regression",
                    passed=(inherited["hierarchical_orthogroup"] == expected_hierarchical),
                    observed=inherited["hierarchical_orthogroup"],
                    expected=expected_hierarchical,
                    details="Read-only inherited SQLite must agree with Results_Feb26.",
                ),
            )
        )
    write_tsv(
        path=staging / "validation_checks.tsv",
        fieldnames=(
            "check_name",
            "status",
            "observed_value",
            "expected_value",
            "details",
        ),
        records=checks,
    )
    summary = {
        "check_count": len(checks),
        "pass_count": sum(check["status"] == "PASS" for check in checks),
        "fail_count": sum(check["status"] == "FAIL" for check in checks),
        "checks": checks,
    }
    atomic_write_json(path=staging / "validation_summary.json", value=summary)
    failed = [check["check_name"] for check in checks if check["status"] == "FAIL"]
    if failed:
        raise ScientificValidationError("Required validation failed: " + "; ".join(failed))
    return {
        "check_count": summary["check_count"],
        "pass_count": summary["pass_count"],
        "fail_count": summary["fail_count"],
    }


def run_publish_stage(
    *,
    staging: Path,
    paths: RuntimePaths,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Publish portable authorities and aggregate run provenance.

    Args:
        staging: Temporary stage directory.
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Published file counts and methods.
    """

    _LOGGER.info("Publication: assembling portable TSV, Parquet and provenance resources.")
    sources = (
        ("01_build_identifier_map", "sequence_identifier_map.tsv", "tables"),
        ("01_build_identifier_map", "sequence_identifier_map.parquet", "tables"),
        ("01_build_identifier_map", "parsed_accession_ambiguities.tsv", "qc"),
        ("02_build_membership", "orthogroup_membership.tsv", "tables"),
        ("02_build_membership", "orthogroup_membership.parquet", "tables"),
        ("02_build_membership", "hierarchical_membership.tsv", "tables"),
        ("02_build_membership", "hierarchical_membership.parquet", "tables"),
        ("03_map_candidates", "candidate_membership_mapping.tsv", "tables"),
        ("03_map_candidates", "candidate_membership_mapping.parquet", "tables"),
        (
            "03_map_candidates",
            "candidate_group_member_sequences.tsv",
            "tables",
        ),
        (
            "03_map_candidates",
            "candidate_group_member_sequences.parquet",
            "tables",
        ),
        (
            "03_map_candidates",
            "candidate_sequence_identifier_mappings.tsv",
            "tables",
        ),
        (
            "03_map_candidates",
            "candidate_sequence_identifier_mappings.parquet",
            "tables",
        ),
        ("03_map_candidates", "candidate_cluster_orthology_summary.tsv", "tables"),
        (
            "03_map_candidates",
            "candidate_cluster_orthology_summary.parquet",
            "tables",
        ),
        ("03_map_candidates", "unmatched_candidate_accessions.tsv", "qc"),
        ("03_map_candidates", "candidate_accession_ambiguities.tsv", "qc"),
        ("03_map_candidates", "unvalidated_candidate_memberships.tsv", "qc"),
        ("04_validate_integration", "validation_checks.tsv", "qc"),
        ("04_validate_integration", "validation_summary.json", "qc"),
        ("00_preflight", "input_inventory.tsv", "provenance"),
        ("00_preflight", "species_coverage.tsv", "provenance"),
        ("00_preflight", "resolved_config.yaml", "provenance"),
    )
    publication_records: list[dict[str, Any]] = []
    for stage_name, filename, section in sources:
        source = stage_directory(run_root=paths.run_root, stage_name=stage_name) / filename
        destination = staging / section / filename
        method = link_or_copy(source=source, destination=destination)
        publication_records.append(
            {
                "source_stage": stage_name,
                "source_path": str(source),
                "published_path": str(Path(section) / filename),
                "publication_method": method,
                "bytes": destination.stat().st_size,
            }
        )
    write_tsv(
        path=staging / "provenance" / "publication_manifest.tsv",
        fieldnames=(
            "source_stage",
            "source_path",
            "published_path",
            "publication_method",
            "bytes",
        ),
        records=publication_records,
    )
    stage_manifests = []
    for stage_name in (
        "00_preflight",
        "01_build_identifier_map",
        "02_build_membership",
        "03_map_candidates",
        "04_validate_integration",
    ):
        manifest_path = (
            stage_directory(
                run_root=paths.run_root,
                stage_name=stage_name,
            )
            / "stage_manifest.json"
        )
        stage_manifests.append(json.loads(manifest_path.read_text(encoding="utf-8")))
    run_manifest = {
        "resource_name": "ARIA E3 OrthoFinder identifier integration",
        "resource_version": __version__,
        "orthofinder_run_id": config["project"]["orthofinder_run_id"],
        "scientific_interpretation": (
            "OrthoFinder orthogroups can contain orthologues and paralogues. "
            "Group membership is run-specific and does not by itself prove E3 function."
        ),
        "created_at": utc_now_iso(),
        "runtime": serialisable_runtime(paths=paths, config=config),
        "stage_manifests": stage_manifests,
        "published_file_count": len(publication_records),
    }
    atomic_write_json(
        path=staging / "provenance" / "run_manifest.json",
        value=run_manifest,
    )
    return {"published_file_count": len(publication_records)}


def build_stage_specs(*, paths: RuntimePaths, config: dict[str, Any]) -> tuple[StageSpec, ...]:
    """Build the complete ordered stage plan and dependency contracts.

    Args:
        paths: Resolved runtime paths.
        config: Effective configuration.

    Returns:
        Ordered immutable stage definitions.
    """

    preflight_outputs = (
        "input_inventory.tsv",
        "species_coverage.tsv",
        "resolved_config.yaml",
        "preflight_summary.tsv",
    )
    identifier_outputs = (
        "sequence_identifier_map.tsv",
        "sequence_identifier_map.parquet",
        "parsed_accession_ambiguities.tsv",
        "identifier_map_summary.tsv",
    )
    membership_outputs = (
        "orthogroup_membership.tsv",
        "orthogroup_membership.parquet",
        "hierarchical_membership.tsv",
        "hierarchical_membership.parquet",
        "membership_summary.tsv",
    )
    candidate_outputs = (
        "candidate_sequence_identifier_mappings.tsv",
        "candidate_sequence_identifier_mappings.parquet",
        "candidate_membership_mapping.tsv",
        "candidate_membership_mapping.parquet",
        "candidate_group_member_sequences.tsv",
        "candidate_group_member_sequences.parquet",
        "candidate_cluster_orthology_summary.tsv",
        "candidate_cluster_orthology_summary.parquet",
        "unmatched_candidate_accessions.tsv",
        "candidate_accession_ambiguities.tsv",
        "unvalidated_candidate_memberships.tsv",
        "candidate_mapping_summary.tsv",
    )
    validation_outputs = ("validation_checks.tsv", "validation_summary.json")
    publish_outputs = tuple(
        [
            f"tables/{filename}"
            for filename in (
                "sequence_identifier_map.tsv",
                "sequence_identifier_map.parquet",
                "orthogroup_membership.tsv",
                "orthogroup_membership.parquet",
                "hierarchical_membership.tsv",
                "hierarchical_membership.parquet",
                "candidate_membership_mapping.tsv",
                "candidate_membership_mapping.parquet",
                "candidate_group_member_sequences.tsv",
                "candidate_group_member_sequences.parquet",
                "candidate_sequence_identifier_mappings.tsv",
                "candidate_sequence_identifier_mappings.parquet",
                "candidate_cluster_orthology_summary.tsv",
                "candidate_cluster_orthology_summary.parquet",
            )
        ]
        + [
            f"qc/{filename}"
            for filename in (
                "parsed_accession_ambiguities.tsv",
                "unmatched_candidate_accessions.tsv",
                "candidate_accession_ambiguities.tsv",
                "unvalidated_candidate_memberships.tsv",
                "validation_checks.tsv",
                "validation_summary.json",
            )
        ]
        + [
            f"provenance/{filename}"
            for filename in (
                "input_inventory.tsv",
                "species_coverage.tsv",
                "resolved_config.yaml",
                "publication_manifest.tsv",
                "run_manifest.json",
            )
        ]
    )

    def stage_file(stage_name: str, filename: str) -> Path:
        """Resolve an upstream output while constructing the stage plan."""

        return stage_output_path(
            run_root=paths.run_root,
            stage_name=stage_name,
            filename=filename,
        )

    return (
        StageSpec(
            name="00_preflight",
            version="1",
            expected_outputs=preflight_outputs,
            input_provider=lambda: (
                paths.species_ids,
                paths.sequence_ids,
                paths.orthogroups,
                paths.hierarchical_orthogroups,
                paths.candidate_evidence,
                paths.sqlite_database,
                paths.species_manifest,
            ),
            executor=lambda staging: run_preflight_stage(
                staging=staging, paths=paths, config=config
            ),
        ),
        StageSpec(
            name="01_build_identifier_map",
            version="1",
            expected_outputs=identifier_outputs,
            input_provider=lambda: (paths.species_ids, paths.sequence_ids),
            executor=lambda staging: run_identifier_stage(
                staging=staging, paths=paths, config=config
            ),
        ),
        StageSpec(
            name="02_build_membership",
            version="1",
            expected_outputs=membership_outputs,
            input_provider=lambda: (
                paths.orthogroups,
                paths.hierarchical_orthogroups,
                stage_file("01_build_identifier_map", "sequence_identifier_map.tsv"),
            ),
            executor=lambda staging: run_membership_stage(
                staging=staging, paths=paths, config=config
            ),
        ),
        StageSpec(
            name="03_map_candidates",
            version="3",
            expected_outputs=candidate_outputs,
            input_provider=lambda: (
                paths.candidate_evidence,
                stage_file("02_build_membership", "orthogroup_membership.tsv"),
                stage_file("02_build_membership", "hierarchical_membership.tsv"),
                stage_file("01_build_identifier_map", "sequence_identifier_map.tsv"),
                stage_file("01_build_identifier_map", "parsed_accession_ambiguities.tsv"),
                *tuple(
                    sorted(
                        (paths.results_directory / "WorkingDirectory").glob(
                            "Species*.fa"
                        )
                    )
                ),
            ),
            executor=lambda staging: run_candidate_mapping_stage(
                staging=staging, paths=paths, config=config
            ),
        ),
        StageSpec(
            name="04_validate_integration",
            version="2",
            expected_outputs=validation_outputs,
            input_provider=lambda: (
                stage_file("00_preflight", "species_coverage.tsv"),
                stage_file("01_build_identifier_map", "identifier_map_summary.tsv"),
                stage_file("03_map_candidates", "candidate_membership_mapping.tsv"),
                stage_file(
                    "03_map_candidates",
                    "candidate_sequence_identifier_mappings.tsv",
                ),
                stage_file("03_map_candidates", "candidate_mapping_summary.tsv"),
                paths.sqlite_database,
            ),
            executor=lambda staging: run_validation_stage(
                staging=staging, paths=paths, config=config
            ),
        ),
        StageSpec(
            name="05_publish_portable_outputs",
            version="3",
            expected_outputs=publish_outputs,
            input_provider=lambda: tuple(
                stage_file(stage_name, filename)
                for stage_name, filenames in (
                    ("00_preflight", preflight_outputs),
                    ("01_build_identifier_map", identifier_outputs),
                    ("02_build_membership", membership_outputs),
                    ("03_map_candidates", candidate_outputs),
                    ("04_validate_integration", validation_outputs),
                )
                for filename in filenames
            ),
            executor=lambda staging: run_publish_stage(staging=staging, paths=paths, config=config),
        ),
    )


def run_pipeline(
    *,
    paths: RuntimePaths,
    config: dict[str, Any],
    resume: bool,
    start_at: str | None,
    stop_after: str | None,
    force_stages: set[str],
    dry_run: bool,
) -> list[dict[str, str]]:
    """Execute the complete restartable identifier-integration workflow.

    Args:
        paths: Resolved formal paths.
        config: Effective configuration.
        resume: Permit validated stage reuse.
        start_at: Optional first stage.
        stop_after: Optional final stage.
        force_stages: Explicit stages to rerun.
        dry_run: Report decisions without running analysis.

    Returns:
        Ordered stage decision records.
    """

    threads = int(config["execution"]["threads"])
    configure_arrow_threads(threads=threads)
    _LOGGER.info("Execution threads: %d (PyArrow CPU and I/O pools).", threads)
    runtime = serialisable_runtime(paths=paths, config=config)
    config_digest = canonical_digest(value=runtime)
    specs = build_stage_specs(paths=paths, config=config)
    _LOGGER.info("Run root: %s", paths.run_root)
    _LOGGER.info("OrthoFinder result: %s", paths.results_directory)
    _LOGGER.info("Configuration digest: %s", config_digest)
    decisions = run_stage_plan(
        run_root=paths.run_root,
        ordered_specs=specs,
        config_digest=config_digest,
        package_version=__version__,
        resume=resume,
        start_at=start_at,
        stop_after=stop_after,
        force_stages=force_stages,
        dry_run=dry_run,
    )
    for decision in decisions:
        _LOGGER.info(
            "Stage %s: %s (%s)",
            decision["stage"],
            decision["decision"],
            decision["reason"],
        )
    return decisions
