"""FPocket output discovery and parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import PocketResidueRecord
from .structure import read_pocket_atom_site_rows


_POCKET_HEADER = re.compile(r"^\s*Pocket\s+(\d+)\s*:?\s*$", re.IGNORECASE)
_KEY_VALUE = re.compile(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$")
_POCKET_FILE = re.compile(r"pocket(\d+)_atm\.(?:cif|pdb)$", re.IGNORECASE)


def normalise_metric_name(name: str) -> str:
    """Normalise an FPocket label into a stable snake-case field name.

    Args:
        name: Raw metric label.

    Returns:
        Lower-case snake-case field name.
    """

    value = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return value


def parse_scalar(value: str) -> str | int | float | None:
    """Parse a scalar FPocket value conservatively.

    Args:
        value: Raw value text.

    Returns:
        Integer, float, stripped string or ``None``.
    """

    stripped = value.strip()
    if not stripped or stripped.lower() in {"na", "nan", "none", "null"}:
        return None
    try:
        integer = int(stripped)
    except ValueError:
        try:
            return float(stripped)
        except ValueError:
            return stripped
    return integer


def discover_fpocket_info_files(root: Path) -> list[Path]:
    """Locate non-empty FPocket ``*_info.txt`` files recursively.

    Args:
        root: Accession-specific tool-output root.

    Returns:
        Sorted matching paths.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"FPocket output directory does not exist: {directory}")
    return sorted(
        path
        for path in directory.rglob("*_info.txt")
        if path.is_file() and path.stat().st_size > 0
    )


def parse_fpocket_info(path: Path, accession: str) -> list[dict[str, Any]]:
    """Parse one FPocket information file into pocket records.

    Args:
        path: FPocket ``*_info.txt`` file.
        accession: Protein accession.

    Returns:
        One dictionary per pocket in file order.

    Raises:
        FileNotFoundError: If the file is absent.
        ValueError: If no pocket blocks are found.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"FPocket info file does not exist: {source}")

    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in source.read_text(encoding="utf-8", errors="strict").splitlines():
        header_match = _POCKET_HEADER.match(line)
        if header_match:
            if current is not None:
                records.append(current)
            current = {
                "accession": accession,
                "pocket_number": int(header_match.group(1)),
                "fpocket_info_path": str(source),
            }
            continue
        if current is None:
            continue
        value_match = _KEY_VALUE.match(line)
        if value_match:
            key = normalise_metric_name(value_match.group(1))
            current[key] = parse_scalar(value_match.group(2))

    if current is not None:
        records.append(current)
    if not records:
        raise ValueError(f"No FPocket pocket blocks found in {source}")
    return records


def discover_pocket_atom_files(root: Path) -> list[tuple[int, Path]]:
    """Locate FPocket pocket-atom CIF/PDB files and extract pocket numbers.

    Args:
        root: Accession-specific tool-output root.

    Returns:
        Sorted ``(pocket_number, path)`` pairs.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"FPocket output directory does not exist: {directory}")
    matches: list[tuple[int, Path]] = []
    for path in directory.rglob("pocket*_atm.*"):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        match = _POCKET_FILE.search(path.name)
        if match:
            matches.append((int(match.group(1)), path.resolve()))
    return sorted(matches, key=lambda item: (item[0], str(item[1])))


def parse_pocket_cif_residues(
    path: Path,
    accession: str,
    pocket_number: int,
) -> list[PocketResidueRecord]:
    """Extract unique residue identifiers from one pocket mmCIF file.

    Args:
        path: FPocket pocket atom mmCIF.
        accession: Protein accession.
        pocket_number: FPocket pocket rank/number.

    Returns:
        Unique pocket residues.
    """

    source = Path(path).expanduser().resolve()
    atom_rows = read_pocket_atom_site_rows(source)
    unique: dict[
        tuple[str, int | None, str, int | None, str, str],
        PocketResidueRecord,
    ] = {}
    for row in atom_rows:
        key = (
            str(row["label_chain"]),
            row["label_seq_id"],
            str(row["auth_chain"]),
            row["auth_seq_id"],
            str(row["insertion_code"]),
            str(row["residue_name"]),
        )
        unique[key] = PocketResidueRecord(
            accession=accession,
            pocket_number=pocket_number,
            label_chain=key[0],
            label_seq_id=key[1],
            auth_chain=key[2],
            auth_seq_id=key[3],
            insertion_code=key[4],
            residue_name=key[5],
            source_file=str(source),
        )
    return sorted(
        unique.values(),
        key=lambda residue: (
            residue.label_chain,
            residue.label_seq_id is None,
            -1 if residue.label_seq_id is None else residue.label_seq_id,
            residue.auth_chain,
            residue.auth_seq_id is None,
            -1 if residue.auth_seq_id is None else residue.auth_seq_id,
            residue.insertion_code,
        ),
    )


def parse_all_pocket_residues(
    root: Path,
    accession: str,
) -> list[PocketResidueRecord]:
    """Parse residue identifiers from every discovered pocket atom mmCIF.

    Args:
        root: Accession-specific FPocket output root.
        accession: Protein accession.

    Returns:
        Combined pocket residue records.

    Raises:
        ValueError: If no pocket atom files are available.
    """

    files = discover_pocket_atom_files(root)
    if not files:
        raise ValueError(f"No FPocket pocket atom files found under {root}")
    records: list[PocketResidueRecord] = []
    for pocket_number, path in files:
        if path.suffix.lower() != ".cif":
            raise ValueError(
                "PDB pocket parsing is not implemented; expected mmCIF but found "
                f"{path}"
            )
        records.extend(parse_pocket_cif_residues(path, accession, pocket_number))
    return records
