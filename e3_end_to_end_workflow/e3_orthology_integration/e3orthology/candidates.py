"""Streaming candidate-evidence input parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pyarrow.parquet as pq

from .errors import InputValidationError
from .io_utils import ensure_readable_file


@dataclass(frozen=True)
class CandidateRecord:
    """One candidate accession linked to one DeepClust representative."""

    cluster_id: str
    candidate_accession: str
    representative_original_id: str
    representative_entry: str


def split_candidate_accessions(*, value: str | None, delimiter: str) -> tuple[str, ...]:
    """Split, trim, de-duplicate and sort one candidate accession field.

    Args:
        value: Delimited candidate accession value.
        delimiter: Explicit configured delimiter.

    Returns:
        Sorted unique non-empty accessions.

    Raises:
        ValueError: If the delimiter is empty.
    """

    if not delimiter:
        raise ValueError("Candidate delimiter must not be empty.")
    if value is None:
        return ()
    return tuple(sorted({token.strip() for token in str(value).split(delimiter) if token.strip()}))


def iter_candidate_records(
    *,
    parquet_path: Path,
    cluster_column: str,
    accession_column: str,
    representative_original_id_column: str,
    representative_entry_column: str,
    delimiter: str,
    batch_size: int = 65_536,
) -> Iterator[CandidateRecord]:
    """Yield normalised candidate records from the v0.4.0 Parquet resource.

    Args:
        parquet_path: Candidate evidence Parquet.
        cluster_column: DeepClust representative identifier column.
        accession_column: Delimited candidate accession column.
        representative_original_id_column: Rich representative identifier column.
        representative_entry_column: Representative entry column.
        delimiter: Candidate accession delimiter.
        batch_size: Parquet records read per batch.

    Yields:
        One record per unique cluster-accession combination.

    Raises:
        InputValidationError: If required columns or values are absent.
        ValueError: If ``batch_size`` is not positive.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")
    source = ensure_readable_file(path=parquet_path)
    parquet = pq.ParquetFile(source)
    required_columns = (
        cluster_column,
        accession_column,
        representative_original_id_column,
        representative_entry_column,
    )
    missing = sorted(set(required_columns) - set(parquet.schema_arrow.names))
    if missing:
        raise InputValidationError(
            f"Candidate Parquet is missing required columns: {', '.join(missing)}"
        )
    seen: set[tuple[str, str]] = set()
    for batch in parquet.iter_batches(columns=list(required_columns), batch_size=batch_size):
        values = batch.to_pydict()
        for row_index in range(batch.num_rows):
            cluster_value = values[cluster_column][row_index]
            if cluster_value is None or not str(cluster_value).strip():
                raise InputValidationError(
                    "Candidate Parquet contains an empty cluster identifier."
                )
            cluster_id = str(cluster_value).strip()
            accessions = split_candidate_accessions(
                value=values[accession_column][row_index],
                delimiter=delimiter,
            )
            if not accessions:
                raise InputValidationError(
                    f"Candidate cluster {cluster_id!r} contains no candidate accessions."
                )
            original_value = values[representative_original_id_column][row_index]
            entry_value = values[representative_entry_column][row_index]
            for accession in accessions:
                key = (cluster_id, accession)
                if key in seen:
                    continue
                seen.add(key)
                yield CandidateRecord(
                    cluster_id=cluster_id,
                    candidate_accession=accession,
                    representative_original_id=(
                        "" if original_value is None else str(original_value).strip()
                    ),
                    representative_entry="" if entry_value is None else str(entry_value).strip(),
                )


def load_candidate_index(
    *,
    parquet_path: Path,
    cluster_column: str,
    accession_column: str,
    representative_original_id_column: str,
    representative_entry_column: str,
    delimiter: str,
) -> dict[str, list[CandidateRecord]]:
    """Index candidate records by accession for streamed membership joins.

    Args:
        parquet_path: Candidate evidence Parquet.
        cluster_column: DeepClust representative identifier column.
        accession_column: Delimited candidate accession column.
        representative_original_id_column: Rich representative identifier column.
        representative_entry_column: Representative entry column.
        delimiter: Candidate accession delimiter.

    Returns:
        Candidate accession to associated cluster records.
    """

    index: dict[str, list[CandidateRecord]] = {}
    for record in iter_candidate_records(
        parquet_path=parquet_path,
        cluster_column=cluster_column,
        accession_column=accession_column,
        representative_original_id_column=representative_original_id_column,
        representative_entry_column=representative_entry_column,
        delimiter=delimiter,
    ):
        index.setdefault(record.candidate_accession, []).append(record)
    return index
