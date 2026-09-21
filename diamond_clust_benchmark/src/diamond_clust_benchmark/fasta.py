"""Streaming protein FASTA profiling for benchmark provenance."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import IO, Dict

from diamond_clust_benchmark.exceptions import DataValidationError
from diamond_clust_benchmark.io_utils import write_json, write_tsv


def open_text(path: Path) -> IO[str]:
    """Open plain or gzip-compressed UTF-8 text.

    Args:
        path: Input text path.

    Returns:
        Read-only text handle.
    """

    source = Path(path)
    if source.suffix.lower() == ".gz":
        return gzip.open(source, "rt", encoding="utf-8")
    return source.open("r", encoding="utf-8")


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """Calculate a file SHA-256 checksum using bounded memory.

    Args:
        path: File to hash.
        block_size: Positive binary read size.

    Returns:
        Lower-case hexadecimal checksum.

    Raises:
        ValueError: If ``block_size`` is not positive.
    """

    if block_size < 1:
        raise ValueError("block_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_fasta(path: Path) -> Dict[str, object]:
    """Count FASTA records and amino-acid residues defensively.

    Args:
        path: Plain or gzip-compressed protein FASTA.

    Returns:
        Mapping of input size, checksum, record and residue counts.

    Raises:
        FileNotFoundError: If the FASTA is absent.
        DataValidationError: If the FASTA is empty or malformed.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"FASTA does not exist: {source}")
    sequences = 0
    residues = 0
    current_residues = 0
    saw_header = False
    with open_text(source) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if len(line) == 1:
                    raise DataValidationError(
                        f"Blank FASTA identifier at line {line_number}"
                    )
                if saw_header and current_residues == 0:
                    raise DataValidationError(
                        f"Empty FASTA sequence before line {line_number}"
                    )
                sequences += 1
                saw_header = True
                current_residues = 0
                continue
            if not saw_header:
                raise DataValidationError(
                    f"Sequence text precedes the first header at line {line_number}"
                )
            compact = "".join(line.split())
            current_residues += len(compact)
            residues += len(compact)
    if not saw_header:
        raise DataValidationError(f"FASTA contains no records: {source}")
    if current_residues == 0:
        raise DataValidationError("The final FASTA record has no sequence")
    return {
        "input_fasta": str(source),
        "input_bytes": source.stat().st_size,
        "input_sha256": sha256_file(source),
        "sequence_count": sequences,
        "residue_count": residues,
    }


def write_fasta_profile(profile: Dict[str, object], output_path: Path) -> None:
    """Write one FASTA profile as TSV and adjacent JSON.

    Args:
        profile: Profile returned by :func:`profile_fasta`.
        output_path: Destination TSV path.
    """

    fields = [
        "input_fasta",
        "input_bytes",
        "input_sha256",
        "sequence_count",
        "residue_count",
    ]
    write_tsv(output_path, [profile], fields)
    write_json(Path(output_path).with_suffix(".json"), profile)
