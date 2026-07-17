"""mmCIF parsing and model-level pLDDT calculations."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import gemmi

from .models import ResidueRecord


_ATOM_SITE_TAGS = [
    "_atom_site.group_PDB",
    "_atom_site.label_atom_id",
    "_atom_site.label_comp_id",
    "_atom_site.label_asym_id",
    "_atom_site.label_seq_id",
    "_atom_site.auth_asym_id",
    "_atom_site.auth_seq_id",
    "_atom_site.pdbx_PDB_ins_code",
    "_atom_site.B_iso_or_equiv",
]


def _optional_int(value: str) -> int | None:
    """Parse an mmCIF integer, treating missing markers as ``None``.

    Args:
        value: Raw mmCIF value.

    Returns:
        Parsed integer or ``None``.
    """

    stripped = value.strip()
    if stripped in {"", ".", "?"}:
        return None
    return int(float(stripped))


def _normalise_missing(value: str) -> str:
    """Convert mmCIF missing markers to an empty string.

    Args:
        value: Raw mmCIF value.

    Returns:
        Empty string for missing values, otherwise stripped text.
    """

    stripped = value.strip()
    return "" if stripped in {".", "?"} else stripped


def read_atom_site_rows(path: Path) -> list[dict[str, Any]]:
    """Read polymer atom rows required for pLDDT and residue mapping.

    Args:
        path: Input mmCIF file.

    Returns:
        Atom records in file order.

    Raises:
        FileNotFoundError: If the file is absent.
        ValueError: If required ``_atom_site`` columns are unavailable.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"mmCIF file does not exist: {source}")

    document = gemmi.cif.read_file(str(source))
    block = document.sole_block()
    table = block.find(_ATOM_SITE_TAGS)
    if len(table) == 0:
        raise ValueError(f"No required _atom_site rows found in {source}")

    records: list[dict[str, Any]] = []
    for row in table:
        group = str(row[0]).strip()
        if group not in {"ATOM", "HETATM"}:
            continue
        try:
            b_factor = float(str(row[8]))
        except ValueError as error:
            raise ValueError(
                f"Invalid B_iso_or_equiv value in {source}: {row[8]!r}"
            ) from error
        if not math.isfinite(b_factor):
            raise ValueError(f"Non-finite B_iso_or_equiv value in {source}")
        records.append(
            {
                "group_pdb": group,
                "atom_name": str(row[1]).strip(),
                "residue_name": str(row[2]).strip(),
                "label_chain": _normalise_missing(str(row[3])),
                "label_seq_id": _optional_int(str(row[4])),
                "auth_chain": _normalise_missing(str(row[5])),
                "auth_seq_id": _optional_int(str(row[6])),
                "insertion_code": _normalise_missing(str(row[7])),
                "plddt": b_factor,
            }
        )
    if not records:
        raise ValueError(f"No ATOM/HETATM records found in {source}")
    return records


def collapse_atoms_to_residues(
    atom_rows: list[dict[str, Any]],
) -> list[ResidueRecord]:
    """Collapse atom rows to one deterministic pLDDT value per residue.

    Carbon-alpha pLDDT is used when present. Otherwise the median pLDDT over
    all residue atoms is used. The range of atom-level values is retained so
    unexpected within-residue variation is auditable.

    Args:
        atom_rows: Atom records from :func:`read_atom_site_rows`.

    Returns:
        Residue records in stable structural order.

    Raises:
        ValueError: If no polymer residues can be constructed.
    """

    groups: dict[
        tuple[str, int | None, str, int | None, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for row in atom_rows:
        if row["group_pdb"] != "ATOM":
            continue
        key = (
            str(row["label_chain"]),
            row["label_seq_id"],
            str(row["auth_chain"]),
            row["auth_seq_id"],
            str(row["insertion_code"]),
            str(row["residue_name"]),
        )
        groups[key].append(row)

    residues: list[ResidueRecord] = []
    for key, atoms in groups.items():
        values = [float(atom["plddt"]) for atom in atoms]
        ca_values = [
            float(atom["plddt"])
            for atom in atoms
            if str(atom["atom_name"]).upper() == "CA"
        ]
        selected = statistics.median(ca_values if ca_values else values)
        residues.append(
            ResidueRecord(
                label_chain=key[0],
                label_seq_id=key[1],
                auth_chain=key[2],
                auth_seq_id=key[3],
                insertion_code=key[4],
                residue_name=key[5],
                plddt=float(selected),
                source_atom_count=len(atoms),
                source_atom_plddt_range=max(values) - min(values),
            )
        )

    if not residues:
        raise ValueError("No polymer ATOM residues were available.")

    return sorted(
        residues,
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


def parse_model_residues(path: Path) -> list[ResidueRecord]:
    """Parse one model mmCIF into residue-level pLDDT records.

    Args:
        path: AlphaFold model mmCIF.

    Returns:
        Residue-level model records.
    """

    return collapse_atoms_to_residues(read_atom_site_rows(path))


def compute_model_quality(
    accession: str,
    residues: list[ResidueRecord],
    confident_threshold: float = 70.0,
    very_high_threshold: float = 90.0,
) -> dict[str, Any]:
    """Calculate model-level pLDDT summaries from residue records.

    Args:
        accession: Protein accession.
        residues: Residue-level pLDDT records.
        confident_threshold: Lower pLDDT threshold for confident residues.
        very_high_threshold: Lower threshold for very-high-confidence residues.

    Returns:
        Flat quality summary.

    Raises:
        ValueError: If residues are empty or thresholds are invalid.
    """

    if not residues:
        raise ValueError("At least one residue is required.")
    if not 0 <= confident_threshold < very_high_threshold <= 100:
        raise ValueError(
            "pLDDT thresholds must satisfy "
            "0 <= confident < very_high <= 100."
        )

    values = [residue.plddt for residue in residues]
    residue_count = len(values)
    count_ge_confident = sum(value >= confident_threshold for value in values)
    count_ge_very_high = sum(value >= very_high_threshold for value in values)
    count_lt_50 = sum(value < 50.0 for value in values)
    count_50_to_70 = sum(50.0 <= value < confident_threshold for value in values)
    count_70_to_90 = sum(
        confident_threshold <= value < very_high_threshold for value in values
    )
    max_atom_range = max(
        residue.source_atom_plddt_range for residue in residues
    )

    return {
        "accession": accession,
        "residue_count": residue_count,
        "mean_plddt": statistics.fmean(values),
        "median_plddt": statistics.median(values),
        "minimum_plddt": min(values),
        "maximum_plddt": max(values),
        "count_plddt_lt_50": count_lt_50,
        "count_plddt_50_to_lt_70": count_50_to_70,
        "count_plddt_70_to_lt_90": count_70_to_90,
        "count_plddt_ge_70": count_ge_confident,
        "count_plddt_ge_90": count_ge_very_high,
        "fraction_residues_ge_70": count_ge_confident / residue_count,
        "fraction_residues_ge_90": count_ge_very_high / residue_count,
        "maximum_within_residue_atom_plddt_range": max_atom_range,
    }


def compare_api_quality(
    computed: dict[str, Any],
    metadata: dict[str, Any],
    mean_tolerance: float,
    fraction_tolerance: float,
) -> dict[str, Any]:
    """Compare model-derived quality values with AlphaFold API metadata.

    Args:
        computed: Model-derived quality summary.
        metadata: Normalised API metadata.
        mean_tolerance: Allowed absolute mean pLDDT difference.
        fraction_tolerance: Allowed absolute fraction >=70 difference.

    Returns:
        Comparison fields suitable for inclusion in model-quality output.
    """

    api_mean = metadata.get("global_metric_value")
    api_fraction = metadata.get("api_fraction_residues_ge_70")
    mean_difference: float | None = None
    fraction_difference: float | None = None
    mean_matches: bool | None = None
    fraction_matches: bool | None = None

    if api_mean is not None:
        mean_difference = float(computed["mean_plddt"]) - float(api_mean)
        mean_matches = abs(mean_difference) <= mean_tolerance
    if api_fraction is not None:
        fraction_difference = (
            float(computed["fraction_residues_ge_70"])
            - float(api_fraction)
        )
        fraction_matches = abs(fraction_difference) <= fraction_tolerance

    return {
        "api_global_metric_value": api_mean,
        "api_fraction_residues_ge_70": api_fraction,
        "mean_plddt_minus_api": mean_difference,
        "fraction_ge_70_minus_api": fraction_difference,
        "mean_plddt_matches_api": mean_matches,
        "fraction_ge_70_matches_api": fraction_matches,
    }
