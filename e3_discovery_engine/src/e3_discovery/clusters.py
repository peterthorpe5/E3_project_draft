"""Streaming conversion and filtering of DIAMOND clustering outputs."""

from __future__ import annotations

import logging
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import atomic_binary_path, open_text_auto

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Thresholds:
    """Strict post-realignment thresholds used for member classification."""

    minimum_percent_identity: float
    minimum_representative_coverage: float
    minimum_member_coverage: float
    minimum_bitscore: float
    maximum_evalue: float

    def validate(self) -> None:
        """Raise ValueError if a threshold is outside its valid range."""

        for name, value in (
            ("minimum_percent_identity", self.minimum_percent_identity),
            (
                "minimum_representative_coverage",
                self.minimum_representative_coverage,
            ),
            ("minimum_member_coverage", self.minimum_member_coverage),
        ):
            if not 0 < value <= 100:
                raise ValueError(f"{name} must be greater than 0 and at most 100")
        if self.minimum_bitscore <= 0:
            raise ValueError("minimum_bitscore must be positive")
        if self.maximum_evalue <= 0:
            raise ValueError("maximum_evalue must be positive")


CLUSTER_SCHEMA = pa.schema(
    [
        ("representative_id", pa.string()),
        ("member_id", pa.string()),
        ("source_row", pa.int64()),
    ]
)

REALIGN_SCHEMA = pa.schema(
    [
        ("representative_id", pa.string()),
        ("member_id", pa.string()),
        ("pident", pa.float64()),
        ("representative_length", pa.int64()),
        ("member_length", pa.int64()),
        ("representative_start", pa.int64()),
        ("representative_end", pa.int64()),
        ("member_start", pa.int64()),
        ("member_end", pa.int64()),
        ("alignment_length", pa.int64()),
        ("evalue", pa.float64()),
        ("bitscore", pa.float64()),
        ("representative_coverage", pa.float64()),
        ("member_coverage", pa.float64()),
        ("passes_identity", pa.bool_()),
        ("passes_representative_coverage", pa.bool_()),
        ("passes_member_coverage", pa.bool_()),
        ("passes_bitscore", pa.bool_()),
        ("passes_evalue", pa.bool_()),
        ("passes_all", pa.bool_()),
        ("source_row", pa.int64()),
    ]
)


def compute_coverage(alignment_length: int, sequence_length: int) -> float:
    """Calculate percent sequence coverage with defensive length checking."""

    if alignment_length < 0:
        raise ValueError("alignment_length cannot be negative")
    if sequence_length <= 0:
        raise ValueError("sequence_length must be positive")
    return min(100.0, 100.0 * alignment_length / sequence_length)


def classify_alignment(
    record: Mapping[str, object],
    thresholds: Thresholds,
) -> Dict[str, object]:
    """Add coverage and strict-threshold flags to one realignment record."""

    thresholds.validate()
    aligned = int(record["alignment_length"])
    representative_length = int(record["representative_length"])
    member_length = int(record["member_length"])
    representative_coverage = compute_coverage(aligned, representative_length)
    member_coverage = compute_coverage(aligned, member_length)
    pident = float(record["pident"])
    bitscore = float(record["bitscore"])
    evalue = float(record["evalue"])

    result = dict(record)
    result.update(
        {
            "representative_coverage": representative_coverage,
            "member_coverage": member_coverage,
            "passes_identity": pident >= thresholds.minimum_percent_identity,
            "passes_representative_coverage": representative_coverage
            >= thresholds.minimum_representative_coverage,
            "passes_member_coverage": member_coverage
            >= thresholds.minimum_member_coverage,
            "passes_bitscore": bitscore > thresholds.minimum_bitscore,
            "passes_evalue": evalue < thresholds.maximum_evalue,
        }
    )
    result["passes_all"] = all(
        result[key]
        for key in (
            "passes_identity",
            "passes_representative_coverage",
            "passes_member_coverage",
            "passes_bitscore",
            "passes_evalue",
        )
    )
    return result


def _normalise_cluster_header(fieldnames: Optional[List[str]]) -> Tuple[str, str]:
    if not fieldnames:
        raise DataValidationError("Cluster membership file has no header")
    lowered = {field.lower(): field for field in fieldnames}
    representative = lowered.get("representative") or lowered.get("cseqid")
    member = lowered.get("member") or lowered.get("mseqid")
    if not representative or not member:
        raise DataValidationError(
            "Cluster membership header must contain representative/member "
            "or cseqid/mseqid"
        )
    return representative, member


def cluster_tsv_to_parquet(
    input_tsv: Path,
    output_parquet: Path,
    batch_size: int = 250_000,
) -> Dict[str, int]:
    """Convert a DIAMOND two-column cluster file to compressed Parquet."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    LOGGER.info("Converting cluster membership TSV: %s", input_tsv)
    rows: List[Dict[str, object]] = []
    count = 0
    representatives = set()
    with open_text_auto(input_tsv) as handle, atomic_binary_path(
        output_parquet
    ) as temporary:
        reader = csv.DictReader(handle, delimiter="\t")
        representative_field, member_field = _normalise_cluster_header(
            reader.fieldnames
        )
        writer = pq.ParquetWriter(
            temporary,
            CLUSTER_SCHEMA,
            compression="zstd",
            use_dictionary=True,
        )
        try:
            for source_row, row in enumerate(reader, start=2):
                representative = str(row.get(representative_field, "")).strip()
                member = str(row.get(member_field, "")).strip()
                if not representative or not member:
                    raise DataValidationError(
                        f"Blank cluster identifier at row {source_row}"
                    )
                rows.append(
                    {
                        "representative_id": representative,
                        "member_id": member,
                        "source_row": source_row,
                    }
                )
                representatives.add(representative)
                count += 1
                if len(rows) >= batch_size:
                    writer.write_table(pa.Table.from_pylist(rows, CLUSTER_SCHEMA))
                    rows.clear()
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, CLUSTER_SCHEMA))
        finally:
            writer.close()
    if count == 0:
        raise DataValidationError("Cluster membership file contains no data rows")
    LOGGER.info(
        "Converted %d cluster membership rows across %d representatives",
        count,
        len(representatives),
    )
    return {"membership_rows": count, "cluster_count": len(representatives)}


def _required_realign_fields(fieldnames: Optional[List[str]]) -> Dict[str, str]:
    if not fieldnames:
        raise DataValidationError("Realignment file has no header")
    aliases = {
        "representative_id": ("qseqid", "cseqid", "representative_id"),
        "member_id": ("sseqid", "mseqid", "member_id"),
        "pident": ("pident", "approx_pident"),
        "representative_length": ("qlen", "representative_length"),
        "member_length": ("slen", "member_length"),
        "representative_start": ("qstart", "cstart", "representative_start"),
        "representative_end": ("qend", "cend", "representative_end"),
        "member_start": ("sstart", "mstart", "member_start"),
        "member_end": ("send", "mend", "member_end"),
        "alignment_length": ("length", "alignment_length"),
        "evalue": ("evalue",),
        "bitscore": ("bitscore", "Bitscore"),
    }
    available = {field.lower(): field for field in fieldnames}
    mapping: Dict[str, str] = {}
    for standard, candidates in aliases.items():
        matched = next(
            (
                available[candidate.lower()]
                for candidate in candidates
                if candidate.lower() in available
            ),
            None,
        )
        if matched is None:
            raise DataValidationError(
                f"Realignment file lacks required field for {standard}. "
                f"Available fields: {', '.join(fieldnames)}"
            )
        mapping[standard] = matched
    return mapping


def _parse_int(value: str, field: str, row_number: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            f"Invalid integer for {field} at row {row_number}: {value!r}"
        ) from error


def _parse_float(value: str, field: str, row_number: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            f"Invalid number for {field} at row {row_number}: {value!r}"
        ) from error


def realign_tsv_to_parquet(
    input_tsv: Path,
    output_parquet: Path,
    thresholds: Thresholds,
    batch_size: int = 250_000,
) -> Dict[str, int]:
    """Convert explicit DIAMOND realign output and classify strict matches."""

    thresholds.validate()
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    LOGGER.info("Converting and filtering realignment TSV: %s", input_tsv)
    rows: List[Dict[str, object]] = []
    total = 0
    passed = 0
    with open_text_auto(input_tsv) as handle, atomic_binary_path(
        output_parquet
    ) as temporary:
        reader = csv.DictReader(handle, delimiter="\t")
        mapping = _required_realign_fields(reader.fieldnames)
        writer = pq.ParquetWriter(
            temporary,
            REALIGN_SCHEMA,
            compression="zstd",
            use_dictionary=True,
        )
        try:
            for source_row, row in enumerate(reader, start=2):
                base = {
                    "representative_id": str(
                        row[mapping["representative_id"]]
                    ).strip(),
                    "member_id": str(row[mapping["member_id"]]).strip(),
                    "pident": _parse_float(
                        row[mapping["pident"]], "pident", source_row
                    ),
                    "representative_length": _parse_int(
                        row[mapping["representative_length"]],
                        "representative_length",
                        source_row,
                    ),
                    "member_length": _parse_int(
                        row[mapping["member_length"]],
                        "member_length",
                        source_row,
                    ),
                    "representative_start": _parse_int(
                        row[mapping["representative_start"]],
                        "representative_start",
                        source_row,
                    ),
                    "representative_end": _parse_int(
                        row[mapping["representative_end"]],
                        "representative_end",
                        source_row,
                    ),
                    "member_start": _parse_int(
                        row[mapping["member_start"]],
                        "member_start",
                        source_row,
                    ),
                    "member_end": _parse_int(
                        row[mapping["member_end"]],
                        "member_end",
                        source_row,
                    ),
                    "alignment_length": _parse_int(
                        row[mapping["alignment_length"]],
                        "alignment_length",
                        source_row,
                    ),
                    "evalue": _parse_float(
                        row[mapping["evalue"]], "evalue", source_row
                    ),
                    "bitscore": _parse_float(
                        row[mapping["bitscore"]], "bitscore", source_row
                    ),
                    "source_row": source_row,
                }
                if not base["representative_id"] or not base["member_id"]:
                    raise DataValidationError(
                        f"Blank realignment identifier at row {source_row}"
                    )
                classified = classify_alignment(base, thresholds)
                rows.append(classified)
                total += 1
                passed += int(bool(classified["passes_all"]))
                if len(rows) >= batch_size:
                    writer.write_table(pa.Table.from_pylist(rows, REALIGN_SCHEMA))
                    rows.clear()
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, REALIGN_SCHEMA))
        finally:
            writer.close()
    if total == 0:
        raise DataValidationError("Realignment file contains no data rows")
    LOGGER.info(
        "Converted %d realignments; %d passed all strict thresholds",
        total,
        passed,
    )
    return {"realignment_rows": total, "strict_pass_rows": passed}


def thresholds_from_mapping(values: Mapping[str, object]) -> Thresholds:
    """Construct validated Thresholds from a configuration mapping."""

    thresholds = Thresholds(
        minimum_percent_identity=float(values["minimum_percent_identity"]),
        minimum_representative_coverage=float(
            values["minimum_representative_coverage"]
        ),
        minimum_member_coverage=float(values["minimum_member_coverage"]),
        minimum_bitscore=float(values["minimum_bitscore"]),
        maximum_evalue=float(values["maximum_evalue"]),
    )
    thresholds.validate()
    return thresholds
