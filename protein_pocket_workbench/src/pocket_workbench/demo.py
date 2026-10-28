"""Explicitly synthetic structures for installation and viewer verification."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from .comparison import compare_batch
from .core import ComparisonSettings
from .importing import import_project
from .sequences import analyse_sequences, fasta_text


def create_demo(*, output: Path) -> Path:
    """Create three synthetic models with known coordinate relationships.

    Args:
        output: New demo resource directory.

    Returns:
        Complete demonstration resource with fits, MSA and an exploratory tree.
    """
    sequences = {
        "synthetic_reference": "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMN",
        "synthetic_mobile": "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMA",
        "synthetic_variant": "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLAA",
    }
    names = {
        "A": "ALA",
        "C": "CYS",
        "D": "ASP",
        "E": "GLU",
        "F": "PHE",
        "G": "GLY",
        "H": "HIS",
        "I": "ILE",
        "K": "LYS",
        "L": "LEU",
        "M": "MET",
        "N": "ASN",
        "P": "PRO",
        "Q": "GLN",
        "R": "ARG",
        "S": "SER",
        "T": "THR",
        "V": "VAL",
        "W": "TRP",
        "Y": "TYR",
    }
    angle = 0.8
    rotation = np.asarray(
        [
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle), np.cos(angle), 0],
            [0, 0, 1],
        ]
    )
    with tempfile.TemporaryDirectory(prefix="synthetic-pocket-demo-") as temporary:
        source = Path(temporary)
        samples, pockets = [], []
        for model_index, (identifier, sequence) in enumerate(sequences.items()):
            lines = []
            for index, amino_acid in enumerate(sequence, start=1):
                point = np.asarray(
                    [index * 1.8, np.sin(index * 0.6) * 5, np.cos(index * 0.6) * 5]
                )
                if model_index:
                    point = point @ rotation.T + np.asarray([25, -12, 6])
                for atom_index, (atom_name, offset) in enumerate(
                    (
                        ("N", [-0.7, 0, 0]),
                        ("CA", [0, 0, 0]),
                        ("C", [0.7, 0, 0]),
                        ("O", [1, 0.5, 0]),
                    )
                ):
                    x, y, z = point + offset
                    element = atom_name[0]
                    serial = (index - 1) * 4 + atom_index + 1
                    lines.append(
                        "ATOM "
                        f" {serial:5d} {atom_name:^4s} {names[amino_acid]} A{index:4d} "
                        f"   {x:8.3f}{y:8.3f}{z:8.3f}{1:6.2f}{90:6.2f}         "
                        f" {element:>2s}  "
                    )
            (source / f"{identifier}.pdb").write_text("\n".join(lines) + "\nTER\nEND\n")
            samples.append(
                {
                    "sample_id": identifier,
                    "cluster": "synthetic",
                    "status": "complete",
                    "warnings": (
                        "Synthetic demonstration; pocket scores are illustrative"
                        " fixtures"
                    ),
                }
            )
            for pocket_id, positions in ((1, range(2, 10)), (2, range(21, 29))):
                pockets.append(
                    {
                        "sample_id": identifier,
                        "method": "fpocket",
                        "pocket_id": pocket_id,
                        "review_rank": pocket_id,
                        "ranking_basis": "synthetic fixture",
                        "druggability_score": 0.6,
                        "volume_a3": 500.0,
                        "mean_plddt": 90.0,
                        "confidence_status": "meets_local_confidence_rule",
                        "residues": [f"A_{i}" for i in positions],
                    }
                )
        (source / "report.html").write_text(
            '<script id="data" type="application/json">'
            + json.dumps(
                {
                    "samples": samples,
                    "pockets": pockets,
                    "ranked": pockets,
                    "methods": [],
                    "manifest": {"synthetic": True},
                }
            )
            + "</script>"
        )
        fasta = source / "representatives.fasta"
        fasta.write_text(fasta_text(records=sequences))
        import_project(
            sources=[source],
            output=output,
            title="Synthetic demonstration · known transforms",
            fasta=fasta,
        )
    compare_batch(
        root=output,
        pairs=[("synthetic_reference", "synthetic_mobile")],
        settings=ComparisonSettings(engine="sequence_kabsch", top_pockets=2),
    )
    analyse_sequences(root=output, threads=1)
    return output
