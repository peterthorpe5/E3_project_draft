"""Streaming conversion and filtering of DIAMOND clustering outputs."""

from __future__ import annotations

import logging
import csv
import re
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
    """Store strict post-realignment classification thresholds.

    Attributes:
        minimum_percent_identity: Minimum accepted alignment identity percent.
        minimum_representative_coverage: Minimum percent of the representative
            sequence covered by the alignment.
        minimum_member_coverage: Minimum percent of the member sequence covered
            by the alignment.
        minimum_bitscore: Exclusive lower bound for DIAMOND bit score.
        maximum_evalue: Exclusive upper bound for DIAMOND e-value.
    """

    minimum_percent_identity: float
    minimum_representative_coverage: float
    minimum_member_coverage: float
    minimum_bitscore: float
    maximum_evalue: float

    def validate(self) -> None:
        """Validate that all threshold values are scientifically and numerically valid.

        Returns:
            None.

        Raises:
            ValueError: If identity or coverage is outside ``(0, 100]``, or if bit
                score or e-value thresholds are not positive.
        """

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
    """Calculate alignment coverage as a percentage of sequence length.

    Coverage is capped at 100 percent to protect downstream tables from minor
    coordinate inconsistencies in external alignment output.

    Args:
        alignment_length: Number of aligned residues.
        sequence_length: Full length of the sequence being assessed.

    Returns:
        Alignment coverage in the inclusive range ``0.0`` to ``100.0``.

    Raises:
        ValueError: If ``alignment_length`` is negative or
            ``sequence_length`` is not positive.
    """

    if alignment_length < 0:
        raise ValueError("alignment_length cannot be negative")
    if sequence_length <= 0:
        raise ValueError("sequence_length must be positive")
    return min(100.0, 100.0 * alignment_length / sequence_length)


def classify_alignment(
    record: Mapping[str, object],
    thresholds: Thresholds,
) -> Dict[str, object]:
    """Calculate coverage and classify one representative-member alignment.

    The returned record retains all input fields and adds coverage percentages,
    one Boolean flag per threshold, and a combined ``passes_all`` flag.

    Args:
        record: Mapping containing alignment length, sequence lengths, identity,
            bit score and e-value fields.
        thresholds: Validated strict classification thresholds.

    Returns:
        A new dictionary containing the original fields plus derived metrics and
        pass/fail flags.

    Raises:
        KeyError: If a required alignment field is absent.
        TypeError: If a required value cannot be converted numerically.
        ValueError: If numeric values or thresholds are invalid.
    """

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


_CLUSTER_REPRESENTATIVE_HEADERS = {
    "representative",
    "representative_id",
    "cluster_representative",
    "cluster_representative_id",
    "centroid",
    "centroid_id",
    "cluster",
    "cseqid",
    "qseqid",
}
_CLUSTER_MEMBER_HEADERS = {
    "member",
    "member_id",
    "cluster_member",
    "cluster_member_id",
    "mseqid",
    "sseqid",
}


def _normalise_header_token(value: str) -> str:
    """Normalise an external table header token for alias matching.

    Args:
        value: Raw header value from a DIAMOND-generated table.

    Returns:
        A lowercase underscore-delimited token without leading comment marks.
    """

    token = str(value).strip().lower().lstrip("#")
    token = re.sub(r"[^a-z0-9]+", "_", token).strip("_")
    return token


def _normalise_cluster_header(
    fieldnames: Optional[List[str]],
) -> Optional[Tuple[int, int]]:
    """Identify a recognised representative/member cluster header.

    DIAMOND clustering output is a fixed two-column table. A return value of
    ``None`` means the supplied first row should be interpreted positionally as
    data rather than as an unrecognised header.

    Args:
        fieldnames: Two values from the first non-comment cluster row.

    Returns:
        ``(0, 1)`` for a recognised representative/member header, otherwise
        ``None`` for a valid positional data row.

    Raises:
        DataValidationError: If the file is empty or the row does not contain
            exactly two fields.
    """

    if not fieldnames:
        raise DataValidationError("Cluster membership file is empty")
    if len(fieldnames) != 2:
        raise DataValidationError(
            "Cluster membership rows must contain exactly two tab-separated "
            f"columns; observed {len(fieldnames)} columns"
        )
    normalised = [_normalise_header_token(field) for field in fieldnames]
    if (
        normalised[0] in _CLUSTER_REPRESENTATIVE_HEADERS
        and normalised[1] in _CLUSTER_MEMBER_HEADERS
    ):
        return 0, 1
    return None


def cluster_tsv_to_parquet(
    input_tsv: Path,
    output_parquet: Path,
    batch_size: int = 250_000,
) -> Dict[str, int]:
    """Stream DIAMOND cluster membership from TSV to Parquet.

    The first column is interpreted as the cluster representative and the second
    as the member. Native and recognised alternative headers are skipped;
    headerless historical files are accepted. Blank rows and DIAMOND comments
    are ignored, while malformed rows fail validation.

    Args:
        input_tsv: DIAMOND two-column cluster-membership table.
        output_parquet: Destination for normalised cluster membership Parquet.
        batch_size: Maximum number of records held before each Parquet write.

    Returns:
        Counts for membership rows and unique cluster representatives.

    Raises:
        ValueError: If ``batch_size`` is smaller than one.
        FileNotFoundError: If ``input_tsv`` does not exist.
        DataValidationError: If rows are malformed, identifiers are blank, or
            the file contains no membership data.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    LOGGER.info("Converting cluster membership TSV: %s", input_tsv)
    rows: List[Dict[str, object]] = []
    count = 0
    representatives = set()
    first_data_or_header_seen = False
    header_detected = False
    with open_text_auto(input_tsv) as handle, atomic_binary_path(
        output_parquet
    ) as temporary:
        reader = csv.reader(handle, delimiter="\t")
        writer = pq.ParquetWriter(
            temporary,
            CLUSTER_SCHEMA,
            compression="zstd",
            use_dictionary=True,
        )
        try:
            for source_row, fields in enumerate(reader, start=1):
                if not fields or all(not str(value).strip() for value in fields):
                    continue
                if len(fields) == 1 and str(fields[0]).lstrip().startswith("#"):
                    LOGGER.debug(
                        "Skipping DIAMOND cluster comment at row %d", source_row
                    )
                    continue
                if len(fields) != 2:
                    raise DataValidationError(
                        "Cluster membership rows must contain exactly two "
                        f"tab-separated columns; row {source_row} has "
                        f"{len(fields)} columns: {fields!r}"
                    )
                if not first_data_or_header_seen:
                    first_data_or_header_seen = True
                    if _normalise_cluster_header(list(fields)) is not None:
                        header_detected = True
                        LOGGER.info(
                            "Detected cluster membership header at row %d: %s",
                            source_row,
                            fields,
                        )
                        continue
                    LOGGER.info(
                        "No cluster header detected; using DIAMOND's official "
                        "positional two-column format"
                    )
                representative = str(fields[0]).strip()
                member = str(fields[1]).strip()
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
    if not first_data_or_header_seen:
        raise DataValidationError("Cluster membership file contains no rows")
    if count == 0:
        detail = " after its header" if header_detected else ""
        raise DataValidationError(
            f"Cluster membership file contains no data rows{detail}"
        )
    LOGGER.info(
        "Converted %d cluster membership rows across %d representatives",
        count,
        len(representatives),
    )
    return {"membership_rows": count, "cluster_count": len(representatives)}


def _required_realign_fields(fieldnames: Optional[List[str]]) -> Dict[str, str]:
    """Map supported DIAMOND realignment headers to canonical field names.

    Query/subject and centroid/member aliases are accepted, including native
    DIAMOND 2.2.x names such as ``clen``, ``mlen`` and ``Bitscore``.

    Args:
        fieldnames: Header names parsed from the realignment table.

    Returns:
        Mapping from each canonical field name to its source header name.

    Raises:
        DataValidationError: If the header is absent or any required alignment
            field cannot be resolved.
    """
    if not fieldnames:
        raise DataValidationError("Realignment file has no header")
    aliases = {
        "representative_id": ("qseqid", "cseqid", "representative_id"),
        "member_id": ("sseqid", "mseqid", "member_id"),
        "pident": ("pident", "approx_pident"),
        "representative_length": (
            "qlen",
            "clen",
            "representative_length",
        ),
        "member_length": ("slen", "mlen", "member_length"),
        "representative_start": ("qstart", "cstart", "representative_start"),
        "representative_end": ("qend", "cend", "representative_end"),
        "member_start": ("sstart", "mstart", "member_start"),
        "member_end": ("send", "mend", "member_end"),
        "alignment_length": ("length", "alignment_length"),
        "evalue": ("evalue",),
        "bitscore": ("bitscore", "Bitscore"),
    }
    available = {_normalise_header_token(field): field for field in fieldnames}
    mapping: Dict[str, str] = {}
    for standard, candidates in aliases.items():
        matched = next(
            (
                available[_normalise_header_token(candidate)]
                for candidate in candidates
                if _normalise_header_token(candidate) in available
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
    """Parse an integer-valued alignment field with row-aware diagnostics.

    Numeric strings containing an integral floating representation are accepted
    for compatibility with external tabular output.

    Args:
        value: Raw field value.
        field: Canonical field name used in error messages.
        row_number: One-based source row number.

    Returns:
        Parsed integer value.

    Raises:
        DataValidationError: If ``value`` cannot be converted to an integer.
    """
    try:
        return int(float(value))
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            f"Invalid integer for {field} at row {row_number}: {value!r}"
        ) from error


def _parse_float(value: str, field: str, row_number: int) -> float:
    """Parse a floating-point alignment field with row-aware diagnostics.

    Args:
        value: Raw field value.
        field: Canonical field name used in error messages.
        row_number: One-based source row number.

    Returns:
        Parsed floating-point value.

    Raises:
        DataValidationError: If ``value`` cannot be converted to a float.
    """
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
    """Convert DIAMOND realignment output and apply strict membership thresholds.

    Header aliases are normalised, numeric fields are validated, representative
    and member coverage are calculated, and every alignment receives individual
    and combined threshold flags before being written in Parquet batches.

    Args:
        input_tsv: Headered DIAMOND realignment table.
        output_parquet: Destination for classified realignment Parquet.
        thresholds: Strict post-realignment classification thresholds.
        batch_size: Maximum number of records held before each Parquet write.

    Returns:
        Counts for total realignment rows and rows passing all thresholds.

    Raises:
        ValueError: If thresholds are invalid or ``batch_size`` is below one.
        FileNotFoundError: If ``input_tsv`` does not exist.
        DataValidationError: If headers, identifiers or numeric fields are
            invalid.
    """

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
        LOGGER.warning(
            "Realignment file contains no pairwise data rows. This is valid "
            "when all clusters are singletons, but should be reviewed for "
            "unexpectedly empty non-singleton datasets."
        )
    else:
        LOGGER.info(
            "Converted %d realignments; %d passed all strict thresholds",
            total,
            passed,
        )
    return {"realignment_rows": total, "strict_pass_rows": passed}


def thresholds_from_mapping(values: Mapping[str, object]) -> Thresholds:
    """Construct and validate thresholds from a configuration mapping.

    Args:
        values: Mapping containing all five strict-threshold configuration keys.

    Returns:
        A validated immutable :class:`Thresholds` instance.

    Raises:
        KeyError: If a required threshold key is absent.
        TypeError: If a threshold cannot be converted to a float.
        ValueError: If a threshold lies outside its accepted range.
    """

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
