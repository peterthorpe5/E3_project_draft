"""Open RDKit fragment descriptors and pharmacophore compatibility ranking."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from e3chemistry.errors import DependencyError, InputValidationError
from e3chemistry.io_utils import read_tsv, require_columns
from e3chemistry.models import ChemistryConfig

FRAGMENT_PROPERTY_FIELDS = (
    "fragment_id",
    "smiles",
    "source",
    "canonical_smiles",
    "molecular_weight",
    "clogp",
    "hydrogen_bond_donor_count",
    "hydrogen_bond_acceptor_count",
    "rotatable_bond_count",
    "topological_polar_surface_area",
    "aromatic_ring_count",
    "positive_feature_count",
    "negative_feature_count",
    "heavy_atom_count",
    "rule_of_three_pass",
    "fragment_status",
    "status_reason",
)

FRAGMENT_RANKING_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "fragment_rank",
    "fragment_id",
    "canonical_smiles",
    "rule_of_three_pass",
    "pharmacophore_feature_coverage",
    "pharmacophore_feature_balance_similarity",
    "open_fragment_priority_score",
    "screening_status",
    "method",
    "interpretation",
)


def calculate_fragment_properties(record: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate rule-of-three and feature descriptors for one SMILES record."""
    fragment_id = str(record.get("fragment_id", "")).strip()
    smiles = str(record.get("smiles", "")).strip()
    source = str(record.get("source", "")).strip()
    if not fragment_id or not smiles:
        raise InputValidationError("Fragment records require fragment_id and smiles")
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise DependencyError("RDKit is required for open fragment screening") from exc
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return {
            "fragment_id": fragment_id,
            "smiles": smiles,
            "source": source,
            "canonical_smiles": "",
            "molecular_weight": "",
            "clogp": "",
            "hydrogen_bond_donor_count": "",
            "hydrogen_bond_acceptor_count": "",
            "rotatable_bond_count": "",
            "topological_polar_surface_area": "",
            "aromatic_ring_count": "",
            "positive_feature_count": "",
            "negative_feature_count": "",
            "heavy_atom_count": "",
            "rule_of_three_pass": False,
            "fragment_status": "INVALID_SMILES",
            "status_reason": "RDKit could not parse the supplied SMILES",
        }
    canonical = Chem.MolToSmiles(molecule, canonical=True)
    molecular_weight = float(Descriptors.MolWt(molecule))
    clogp = float(Crippen.MolLogP(molecule))
    donors = int(Lipinski.NumHDonors(molecule))
    acceptors = int(Lipinski.NumHAcceptors(molecule))
    rotatable = int(Lipinski.NumRotatableBonds(molecule))
    polar_surface = float(rdMolDescriptors.CalcTPSA(molecule))
    aromatic_rings = int(rdMolDescriptors.CalcNumAromaticRings(molecule))
    positive = len(molecule.GetSubstructMatches(Chem.MolFromSmarts("[+,+2,+3,+4]")))
    negative = len(molecule.GetSubstructMatches(Chem.MolFromSmarts("[-,-2,-3,-4]")))
    heavy_atoms = int(molecule.GetNumHeavyAtoms())
    rule_of_three = (
        molecular_weight <= 300.0
        and clogp <= 3.0
        and donors <= 3
        and acceptors <= 3
        and rotatable <= 3
        and polar_surface <= 60.0
    )
    return {
        "fragment_id": fragment_id,
        "smiles": smiles,
        "source": source,
        "canonical_smiles": canonical,
        "molecular_weight": round(molecular_weight, 6),
        "clogp": round(clogp, 6),
        "hydrogen_bond_donor_count": donors,
        "hydrogen_bond_acceptor_count": acceptors,
        "rotatable_bond_count": rotatable,
        "topological_polar_surface_area": round(polar_surface, 6),
        "aromatic_ring_count": aromatic_rings,
        "positive_feature_count": positive,
        "negative_feature_count": negative,
        "heavy_atom_count": heavy_atoms,
        "rule_of_three_pass": rule_of_three,
        "fragment_status": "READY" if rule_of_three else "OUTSIDE_RULE_OF_THREE",
        "status_reason": (
            "all configured rule-of-three thresholds passed"
            if rule_of_three
            else "one or more configured rule-of-three thresholds failed"
        ),
    }


def load_fragment_properties(path: Path) -> list[dict[str, Any]]:
    """Read, deduplicate and calculate properties for an open fragment library."""
    rows = read_tsv(path)
    require_columns(
        records=rows,
        required=("fragment_id", "smiles"),
        label="fragment library",
    )
    identifiers = [str(row["fragment_id"]).strip() for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise InputValidationError("Fragment library contains duplicate fragment_id values")
    return [calculate_fragment_properties(row) for row in rows]


def _target_signature(features: Sequence[Mapping[str, Any]]) -> Counter[str]:
    """Return capped feature demands for one target pharmacophore."""
    observed = Counter(str(feature["feature_type"]) for feature in features)
    return Counter({name: min(3, count) for name, count in observed.items()})


def _fragment_signature(fragment: Mapping[str, Any]) -> Counter[str]:
    """Return a compatible feature signature from RDKit fragment properties."""
    heavy_atoms = int(fragment["heavy_atom_count"])
    return Counter(
        {
            "hydrogen_bond_donor": int(fragment["hydrogen_bond_donor_count"]),
            "hydrogen_bond_acceptor": int(fragment["hydrogen_bond_acceptor_count"]),
            "aromatic": int(fragment["aromatic_ring_count"]),
            "positive_ionisable": int(fragment["positive_feature_count"]),
            "negative_ionisable": int(fragment["negative_feature_count"]),
            "hydrophobic": min(3, max(0, heavy_atoms // 4)),
        }
    )


def score_fragment(
    *, target_signature: Counter[str], fragment: Mapping[str, Any]
) -> tuple[float, float, float]:
    """Return coverage, balance and conservative open-screen priority score."""
    fragment_signature = _fragment_signature(fragment)
    target_total = sum(target_signature.values())
    overlap = sum(
        min(target_signature[name], fragment_signature[name])
        for name in set(target_signature).union(fragment_signature)
    )
    coverage = overlap / target_total if target_total else 0.0
    denominator = sum(
        max(target_signature[name], fragment_signature[name])
        for name in set(target_signature).union(fragment_signature)
    )
    balance = overlap / denominator if denominator else 0.0
    rule_score = 1.0 if bool(fragment["rule_of_three_pass"]) else 0.0
    priority = 0.5 * coverage + 0.3 * balance + 0.2 * rule_score
    return coverage, balance, priority


def rank_fragments(
    *,
    group_summaries: Sequence[Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
    fragments: Sequence[Mapping[str, Any]],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Rank valid fragments against chemistry-ready group pharmacophores."""
    features_by_group: dict[str, list[Mapping[str, Any]]] = {}
    for feature in features:
        features_by_group.setdefault(
            str(feature["evolutionary_group_key"]), []
        ).append(feature)
    valid_fragments = [
        fragment for fragment in fragments if fragment["fragment_status"] == "READY"
    ]
    output = []
    for group in group_summaries:
        if group["chemistry_handoff_status"] != "READY_FOR_OPEN_FRAGMENT_PRIORITISATION":
            continue
        key = str(group["evolutionary_group_key"])
        signature = _target_signature(features_by_group.get(key, []))
        scored = []
        for fragment in valid_fragments:
            coverage, balance, priority = score_fragment(
                target_signature=signature,
                fragment=fragment,
            )
            scored.append((priority, coverage, balance, fragment))
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                str(item[3]["fragment_id"]),
            )
        )
        for fragment_rank, (priority, coverage, balance, fragment) in enumerate(
            scored[: config.maximum_fragments_per_group],
            start=1,
        ):
            output.append(
                {
                    "evolutionary_group_rank": group["evolutionary_group_rank"],
                    "evolutionary_group_key": key,
                    "fragment_rank": fragment_rank,
                    "fragment_id": fragment["fragment_id"],
                    "canonical_smiles": fragment["canonical_smiles"],
                    "rule_of_three_pass": fragment["rule_of_three_pass"],
                    "pharmacophore_feature_coverage": round(coverage, 6),
                    "pharmacophore_feature_balance_similarity": round(balance, 6),
                    "open_fragment_priority_score": round(priority, 6),
                    "screening_status": "PRIORITISED_FOR_REVIEW",
                    "method": config.method_name,
                    "interpretation": (
                        "two-dimensional feature compatibility only; not docking, "
                        "binding affinity or experimental fragment screening"
                    ),
                }
            )
    return output
