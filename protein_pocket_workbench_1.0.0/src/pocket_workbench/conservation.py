"""Mutual-nearest pocket residue correspondences using E3 chemical groups."""

from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist

CHEMICAL_GROUPS = {
    **dict.fromkeys("AVLIMFWY", "hydrophobic"),
    **dict.fromkeys("STNQ", "polar"),
    **dict.fromkeys("KRH", "positive"),
    **dict.fromkeys("DE", "negative"),
    **dict.fromkeys("CGP", "special"),
}


def residue_evidence(
    *,
    reference: list[dict],
    mobile: list[dict],
    mobile_xyz: np.ndarray,
    radius: float,
) -> dict:
    """Measure identity and chemical groups among unique structural matches.

    Args:
        reference: Reference pocket residues with original numbering and FASTA map.
        mobile: Equivalent mobile residues in the same order as mobile_xyz.
        mobile_xyz: Transformed mobile pocket C-alpha coordinates.
        radius: Maximum allowed mutual-nearest distance in Angstroms.

    Returns:
        Auditable residue correspondences and fractions; unknown is never zero.
    """
    distances = cdist(np.asarray([r["xyz"] for r in reference]), mobile_xyz)
    forward, reverse = distances.argmin(axis=1), distances.argmin(axis=0)
    rows, identities, chemicals = [], [], []
    for i, j in enumerate(forward):
        if reverse[j] != i or distances[i, j] > radius:
            continue
        a, b = reference[i], mobile[j]
        aa, bb = a.get("amino_acid"), b.get("amino_acid")
        comparable = bool(
            a.get("sequence_position")
            and b.get("sequence_position")
            and aa in CHEMICAL_GROUPS
            and bb in CHEMICAL_GROUPS
        )
        identity = aa == bb if comparable else None
        chemical = CHEMICAL_GROUPS[aa] == CHEMICAL_GROUPS[bb] if comparable else None
        if comparable:
            identities.append(identity)
            chemicals.append(chemical)
        rows.append(
            {
                "reference_residue": a["residue_key"],
                "mobile_residue": b["residue_key"],
                "reference_author_chain": a.get("author_chain"),
                "reference_author_number": a.get("author_residue_number"),
                "reference_insertion_code": a.get("insertion_code", ""),
                "mobile_author_chain": b.get("author_chain"),
                "mobile_author_number": b.get("author_residue_number"),
                "mobile_insertion_code": b.get("insertion_code", ""),
                "reference_fasta_position": a.get("sequence_position"),
                "mobile_fasta_position": b.get("sequence_position"),
                "reference_amino_acid": aa,
                "mobile_amino_acid": bb,
                "ca_distance": float(distances[i, j]),
                "residue_identity": identity,
                "chemical_group_match": chemical,
                "sequence_comparison_status": (
                    "exact_sequence_coordinates" if comparable else "not_comparable"
                ),
            }
        )
    return {
        "residue_correspondences": rows,
        "comparable_residue_pairs": len(identities),
        "residue_identity_fraction": (
            sum(identities) / len(identities) if identities else None
        ),
        "chemical_group_conservation": (
            sum(chemicals) / len(chemicals) if chemicals else None
        ),
    }
