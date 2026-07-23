"""PDB/mmCIF C-alpha parsing and pocket geometry."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from e3structalign.errors import InputValidationError
from e3structalign.models import AtomCoordinate, ResidueLocator, Transform


def _normalise_identifier(value: Any) -> str:
    """Return a stripped mmCIF/PDB identifier, mapping null tokens to empty."""
    text = "" if value is None else str(value).strip()
    return "" if text in {"", ".", "?"} else text


def _as_list(value: Any, length: int, default: str = "") -> list[str]:
    """Return one mmCIF field as a list with the requested length."""
    if value is None:
        return [default] * length
    values = [str(item) for item in value] if isinstance(value, list) else [str(value)]
    if len(values) == 1 and length > 1:
        return values * length
    if len(values) != length:
        raise InputValidationError(
            f"mmCIF atom-site column length {len(values)} does not match {length}"
        )
    return values


def parse_pdb_ca_atoms(path: Path) -> list[AtomCoordinate]:
    """Parse first-model C-alpha atoms from a PDB coordinate file."""
    atoms: list[AtomCoordinate] = []
    model_seen = False
    with Path(path).open("r", encoding="utf-8", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = line[:6].strip()
            if record == "MODEL":
                if model_seen:
                    break
                model_seen = True
                continue
            if record == "ENDMDL":
                break
            if record not in {"ATOM", "HETATM"} or line[12:16].strip() != "CA":
                continue
            alternate = line[16:17].strip()
            if alternate not in {"", "A"}:
                continue
            try:
                atoms.append(
                    AtomCoordinate(
                        label_chain=line[21:22].strip(),
                        label_seq_id=line[22:26].strip(),
                        auth_chain=line[21:22].strip(),
                        auth_seq_id=line[22:26].strip(),
                        insertion_code=line[26:27].strip(),
                        x=float(line[30:38]),
                        y=float(line[38:46]),
                        z=float(line[46:54]),
                    )
                )
            except ValueError as exc:
                raise InputValidationError(
                    f"Malformed PDB C-alpha record at {path}:{line_number}"
                ) from exc
    if not atoms:
        raise InputValidationError(f"Structure contains no C-alpha atoms: {path}")
    return atoms


def parse_mmcif_ca_atoms(path: Path) -> list[AtomCoordinate]:
    """Parse first-model C-alpha atoms from an mmCIF coordinate file."""
    try:
        payload: Mapping[str, Any] = MMCIF2Dict(str(path))
    except (OSError, ValueError, KeyError) as exc:
        raise InputValidationError(f"Could not parse mmCIF structure {path}: {exc}") from exc
    atom_names_raw = payload.get("_atom_site.label_atom_id")
    if atom_names_raw is None:
        raise InputValidationError(f"mmCIF has no _atom_site.label_atom_id column: {path}")
    atom_names = (
        [str(item) for item in atom_names_raw]
        if isinstance(atom_names_raw, list)
        else [str(atom_names_raw)]
    )
    count = len(atom_names)
    label_chains = _as_list(payload.get("_atom_site.label_asym_id"), count)
    label_sequences = _as_list(payload.get("_atom_site.label_seq_id"), count)
    auth_chains = _as_list(payload.get("_atom_site.auth_asym_id"), count)
    auth_sequences = _as_list(payload.get("_atom_site.auth_seq_id"), count)
    insertions = _as_list(payload.get("_atom_site.pdbx_PDB_ins_code"), count)
    alternatives = _as_list(payload.get("_atom_site.label_alt_id"), count)
    models = _as_list(payload.get("_atom_site.pdbx_PDB_model_num"), count, "1")
    x_values = _as_list(payload.get("_atom_site.Cartn_x"), count)
    y_values = _as_list(payload.get("_atom_site.Cartn_y"), count)
    z_values = _as_list(payload.get("_atom_site.Cartn_z"), count)
    atoms: list[AtomCoordinate] = []
    for index, atom_name in enumerate(atom_names):
        if atom_name.strip() != "CA":
            continue
        if _normalise_identifier(models[index]) not in {"", "1"}:
            continue
        if _normalise_identifier(alternatives[index]) not in {"", "A"}:
            continue
        try:
            atoms.append(
                AtomCoordinate(
                    label_chain=_normalise_identifier(label_chains[index]),
                    label_seq_id=_normalise_identifier(label_sequences[index]),
                    auth_chain=_normalise_identifier(auth_chains[index]),
                    auth_seq_id=_normalise_identifier(auth_sequences[index]),
                    insertion_code=_normalise_identifier(insertions[index]),
                    x=float(x_values[index]),
                    y=float(y_values[index]),
                    z=float(z_values[index]),
                )
            )
        except ValueError as exc:
            raise InputValidationError(
                f"Non-numeric mmCIF coordinate at atom-site row {index + 1}: {path}"
            ) from exc
    if not atoms:
        raise InputValidationError(f"Structure contains no first-model C-alpha atoms: {path}")
    return atoms


def parse_ca_atoms(path: Path) -> list[AtomCoordinate]:
    """Parse C-alpha coordinates from a supported structure file."""
    source = Path(path).expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix == ".pdb":
        return parse_pdb_ca_atoms(source)
    if suffix in {".cif", ".mmcif"}:
        return parse_mmcif_ca_atoms(source)
    raise InputValidationError(
        f"Unsupported structure format; expected .pdb, .cif or .mmcif: {source}"
    )


def _matches(atom: AtomCoordinate, locator: ResidueLocator) -> bool:
    """Return whether one atom matches a label or author residue locator."""
    if locator.label_seq_id:
        label_chain_matches = (
            not locator.label_chain or atom.label_chain == locator.label_chain
        )
        if label_chain_matches and atom.label_seq_id == locator.label_seq_id:
            return True
    if locator.auth_seq_id:
        auth_chain_matches = (
            not locator.auth_chain or atom.auth_chain == locator.auth_chain
        )
        insertion_matches = (
            not locator.insertion_code
            or atom.insertion_code == locator.insertion_code
        )
        if (
            auth_chain_matches
            and insertion_matches
            and atom.auth_seq_id == locator.auth_seq_id
        ):
            return True
    return False


def pocket_coordinates(
    atoms: Sequence[AtomCoordinate],
    locators: Sequence[ResidueLocator],
) -> list[tuple[float, float, float]]:
    """Return one deterministic C-alpha coordinate per mapped pocket residue."""
    coordinates: list[tuple[float, float, float]] = []
    for locator in locators:
        matches = [atom for atom in atoms if _matches(atom, locator)]
        if len(matches) > 1:
            unique_coordinates = {atom.coordinate for atom in matches}
            if len(unique_coordinates) > 1:
                raise InputValidationError(
                    "Pocket residue locator matches multiple C-alpha coordinates: "
                    f"{locator}"
                )
        if matches:
            coordinate = matches[0].coordinate
            if coordinate not in coordinates:
                coordinates.append(coordinate)
    return coordinates


def transform_coordinates(
    coordinates: Sequence[tuple[float, float, float]],
    transform: Transform,
) -> list[tuple[float, float, float]]:
    """Apply one structural-aligner transform to every mobile coordinate."""
    return [transform.apply(coordinate) for coordinate in coordinates]


def euclidean_distance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    """Return Euclidean distance in Angstroms."""
    return math.sqrt(sum((first[index] - second[index]) ** 2 for index in range(3)))


def centroid(
    coordinates: Sequence[tuple[float, float, float]],
) -> tuple[float, float, float]:
    """Return the arithmetic centroid of non-empty coordinates."""
    if not coordinates:
        raise InputValidationError("Cannot calculate a centroid for zero coordinates")
    return tuple(
        sum(coordinate[axis] for coordinate in coordinates) / len(coordinates)
        for axis in range(3)
    )


def pocket_geometry(
    *,
    reference_coordinates: Sequence[tuple[float, float, float]],
    transformed_mobile_coordinates: Sequence[tuple[float, float, float]],
    distance_threshold_angstrom: float,
) -> dict[str, float]:
    """Calculate symmetric nearest-neighbour pocket overlap after superposition."""
    if not reference_coordinates or not transformed_mobile_coordinates:
        raise InputValidationError(
            "Both pockets require at least one mapped C-alpha coordinate"
        )
    reference_nearest = [
        min(euclidean_distance(reference, mobile) for mobile in transformed_mobile_coordinates)
        for reference in reference_coordinates
    ]
    mobile_nearest = [
        min(euclidean_distance(mobile, reference) for reference in reference_coordinates)
        for mobile in transformed_mobile_coordinates
    ]
    reference_fraction = sum(
        distance <= distance_threshold_angstrom for distance in reference_nearest
    ) / len(reference_nearest)
    mobile_fraction = sum(
        distance <= distance_threshold_angstrom for distance in mobile_nearest
    ) / len(mobile_nearest)
    return {
        "centroid_distance_angstrom": euclidean_distance(
            centroid(reference_coordinates),
            centroid(transformed_mobile_coordinates),
        ),
        "reference_fraction_within_threshold": reference_fraction,
        "mobile_fraction_within_threshold": mobile_fraction,
        "symmetric_overlap_fraction": (reference_fraction + mobile_fraction) / 2.0,
        "mean_bidirectional_nearest_distance_angstrom": (
            sum(reference_nearest) + sum(mobile_nearest)
        )
        / (len(reference_nearest) + len(mobile_nearest)),
    }
