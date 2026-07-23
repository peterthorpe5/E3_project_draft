"""Reuse ligandability evidence and measure conserved pocket-bearing regions."""

from __future__ import annotations

import itertools
import logging
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb

from e3workflow.config import WorkflowConfig
from e3workflow.errors import StageError
from e3workflow.io_utils import read_tsv, write_tsv
from e3workflow.production import find_one, iter_fasta, parse_fasta_identifier
from e3workflow.resources import (
    LIGANDABILITY_DATASETS,
    paths_for_dataset,
    read_resource_manifest,
)
from e3workflow.tabular import copy_query_to_parquet, parquet_columns, quote_literal, write_records

LOGGER = logging.getLogger("e3workflow.ligandability")

SELECTED_POCKET_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "candidate_accession",
    "species_column",
    "pocket_number",
    "druggability_score",
    "p2rank_score",
    "p2rank_probability",
    "p2rank_match_status",
    "mapping_fraction",
    "conservative_fraction_plddt_ge_70",
    "mapped_mean_plddt",
    "passes_druggability_threshold",
    "passes_mapping_threshold",
    "passes_pocket_confidence_threshold",
    "predictor_agreement",
    "structural_evidence_status",
    "source_resource_id",
)

POCKET_CONSERVATION_FIELDS = (
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "structured_accession_count",
    "structured_species_count",
    "conserved_component_accession_count",
    "conserved_component_species_count",
    "conserved_component_fraction",
    "conserved_accessions",
    "conserved_species",
    "aligned_region_start",
    "aligned_region_end",
    "mean_pairwise_region_overlap",
    "median_pairwise_region_overlap",
    "mean_chemical_group_conservation",
    "minimum_druggability_score",
    "mean_druggability_score",
    "all_assessed_members_pass_druggability",
    "mean_pocket_plddt_fraction",
    "all_assessed_members_pass_mapping",
    "predictor_agreement_fraction",
    "conserved_pocket_score",
    "conservation_status",
    "interpretation",
)

POCKET_MEMBER_FIELDS = (
    "cluster_id",
    "primary_group_id",
    "candidate_accession",
    "species_column",
    "pocket_number",
    "alignment_column_count",
    "alignment_columns",
    "component_selected",
    "druggability_score",
    "mapping_fraction",
    "pocket_plddt_fraction",
    "predictor_agreement",
)

STRUCTURAL_STATUS_FIELDS = (
    "cluster_id",
    "primary_group_id",
    "candidate_accession",
    "species_column",
    "reused_prediction_available",
    "selected_pocket_available",
    "status",
    "reason",
)

CHEMICAL_GROUPS = {
    **{residue: "hydrophobic" for residue in "AVLIMFWY"},
    **{residue: "polar" for residue in "STNQ"},
    **{residue: "positive" for residue in "KRH"},
    **{residue: "negative" for residue in "DE"},
    **{residue: "special" for residue in "CGP"},
}


def _manifest_union_query(records: Sequence[Mapping[str, str]], dataset: str) -> str:
    """Return a provenance-labelled UNION ALL query for one dataset."""
    selected = [record for record in records if record["dataset"] == dataset]
    if not selected:
        raise StageError(f"Ligandability manifest contains no {dataset} dataset")
    return " UNION ALL ".join(
        "SELECT "
        + quote_literal(record["resource_id"])
        + " AS source_resource_id, * FROM read_parquet("
        + quote_literal(record["path"])
        + ")"
        for record in selected
    )


def _copy_reused_tables(
    *,
    records: Sequence[Mapping[str, str]],
    stage_root: Path,
    datasets: Sequence[str],
) -> dict[str, Path]:
    """Materialise controlled reusable tables with source-resource identifiers."""
    connection = duckdb.connect(":memory:")
    outputs: dict[str, Path] = {}
    try:
        for dataset in datasets:
            if not any(record["dataset"] == dataset for record in records):
                continue
            destination = stage_root / "tables" / f"reused_{dataset}.parquet"
            copy_query_to_parquet(
                connection=connection,
                query=_manifest_union_query(records=records, dataset=dataset),
                path=destination,
            )
            outputs[dataset] = destination
    finally:
        connection.close()
    return outputs


def _column_expression(
    columns: set[str], candidates: Sequence[str], default: str, *, table_alias: str
) -> str:
    """Return the first available TRY_CAST expression from alternative fields."""
    expressions = [
        f"TRY_CAST({table_alias}.{quote_identifier_safe(column)} AS DOUBLE)"
        for column in candidates
        if column in columns
    ]
    if not expressions:
        return default
    return expressions[0] if len(expressions) == 1 else "COALESCE(" + ", ".join(expressions) + ")"


def quote_identifier_safe(value: str) -> str:
    """Quote a schema-inspected column name for generated read-only SQL."""
    return '"' + value.replace('"', '""') + '"'


def build_selected_pockets(
    *,
    config: WorkflowConfig,
    structural_accessions: Path,
    joined_pockets: Path,
    pocket_quality: Path,
    output_path: Path,
) -> None:
    """Select one best-supported reused pocket per requested candidate accession."""
    joined_columns = set(parquet_columns(path=joined_pockets))
    quality_columns = set(parquet_columns(path=pocket_quality))
    for required, observed, label in (
        ({"accession", "pocket_number"}, joined_columns, "joined_pockets"),
        ({"accession", "pocket_number"}, quality_columns, "pocket_quality"),
    ):
        missing = sorted(required.difference(observed))
        if missing:
            raise StageError(f"{label} is missing required columns: {', '.join(missing)}")
    drug = _column_expression(
        joined_columns,
        ("druggability_score", "p2rank_druggability_score", "score"),
        "NULL::DOUBLE",
        table_alias="j",
    )
    p2rank_score = _column_expression(
        joined_columns,
        ("p2rank_score", "p2rank_prediction_score"),
        "NULL::DOUBLE",
        table_alias="j",
    )
    p2rank_probability = _column_expression(
        joined_columns,
        ("p2rank_probability", "p2rank_prediction_probability"),
        "NULL::DOUBLE",
        table_alias="j",
    )
    mapping_fraction = _column_expression(
        quality_columns, ("mapping_fraction",), "NULL::DOUBLE", table_alias="q"
    )
    plddt_fraction = _column_expression(
        quality_columns,
        ("conservative_fraction_plddt_ge_70", "mapped_fraction_plddt_ge_70"),
        "NULL::DOUBLE",
        table_alias="q",
    )
    mapped_mean = _column_expression(
        quality_columns, ("mapped_mean_plddt",), "NULL::DOUBLE", table_alias="q"
    )
    p2rank_match = (
        "COALESCE(CAST(j.p2rank_match_status AS VARCHAR), '')"
        if "p2rank_match_status" in joined_columns
        else "''"
    )
    connection = duckdb.connect(":memory:")
    try:
        query = (
            "WITH requested AS (SELECT * FROM read_parquet("
            f"{quote_literal(structural_accessions)})), joined AS (SELECT * FROM read_parquet("
            f"{quote_literal(joined_pockets)})), quality AS (SELECT * FROM read_parquet("
            f"{quote_literal(pocket_quality)})), candidates AS (SELECT r.cluster_id, "
            "r.primary_group_type, r.primary_group_id, r.candidate_accession, r.species_column, "
            "TRY_CAST(j.pocket_number AS INTEGER) AS pocket_number, "
            f"{drug} AS druggability_score, {p2rank_score} AS p2rank_score, "
            f"{p2rank_probability} AS p2rank_probability, {p2rank_match} AS "
            f"p2rank_match_status, {mapping_fraction} AS mapping_fraction, {plddt_fraction} AS "
            f"conservative_fraction_plddt_ge_70, {mapped_mean} AS mapped_mean_plddt, "
            "CASE WHEN druggability_score >= "
            f"{config.analysis.ligandability.minimum_druggability_score} THEN true ELSE false END "
            "AS passes_druggability_threshold, CASE WHEN mapping_fraction >= "
            f"{config.analysis.ligandability.minimum_mapping_fraction} THEN true ELSE false END AS "
            "passes_mapping_threshold, CASE WHEN conservative_fraction_plddt_ge_70 >= "
            f"{config.analysis.ligandability.minimum_pocket_plddt_fraction} THEN true ELSE false "
            "END AS passes_pocket_confidence_threshold, CASE WHEN upper(p2rank_match_status) = "
            "'MATCHED' THEN true ELSE false END AS predictor_agreement, j.source_resource_id, "
            "row_number() OVER (PARTITION BY r.cluster_id, r.candidate_accession ORDER BY "
            "passes_druggability_threshold DESC, passes_mapping_threshold DESC, "
            "passes_pocket_confidence_threshold DESC, predictor_agreement DESC, "
            "druggability_score DESC NULLS LAST, conservative_fraction_plddt_ge_70 DESC NULLS "
            "LAST, j.source_resource_id, TRY_CAST(j.pocket_number AS INTEGER)) AS selection_rank "
            "FROM requested r JOIN joined j ON upper(CAST(j.accession AS VARCHAR)) = "
            "upper(r.candidate_accession) LEFT JOIN quality q ON upper(CAST(q.accession AS "
            "VARCHAR)) = upper(CAST(j.accession AS VARCHAR)) AND TRY_CAST(q.pocket_number AS "
            "INTEGER) = TRY_CAST(j.pocket_number AS INTEGER)) SELECT cluster_id, "
            "primary_group_type, primary_group_id, candidate_accession, species_column, "
            "pocket_number, druggability_score, p2rank_score, p2rank_probability, "
            "p2rank_match_status, mapping_fraction, conservative_fraction_plddt_ge_70, "
            "mapped_mean_plddt, passes_druggability_threshold, passes_mapping_threshold, "
            "passes_pocket_confidence_threshold, predictor_agreement, CASE WHEN "
            "passes_druggability_threshold AND passes_mapping_threshold AND "
            "passes_pocket_confidence_threshold THEN 'SELECTED_HIGH_CONFIDENCE' ELSE "
            "'SELECTED_BEST_AVAILABLE_BELOW_ONE_OR_MORE_THRESHOLDS' END AS "
            "structural_evidence_status, source_resource_id FROM candidates "
            "WHERE selection_rank = 1"
        )
        copy_query_to_parquet(connection=connection, query=query, path=output_path)
    except duckdb.Error as exc:
        raise StageError(f"Could not select reused ligandability pockets: {exc}") from exc
    finally:
        connection.close()


def _read_query(path: Path, query: str = "SELECT * FROM source") -> list[dict[str, Any]]:
    """Read one bounded Parquet query into dictionaries."""
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            query.replace("source", f"read_parquet({quote_literal(path)})")
        ).fetchall()
        fields = [str(item[0]) for item in connection.description]
        return [dict(zip(fields, row)) for row in rows]
    except duckdb.Error as exc:
        raise StageError(f"Could not read Parquet table {path}: {exc}") from exc
    finally:
        connection.close()


def _load_sequences(config: WorkflowConfig, accessions: set[str]) -> dict[str, str]:
    """Load requested sequences from fresh proteomes or reused OrthoFinder working files."""
    prepared = config.run_root / "01_prepared_proteomes" / "prepared_proteomes.tsv"
    sequences: dict[str, str] = {}
    if prepared.is_file():
        _, rows = read_tsv(prepared)
        for row in rows:
            fasta = (
                config.run_root
                / "01_prepared_proteomes"
                / row["prepared_fasta_relative_path"]
            )
            for header, sequence in iter_fasta(path=fasta):
                for accession in accessions.intersection(
                    parse_fasta_identifier(header=header)
                ):
                    if accession in sequences and sequences[accession] != sequence:
                        raise StageError(
                            f"Conflicting prepared sequences for accession {accession}"
                        )
                    sequences[accession] = sequence
        return sequences
    working = config.run_root / "04_orthofinder" / "Results" / "WorkingDirectory"
    sequence_ids = working / "SequenceIDs.txt"
    if not sequence_ids.is_file():
        raise StageError(
            "Neither prepared proteomes nor reused OrthoFinder SequenceIDs.txt are available"
        )
    internal_to_accession: dict[str, str] = {}
    with sequence_ids.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            internal_id, separator, raw_identifier = line.partition(": ")
            if not separator or not internal_id or not raw_identifier:
                raise StageError(
                    f"Malformed SequenceIDs.txt row at {sequence_ids}:{line_number}"
                )
            matches = accessions.intersection(
                parse_fasta_identifier(header=raw_identifier)
            )
            if len(matches) > 1:
                raise StageError(
                    f"One OrthoFinder sequence maps to multiple requested accessions: {line}"
                )
            if matches:
                internal_to_accession[internal_id] = next(iter(matches))
    for fasta in sorted(working.glob("Species*.fa")):
        for header, sequence in iter_fasta(path=fasta):
            internal_id = header.split(maxsplit=1)[0]
            accession = internal_to_accession.get(internal_id)
            if accession is None:
                continue
            if accession in sequences and sequences[accession] != sequence:
                raise StageError(
                    f"Conflicting OrthoFinder sequences for accession {accession}"
                )
            sequences[accession] = sequence
    return sequences


def _run_mafft(
    *, executable: str, input_fasta: Path, output_fasta: Path, log_path: Path, threads: int
) -> None:
    """Run MAFFT with captured logs and an atomic alignment output."""
    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_fasta.with_name(f".{output_fasta.name}.partial")
    argv = [executable, "--auto", "--thread", str(threads), str(input_fasta)]
    LOGGER.info("Running alignment command: %s", " ".join(argv))
    with temporary.open("w", encoding="utf-8") as output_handle, log_path.open(
        "w", encoding="utf-8"
    ) as log_handle:
        result = subprocess.run(
            args=argv,
            stdout=output_handle,
            stderr=log_handle,
            check=False,
            text=True,
        )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise StageError(f"MAFFT returned {result.returncode}; see {log_path}")
    temporary.replace(output_fasta)


def _alignment_position_map(sequence: str) -> dict[int, int]:
    """Map one-based ungapped residue positions to one-based alignment columns."""
    mapping: dict[int, int] = {}
    residue_position = 0
    for alignment_position, character in enumerate(sequence, start=1):
        if character in {"-", "."}:
            continue
        residue_position += 1
        mapping[residue_position] = alignment_position
    return mapping


def region_overlap(first: set[int], second: set[int]) -> float:
    """Return overlap divided by the smaller pocket-region size."""
    denominator = min(len(first), len(second))
    return 0.0 if denominator == 0 else len(first.intersection(second)) / denominator


def _connected_components(
    *, regions: Mapping[str, set[int]], minimum_overlap: float
) -> list[set[str]]:
    """Return deterministic pocket-region components linked by pairwise overlap."""
    neighbours: dict[str, set[str]] = {accession: set() for accession in regions}
    for first, second in itertools.combinations(sorted(regions), 2):
        if region_overlap(regions[first], regions[second]) >= minimum_overlap:
            neighbours[first].add(second)
            neighbours[second].add(first)
    components: list[set[str]] = []
    remaining = set(regions)
    while remaining:
        seed = min(remaining)
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(sorted(neighbours[current].difference(component), reverse=True))
        remaining.difference_update(component)
        components.append(component)
    return components


def _pairwise_overlaps(component: set[str], regions: Mapping[str, set[int]]) -> list[float]:
    """Return every pairwise overlap within one component."""
    return [
        region_overlap(regions[first], regions[second])
        for first, second in itertools.combinations(sorted(component), 2)
    ]


def _chemical_conservation(
    *, component: set[str], aligned: Mapping[str, str], regions: Mapping[str, set[int]]
) -> float:
    """Measure modal amino-acid chemical-group conservation at shared pocket columns."""
    shared_columns = {
        column
        for column in set().union(*(regions[accession] for accession in component))
        if sum(column in regions[accession] for accession in component) >= 2
    }
    scores: list[float] = []
    for column in sorted(shared_columns):
        groups = []
        for accession in component:
            character = aligned[accession][column - 1].upper()
            if character in {"-", ".", "X"}:
                continue
            groups.append(CHEMICAL_GROUPS.get(character, "other"))
        if len(groups) < 2:
            continue
        modal = max(groups.count(group) for group in set(groups))
        scores.append(modal / len(groups))
    return statistics.mean(scores) if scores else 0.0


def _write_group_fasta(path: Path, accessions: Sequence[str], sequences: Mapping[str, str]) -> None:
    """Write one group FASTA using accession-only headers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for accession in sorted(accessions):
            handle.write(f">{accession}\n{sequences[accession]}\n")


def measure_pocket_conservation(
    *,
    config: WorkflowConfig,
    selected_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
    sequences: Mapping[str, str],
    stage_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Align selected candidates and calculate conserved pocket-region evidence."""
    selected_by_accession = {
        str(record["candidate_accession"]): dict(record) for record in selected_records
    }
    positions: dict[str, set[int]] = defaultdict(set)
    for record in mapping_records:
        accession = str(record.get("accession", ""))
        selected = selected_by_accession.get(accession)
        if selected is None:
            continue
        if int(record.get("pocket_number") or -1) != int(selected["pocket_number"]):
            continue
        if str(record.get("mapping_status", "")) != "MAPPED":
            continue
        position = record.get("model_label_seq_id")
        if position is not None and str(position) != "":
            positions[accession].add(int(position))
    by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in selected_records:
        key = (
            str(record["cluster_id"]),
            str(record["primary_group_type"]),
            str(record["primary_group_id"]),
        )
        by_group[key].append(dict(record))
    summaries: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    for (cluster_id, group_type, group_id), records in sorted(by_group.items()):
        eligible = [
            record
            for record in records
            if record["candidate_accession"] in sequences
            and positions.get(str(record["candidate_accession"]))
        ]
        if len(eligible) < 2:
            summaries.append(
                {
                    "cluster_id": cluster_id,
                    "primary_group_type": group_type,
                    "primary_group_id": group_id,
                    "structured_accession_count": len(eligible),
                    "structured_species_count": len(
                        {str(record["species_column"]) for record in eligible}
                    ),
                    "conserved_component_accession_count": 0,
                    "conserved_component_species_count": 0,
                    "conserved_component_fraction": 0.0,
                    "conserved_accessions": "",
                    "conserved_species": "",
                    "aligned_region_start": "",
                    "aligned_region_end": "",
                    "mean_pairwise_region_overlap": 0.0,
                    "median_pairwise_region_overlap": 0.0,
                    "mean_chemical_group_conservation": 0.0,
                    "minimum_druggability_score": "",
                    "mean_druggability_score": "",
                    "all_assessed_members_pass_druggability": False,
                    "mean_pocket_plddt_fraction": "",
                    "all_assessed_members_pass_mapping": False,
                    "predictor_agreement_fraction": 0.0,
                    "conserved_pocket_score": 0.0,
                    "conservation_status": "INSUFFICIENT_STRUCTURES",
                    "interpretation": (
                        "fewer than two reusable mapped pocket predictions were available"
                    ),
                }
            )
            continue
        group_slug = re_safe_filename(f"{cluster_id}__{group_id}")
        input_fasta = stage_root / "alignments" / group_slug / "input.fasta"
        aligned_fasta = stage_root / "alignments" / group_slug / "aligned.fasta"
        log_path = stage_root / "alignments" / group_slug / "mafft.log"
        accessions = [str(record["candidate_accession"]) for record in eligible]
        _write_group_fasta(path=input_fasta, accessions=accessions, sequences=sequences)
        _run_mafft(
            executable=config.analysis.ligandability.mafft_executable,
            input_fasta=input_fasta,
            output_fasta=aligned_fasta,
            log_path=log_path,
            threads=config.stage("09_ligandability").threads,
        )
        aligned = {
            header.split(maxsplit=1)[0]: sequence
            for header, sequence in iter_fasta(path=aligned_fasta)
        }
        if set(accessions) != set(aligned):
            raise StageError(f"MAFFT output identifiers differ for group {group_id}")
        regions: dict[str, set[int]] = {}
        for accession in accessions:
            position_map = _alignment_position_map(sequence=aligned[accession])
            missing_positions = positions[accession].difference(position_map)
            if missing_positions:
                raise StageError(
                    f"Pocket positions exceed the prepared sequence for {accession}: "
                    + ",".join(str(value) for value in sorted(missing_positions))
                )
            regions[accession] = {position_map[position] for position in positions[accession]}
        components = _connected_components(
            regions=regions,
            minimum_overlap=config.analysis.ligandability.minimum_region_overlap,
        )
        components.sort(
            key=lambda component: (
                -len(component),
                -statistics.mean(_pairwise_overlaps(component, regions))
                if len(component) > 1
                else 0.0,
                sorted(component),
            )
        )
        component = components[0]
        overlaps = _pairwise_overlaps(component, regions)
        mean_overlap = statistics.mean(overlaps) if overlaps else 0.0
        median_overlap = statistics.median(overlaps) if overlaps else 0.0
        chemical = _chemical_conservation(
            component=component, aligned=aligned, regions=regions
        )
        component_records = [
            selected_by_accession[accession] for accession in sorted(component)
        ]
        drug_values = [
            float(record["druggability_score"])
            for record in component_records
            if record.get("druggability_score") is not None
        ]
        plddt_values = [
            float(record["conservative_fraction_plddt_ge_70"])
            for record in component_records
            if record.get("conservative_fraction_plddt_ge_70") is not None
        ]
        predictor_fraction = sum(
            bool(record["predictor_agreement"]) for record in component_records
        ) / len(component_records)
        component_fraction = len(component) / len(eligible)
        minimum_drug = min(drug_values) if drug_values else 0.0
        mean_drug = statistics.mean(drug_values) if drug_values else 0.0
        mean_plddt = statistics.mean(plddt_values) if plddt_values else 0.0
        conserved_score = (
            0.30 * component_fraction
            + 0.25 * mean_overlap
            + 0.20 * chemical
            + 0.15 * max(0.0, min(1.0, minimum_drug))
            + 0.10 * mean_plddt
        )
        region_union = set().union(*(regions[accession] for accession in component))
        species = {
            str(record["species_column"])
            for record in component_records
            if record.get("species_column")
        }
        summaries.append(
            {
                "cluster_id": cluster_id,
                "primary_group_type": group_type,
                "primary_group_id": group_id,
                "structured_accession_count": len(eligible),
                "structured_species_count": len(
                    {str(record["species_column"]) for record in eligible}
                ),
                "conserved_component_accession_count": len(component),
                "conserved_component_species_count": len(species),
                "conserved_component_fraction": component_fraction,
                "conserved_accessions": ";".join(sorted(component)),
                "conserved_species": ";".join(sorted(species)),
                "aligned_region_start": min(region_union),
                "aligned_region_end": max(region_union),
                "mean_pairwise_region_overlap": mean_overlap,
                "median_pairwise_region_overlap": median_overlap,
                "mean_chemical_group_conservation": chemical,
                "minimum_druggability_score": minimum_drug,
                "mean_druggability_score": mean_drug,
                "all_assessed_members_pass_druggability": all(
                    bool(record["passes_druggability_threshold"])
                    for record in component_records
                ),
                "mean_pocket_plddt_fraction": mean_plddt,
                "all_assessed_members_pass_mapping": all(
                    bool(record["passes_mapping_threshold"]) for record in component_records
                ),
                "predictor_agreement_fraction": predictor_fraction,
                "conserved_pocket_score": conserved_score,
                "conservation_status": (
                    "CONSERVED_REGION_SUPPORTED"
                    if len(component) >= 2
                    and mean_overlap >= config.analysis.ligandability.minimum_region_overlap
                    else "NO_MULTI_MEMBER_CONSERVED_REGION"
                ),
                "interpretation": (
                    "residue-level sequence-alignment evidence for pockets occupying a shared "
                    "region; not proof of conserved three-dimensional binding or compound affinity"
                ),
            }
        )
        record_by_accession = {
            str(record["candidate_accession"]): record for record in eligible
        }
        for accession in sorted(regions):
            record = record_by_accession[accession]
            members.append(
                {
                    "cluster_id": cluster_id,
                    "primary_group_id": group_id,
                    "candidate_accession": accession,
                    "species_column": record["species_column"],
                    "pocket_number": record["pocket_number"],
                    "alignment_column_count": len(regions[accession]),
                    "alignment_columns": ";".join(
                        str(value) for value in sorted(regions[accession])
                    ),
                    "component_selected": accession in component,
                    "druggability_score": record["druggability_score"],
                    "mapping_fraction": record["mapping_fraction"],
                    "pocket_plddt_fraction": record["conservative_fraction_plddt_ge_70"],
                    "predictor_agreement": record["predictor_agreement"],
                }
            )
    return summaries, members


def re_safe_filename(value: str) -> str:
    """Return a portable filename component for one controlled group label."""
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in value
    )
    return cleaned[:180] or "group"


def _structural_status(
    *, requested: Sequence[Mapping[str, Any]], selected: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Report explicit missing and available reused predictions for every request."""
    selected_accessions = {str(record["candidate_accession"]) for record in selected}
    return [
        {
            "cluster_id": record["cluster_id"],
            "primary_group_id": record["primary_group_id"],
            "candidate_accession": record["candidate_accession"],
            "species_column": record["species_column"],
            "reused_prediction_available": record["candidate_accession"] in selected_accessions,
            "selected_pocket_available": record["candidate_accession"] in selected_accessions,
            "status": (
                "REUSED_POCKET_SELECTED"
                if record["candidate_accession"] in selected_accessions
                else "MISSING_REUSED_PREDICTION"
            ),
            "reason": (
                "best_available_reused_pocket_selected"
                if record["candidate_accession"] in selected_accessions
                else "no_matching_accession_in_controlled_ligandability_resources"
            ),
        }
        for record in requested
    ]


def run_ligandability_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Reuse pocket predictions and measure conserved aligned pocket regions."""
    manifest_path = config.resources.ligandability_manifest
    if manifest_path is None:
        raise StageError("inputs.ligandability_manifest is required")
    records = read_resource_manifest(
        path=manifest_path,
        allowed_resource_types={"ligandability"},
        verify_checksums=True,
    )
    observed_datasets = {record["dataset"] for record in records}
    required = {"joined_pockets", "pocket_residue_mappings", "pocket_quality", "model_quality"}
    missing = sorted(required.difference(observed_datasets))
    if missing:
        raise StageError("Ligandability manifest lacks datasets: " + ", ".join(missing))
    copied = _copy_reused_tables(
        records=records,
        stage_root=stage_root,
        datasets=sorted(LIGANDABILITY_DATASETS),
    )
    write_tsv(
        stage_root / "provenance" / "ligandability_source_manifest.tsv",
        records,
        (
            "resource_id",
            "resource_type",
            "species_column",
            "dataset",
            "path",
            "sha256",
            "include",
        ),
    )
    structural_accessions = find_one(
        root=config.run_root / "08_shortlist_gate", name="structural_analysis_accessions.parquet"
    )
    selected_path = stage_root / "tables" / "selected_pockets.parquet"
    build_selected_pockets(
        config=config,
        structural_accessions=structural_accessions,
        joined_pockets=copied["joined_pockets"],
        pocket_quality=copied["pocket_quality"],
        output_path=selected_path,
    )
    selected = _read_query(
        path=selected_path,
        query="SELECT * FROM source ORDER BY cluster_id, candidate_accession",
    )
    requested = _read_query(
        path=structural_accessions,
        query="SELECT * FROM source ORDER BY computational_rank, candidate_accession",
    )
    selected_tsv_rows = [
        {field: record.get(field, "") for field in SELECTED_POCKET_FIELDS}
        for record in selected
    ]
    write_tsv(
        stage_root / "tables" / "selected_pockets.tsv",
        selected_tsv_rows,
        SELECTED_POCKET_FIELDS,
    )
    status = _structural_status(requested=requested, selected=selected)
    write_records(
        tsv_path=stage_root / "tables" / "structural_prediction_status.tsv",
        parquet_path=stage_root / "tables" / "structural_prediction_status.parquet",
        fieldnames=STRUCTURAL_STATUS_FIELDS,
        records=status,
    )
    if config.analysis.ligandability.mode == "reuse_then_run_missing" and any(
        row["status"] == "MISSING_REUSED_PREDICTION" for row in status
    ):
        raise StageError(
            "reuse_then_run_missing was requested, but automatic missing-model execution is not "
            "enabled without an explicit reviewed AlphaFold/ligandability command adapter"
        )
    requested_accessions = {str(record["candidate_accession"]) for record in selected}
    sequences = _load_sequences(config=config, accessions=requested_accessions)
    mapping_records = _read_query(
        path=copied["pocket_residue_mappings"],
        query=(
            "SELECT accession, pocket_number, mapping_status, model_label_seq_id, "
            "model_residue_name, model_plddt FROM source"
        ),
    )
    summaries, members = measure_pocket_conservation(
        config=config,
        selected_records=selected,
        mapping_records=mapping_records,
        sequences=sequences,
        stage_root=stage_root,
    )
    write_records(
        tsv_path=stage_root / "tables" / "pocket_conservation_summary.tsv",
        parquet_path=stage_root / "tables" / "pocket_conservation_summary.parquet",
        fieldnames=POCKET_CONSERVATION_FIELDS,
        records=summaries,
    )
    write_records(
        tsv_path=stage_root / "tables" / "pocket_conservation_members.tsv",
        parquet_path=stage_root / "tables" / "pocket_conservation_members.parquet",
        fieldnames=POCKET_MEMBER_FIELDS,
        records=members,
    )
    write_tsv(
        stage_root / "qc" / "ligandability_validation.tsv",
        [
            {
                "requested_accession_count": len(requested),
                "selected_reused_pocket_count": len(selected),
                "missing_reused_prediction_count": sum(
                    row["status"] == "MISSING_REUSED_PREDICTION" for row in status
                ),
                "group_conservation_summary_count": len(summaries),
                "conserved_region_supported_count": sum(
                    row["conservation_status"] == "CONSERVED_REGION_SUPPORTED"
                    for row in summaries
                ),
                "mode": config.analysis.ligandability.mode,
                "interpretation": (
                    "AlphaFold confidence and FPocket/P2Rank predictions support prioritisation; "
                    "they do not prove binding or degradation"
                ),
            }
        ],
        (
            "requested_accession_count",
            "selected_reused_pocket_count",
            "missing_reused_prediction_count",
            "group_conservation_summary_count",
            "conserved_region_supported_count",
            "mode",
            "interpretation",
        ),
    )
