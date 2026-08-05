"""Checksum-bound structure and mapped pocket-residue resolution."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from e3chemistry.errors import DependencyError, InputValidationError
from e3chemistry.io_utils import require_columns, sha256_file
from e3chemistry.models import Coordinate, ResidueGeometry, StructureAsset

LOGGER = logging.getLogger("e3chemistry.structures")
STRUCTURE_SUFFIXES = frozenset({".cif", ".mmcif", ".pdb"})


def _text(value: Any) -> str:
    """Return stripped text for one possibly missing value."""
    return "" if value is None else str(value).strip()


def _integer(value: Any, label: str) -> int:
    """Parse one required integer without accepting silent truncation."""
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{label} must be an integer: {value!r}") from exc
    return result


def resolve_structure_assets(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, StructureAsset]:
    """Resolve one existing, checksum-validated model per accession.

    Args:
        records: Asset-manifest records.

    Returns:
        Upper-case accession keys mapped to validated structure assets.

    Raises:
        InputValidationError: If checksums conflict or no usable asset exists.
    """
    require_columns(records=records, required=("accession",), label="asset manifest")
    path_fields = ("path", "model_path", "source_path")
    candidates: dict[str, list[tuple[int, StructureAsset]]] = defaultdict(list)
    for record in records:
        accession = _text(record.get("accession")).upper()
        if not accession:
            continue
        for priority, field in enumerate(path_fields):
            raw_path = _text(record.get(field))
            if not raw_path:
                continue
            path = Path(raw_path).expanduser().resolve()
            if path.suffix.lower() not in STRUCTURE_SUFFIXES or not path.is_file():
                continue
            observed = sha256_file(path)
            expected = _text(record.get("sha256")).lower()
            if expected and expected != observed:
                raise InputValidationError(
                    f"Structure checksum mismatch for {accession}: {path}"
                )
            candidates[accession].append(
                (
                    priority,
                    StructureAsset(accession=accession, path=path, sha256=observed),
                )
            )
    if not candidates:
        raise InputValidationError("Asset manifest contains no usable structure files")
    resolved = {}
    for accession, options in candidates.items():
        ordered = sorted(options, key=lambda item: (item[0], str(item[1].path)))
        chosen = ordered[0][1]
        conflicting = {item[1].sha256 for item in ordered}
        if len(conflicting) > 1:
            raise InputValidationError(
                f"Asset manifest contains conflicting structures for {accession}"
            )
        resolved[accession] = chosen
    return resolved


def mapped_residue_locators(
    *,
    records: Sequence[Mapping[str, Any]],
    accession: str,
    pocket_number: int,
) -> list[dict[str, str]]:
    """Return unique mapped residue locators for one selected pocket."""
    require_columns(
        records=records,
        required=("accession", "pocket_number", "mapping_status"),
        label="pocket residue mappings",
    )
    selected: dict[tuple[str, str, str], dict[str, str]] = {}
    accession_key = accession.upper()
    for record in records:
        if _text(record.get("accession")).upper() != accession_key:
            continue
        if _integer(record.get("pocket_number"), "pocket_number") != pocket_number:
            continue
        if _text(record.get("mapping_status")).upper() != "MAPPED":
            continue
        chain_id = _text(
            record.get("model_auth_chain")
            or record.get("model_label_chain")
            or record.get("auth_chain")
            or record.get("label_chain")
        )
        sequence_id = _text(
            record.get("model_auth_seq_id")
            or record.get("model_label_seq_id")
            or record.get("auth_seq_id")
            or record.get("label_seq_id")
        )
        insertion_code = _text(
            record.get("model_insertion_code") or record.get("insertion_code")
        )
        if not chain_id or not sequence_id:
            continue
        key = (chain_id, sequence_id, insertion_code)
        selected[key] = {
            "chain_id": chain_id,
            "sequence_id": sequence_id,
            "insertion_code": insertion_code,
        }
    return [selected[key] for key in sorted(selected)]


def _residue_matches(
    *, residue: Any, sequence_id: str, insertion_code: str
) -> bool:
    """Return whether a Gemmi residue matches an author residue locator."""
    residue_number = str(residue.seqid.num)
    residue_insertion = str(residue.seqid.icode).strip()
    normalised_insertion = insertion_code.strip()
    return residue_number == sequence_id and residue_insertion == normalised_insertion


def load_pocket_residues(
    *,
    asset: StructureAsset,
    pocket_number: int,
    locators: Sequence[Mapping[str, str]],
) -> list[ResidueGeometry]:
    """Load mapped residue atom coordinates from one PDB or mmCIF structure.

    Args:
        asset: Checksum-validated structure asset.
        pocket_number: Selected pocket identifier.
        locators: Author chain, sequence and insertion-code locators.

    Returns:
        Mapped pocket residues with non-hydrogen atom coordinates.

    Raises:
        DependencyError: If Gemmi is unavailable.
        InputValidationError: If the structure cannot be parsed or no locator resolves.
    """
    try:
        import gemmi
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise DependencyError("Gemmi is required to read protein structures") from exc
    try:
        structure = gemmi.read_structure(str(asset.path))
    except (RuntimeError, ValueError) as exc:
        raise InputValidationError(f"Could not parse structure {asset.path}: {exc}") from exc
    if len(structure) == 0:
        raise InputValidationError(f"Structure contains no models: {asset.path}")
    model = structure[0]
    resolved: list[ResidueGeometry] = []
    unresolved = []
    for locator in locators:
        chain_id = _text(locator.get("chain_id"))
        sequence_id = _text(locator.get("sequence_id"))
        insertion_code = _text(locator.get("insertion_code"))
        matched = None
        for chain in model:
            if str(chain.name).strip() != chain_id:
                continue
            for residue in chain:
                if _residue_matches(
                    residue=residue,
                    sequence_id=sequence_id,
                    insertion_code=insertion_code,
                ):
                    matched = residue
                    break
            if matched is not None:
                break
        if matched is None:
            unresolved.append(f"{chain_id}:{sequence_id}{insertion_code}")
            continue
        atoms = {
            str(atom.name).strip(): Coordinate(
                x=float(atom.pos.x),
                y=float(atom.pos.y),
                z=float(atom.pos.z),
            )
            for atom in matched
            if str(atom.element.name).upper() != "H"
        }
        if not atoms:
            unresolved.append(f"{chain_id}:{sequence_id}{insertion_code}")
            continue
        resolved.append(
            ResidueGeometry(
                accession=asset.accession,
                pocket_number=pocket_number,
                chain_id=chain_id,
                sequence_id=sequence_id,
                insertion_code=insertion_code,
                residue_name=str(matched.name).strip().upper(),
                atoms=atoms,
            )
        )
    if unresolved:
        LOGGER.warning(
            "Structure %s did not resolve %d mapped pocket residues: %s",
            asset.accession,
            len(unresolved),
            ";".join(unresolved),
        )
    if not resolved:
        raise InputValidationError(
            f"No mapped pocket residue resolved in structure for {asset.accession}"
        )
    return resolved
