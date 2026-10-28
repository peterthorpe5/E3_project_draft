"""Strict sequence/manifest input and portable JSON/TSV output."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .models import Sample

LOGGER = logging.getLogger(__name__)


def sha256_file(*, path: Path) -> str:
    """Hash a file without loading it into memory.

    Args:
        path: Existing file.

    Returns:
        Hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open(mode="rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(*, path: Path, data: Any) -> None:
    """Atomically replace a JSON file using strict finite numeric values.

    Args:
        path: Destination.
        data: JSON-compatible value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        data=json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target=path)


def write_tsv(*, path: Path, rows: list[dict], columns: list[str]) -> None:
    """Write a header even for an empty table; preserve numbers and nulls.

    Args:
        path: Destination.
        rows: Records keyed by stable field names.
        columns: Explicit ordered schema.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            f=handle, fieldnames=columns, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rowdicts=rows)


def read_fasta(*, path: Path | None) -> dict[str, str]:
    """Read unique protein FASTA identifiers without heuristic ID rewriting.

    Args:
        path: Optional protein FASTA.

    Returns:
        First-header-token identifier to upper-case sequence.

    Raises:
        ValueError: For duplicates, empty records, gaps or invalid residues.
    """
    if path is None:
        return {}
    records: dict[str, str] = {}
    identifier = None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if not line[1:].strip():
                raise ValueError("FASTA contains a blank identifier")
            identifier = line[1:].split()[0]
            if identifier in records:
                raise ValueError(f"Duplicate FASTA identifier: {identifier}")
            records[identifier] = ""
        elif identifier is None:
            raise ValueError("FASTA sequence occurs before its header")
        else:
            records[identifier] += line.upper()
    if not records:
        raise ValueError("FASTA has no records")
    for identifier, sequence in records.items():
        if not sequence or set(sequence) - set("ACDEFGHIKLMNPQRSTVWYBXZJUO"):
            raise ValueError(f"Invalid or empty protein FASTA: {identifier}")
    return records


def load_samples(
    *, models: Path | None, manifest: Path | None, fasta: Path | None, chain: str
) -> list[Sample]:
    """Load either a flat model folder or a TSV with explicit sequence mapping.

    Args:
        models: Flat PDB/mmCIF directory, mutually exclusive with manifest.
        manifest: TSV with sample_id and model_path; paths relative to the TSV.
        fasta: Optional representative FASTA.
        chain: Default author chain selection.

    Returns:
        Validated samples sorted deterministically by sample_id.

    Raises:
        ValueError: For duplicate IDs, missing sequence IDs or malformed input.
    """
    if (models is None) == (manifest is None):
        raise ValueError("Supply exactly one of --models or --manifest")
    sequences = read_fasta(path=fasta)
    entries = []
    if models is not None:
        if not models.is_dir():
            raise ValueError(f"Model folder does not exist: {models}")
        entries = [
            {"sample_id": path.stem, "model_path": str(path.resolve())}
            for path in sorted(models.iterdir())
            if path.is_file() and path.suffix.lower() in {".pdb", ".cif", ".mmcif"}
        ]
        base = models.resolve()
    else:
        assert manifest is not None
        base = manifest.resolve().parent
        with manifest.open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(f=handle, delimiter="\t")
            if not {"sample_id", "model_path"} <= set(reader.fieldnames or []):
                raise ValueError("Manifest needs TSV columns sample_id and model_path")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("Manifest has an inconsistent number of fields")
                entries.append({key: value.strip() for key, value in row.items()})
    if not entries:
        raise ValueError("No input models found")
    samples = []
    seen: set[str] = set()
    for row in entries:
        identifier = row["sample_id"]
        if identifier.casefold() in seen:
            raise ValueError(f"Duplicate sample_id (case insensitive): {identifier}")
        seen.add(identifier.casefold())
        sequence_id = row.get("sequence_id") or (identifier if sequences else "")
        if sequence_id and sequence_id not in sequences:
            raise ValueError(
                f"FASTA identifier {sequence_id!r} missing for {identifier}; "
                "use --manifest to map filenames to sequence_id"
            )
        if not row["model_path"]:
            raise ValueError(f"Missing model_path for {identifier}")
        samples.append(
            Sample(
                sample_id=identifier,
                model_path=(base / Path(row["model_path"]).expanduser()).resolve(),
                sequence_id=sequence_id,
                sequence=sequences.get(sequence_id, ""),
                cluster=row.get("cluster", ""),
                chain=row.get("chain") or chain,
            )
        )
    unused = set(sequences) - {sample.sequence_id for sample in samples}
    if unused:
        LOGGER.warning("Unused FASTA identifiers: %s", "; ".join(sorted(unused)))
    return sorted(samples, key=lambda sample: sample.sample_id)
