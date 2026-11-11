"""Read selected results exported by the external DeepClust search application."""

from __future__ import annotations

import logging

import pyarrow as pa
from pyarrow import parquet

from .common import ResearchError, normalise_protein
from .viewer_inputs import UPLOAD_BYTES

LOGGER = logging.getLogger(__name__)
PARQUET_UPLOAD_BYTES = 200_000_000


def open_results(*, content: bytes) -> parquet.ParquetFile:
    """Open a bounded self-contained Parquet file without accessing a DeepClust database.

    Args:
        content: Uploaded export bytes.

    Returns:
        An in-memory Parquet reader.

    Raises:
        ResearchError: If the export is invalid, uses external column files or exceeds bounds.
    """
    if not content or len(content) > PARQUET_UPLOAD_BYTES:
        raise ResearchError("Upload a DeepClust results Parquet file of at most 200 MB")
    try:
        reader = parquet.ParquetFile(
            source=pa.BufferReader(content), thrift_string_size_limit=16_000_000,
            thrift_container_size_limit=1_000_000,
        )
    except (pa.ArrowException, OSError) as exc:
        raise ResearchError("Could not open the uploaded DeepClust results as Parquet") from exc
    metadata = reader.metadata
    if not 1 <= metadata.num_rows <= 2_000_000 or not 1 <= metadata.num_columns <= 128:
        raise ResearchError("Export 1–2,000,000 result rows with at most 128 columns")
    names = reader.schema_arrow.names
    if len(set(names)) != len(names):
        raise ResearchError("DeepClust export columns must have unique names")
    total_bytes = 0
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        total_bytes += group.total_byte_size
        if total_bytes > 1_000_000_000:
            raise ResearchError("Export a smaller DeepClust result for browser inspection")
        if any(group.column(column).file_path for column in range(group.num_columns)):
            raise ResearchError("DeepClust export must contain its own column data")
    return reader


def results_preview(*, reader: parquet.ParquetFile) -> pa.Table:
    """Return up to 100 result rows while retaining the uploaded column names.

    Args:
        reader: Validated DeepClust results reader.

    Returns:
        A table suitable for a bounded screen preview.
    """
    try:
        return pa.Table.from_batches([next(reader.iter_batches(batch_size=100))])
    except (pa.ArrowException, OSError, StopIteration) as exc:
        raise ResearchError("Could not decode the uploaded Parquet preview") from exc


def extract_family(
    *, reader: parquet.ParquetFile, id_column: str, sequence_column: str,
    cluster_column: str = "", cluster_id: str = "",
) -> str:
    """Extract the complete selected family and validate exact protein identifiers.

    Args:
        reader: Validated DeepClust export reader.
        id_column: User-selected protein identifier field.
        sequence_column: User-selected amino-acid sequence field.
        cluster_column: Optional cluster identifier field.
        cluster_id: Exact cluster value to retain when a cluster field is selected.

    Returns:
        Standalone protein FASTA. Identical repeated rows collapse to one protein.

    Raises:
        ResearchError: For missing fields, ambiguous identifiers or invalid FASTA data.
    """
    columns = [id_column, sequence_column] + ([cluster_column] if cluster_column else [])
    if (len(set(columns)) != len(columns) or not set(columns).issubset(reader.schema_arrow.names)
            or bool(cluster_column) != bool(cluster_id)):
        raise ResearchError("Select distinct identifier, sequence and optional cluster columns")
    records = {}
    size = 0
    try:
        for batch in reader.iter_batches(batch_size=2_048, columns=columns):
            for row in batch.to_pylist():
                if cluster_column and str(row[cluster_column]) != cluster_id:
                    continue
                value = row[id_column]
                identifier = str(value) if value is not None else ""
                if (not identifier or identifier.startswith(">")
                        or any(c.isspace() or ord(c) < 32 for c in identifier)):
                    raise ResearchError("Every selected row needs a whitespace-free protein ID")
                sequence = row[sequence_column]
                if not isinstance(sequence, str):
                    raise ResearchError(f"Protein {identifier} lacks amino-acid sequence text")
                sequence = normalise_protein(sequence=sequence)
                if identifier in records:
                    if records[identifier] != sequence:
                        raise ResearchError(f"Conflicting sequences for protein ID {identifier}")
                    continue
                size += len(identifier.encode()) + len(sequence) + 3
                if size > UPLOAD_BYTES:
                    raise ResearchError("Select a smaller family. FASTA export is limited to 20 MB")
                records[identifier] = sequence
    except (pa.ArrowException, OSError) as exc:
        raise ResearchError("Could not decode the selected Parquet sequence columns") from exc
    if not records:
        raise ResearchError("The selected result contains no protein records")
    LOGGER.info("Prepared %d proteins from external DeepClust result", len(records))
    return "".join(f">{identifier}\n{sequence}\n" for identifier, sequence in records.items())
