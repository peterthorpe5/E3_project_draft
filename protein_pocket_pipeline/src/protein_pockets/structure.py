"""PDB/mmCIF preparation with an explicit original-to-tool residue map."""

from __future__ import annotations

import math
import string
from pathlib import Path

import gemmi

from .models import Sample, Settings


def prepare_structure(
    *, sample: Sample, settings: Settings, destination: Path
) -> tuple[list[dict], dict]:
    """Prepare protein heavy atoms and map every residue to the original model.

    Models are never aligned or confidence-trimmed. Normalising author chains
    and residue numbering avoids ambiguities in external-tool parsers. Original
    structures are retained separately by the pipeline. AF3 atom confidence is
    averaged within each residue before any residue-level summaries.

    Args:
        sample: Input model, optional FASTA and author chain selection.
        settings: Confidence interpretation and exact-fragment policy.
        destination: Normalised PDB destination.

    Returns:
        Residue map and structure-level quality/sequence metadata.

    Raises:
        ValueError: For multiple models, ambiguous chains, sequence mismatch,
            non-finite coordinates or invalid pLDDT.
    """
    structure = gemmi.read_structure(str(sample.model_path))
    if len(structure) != 1:
        raise ValueError("Exactly one coordinate MODEL is required per input file")
    protein_chains = []
    excluded = 0
    for chain in structure[0]:
        protein_residues = []
        for residue in chain:
            info = gemmi.find_tabulated_residue(residue.name)
            if info.is_amino_acid() and residue.find_atom("CA", "*"):
                protein_residues.append(residue)
            else:
                excluded += 1
        if protein_residues:
            protein_chains.append((chain.name, protein_residues))
    if not protein_chains:
        raise ValueError("No protein residues with alpha carbons found")
    names = [name for name, _ in protein_chains]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate author chain identifiers in input model")
    if sample.chain == "all":
        if sample.sequence and len(protein_chains) > 1:
            raise ValueError("FASTA mapping requires one target chain, not chain=all")
        selected = protein_chains
    elif sample.chain:
        selected = [item for item in protein_chains if item[0] == sample.chain]
        if not selected:
            raise ValueError(f"Author chain {sample.chain!r} not found; found {names}")
    elif len(protein_chains) == 1:
        selected = protein_chains
    else:
        raise ValueError(
            f"Multiple protein chains {names}; select --chain or manifest chain, "
            "or explicitly use chain=all for complex-level pocket analysis"
        )
    if len(selected) > 62:
        raise ValueError("PDB normalisation supports at most 62 protein chains")
    prepared = gemmi.Structure()
    prepared.name = sample.sample_id
    model = gemmi.Model("1")
    rows = []
    incomplete = 0
    chain_alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    for index, (original_chain, residues) in enumerate(selected):
        if len(residues) > 9999:
            raise ValueError("PDB normalisation supports at most 9999 residues/chain")
        tool_chain = chain_alphabet[index]
        normalised_chain = gemmi.Chain(tool_chain)
        seen = set()
        for position, residue in enumerate(residues, start=1):
            original_key = (residue.seqid.num, residue.seqid.icode.strip())
            if original_key in seen:
                raise ValueError("Duplicate author residue identifier in one chain")
            seen.add(original_key)
            new_residue = gemmi.Residue()
            new_residue.name = "MET" if residue.name == "MSE" else residue.name
            new_residue.seqid = gemmi.SeqId(position, " ")
            new_residue.het_flag = "A"
            atoms = {}
            for atom in residue:
                if atom.element.is_hydrogen:
                    continue
                if not all(math.isfinite(value) for value in atom.pos):
                    raise ValueError("Non-finite atom coordinates")
                if any(abs(value) >= 9999 for value in atom.pos):
                    raise ValueError("Atom coordinates exceed PDB field capacity")
                old = atoms.get(atom.name)
                priority = (atom.occ, atom.altloc in {"\x00", " ", "A"})
                if old is None or priority > (
                    old.occ,
                    old.altloc in {"\x00", " ", "A"},
                ):
                    atoms[atom.name] = atom
            if not {"N", "CA", "C"} <= atoms.keys():
                incomplete += 1
            values = [float(atom.b_iso) for atom in atoms.values()]
            if settings.confidence == "plddt" and any(
                not math.isfinite(value) or not 0 <= value <= 100 for value in values
            ):
                raise ValueError("pLDDT fields must contain finite values in [0, 100]")
            for atom in atoms.values():
                copied = atom.clone()
                copied.altloc = "\x00"
                if residue.name == "MSE" and atom.name == "SE":
                    copied.name = "SD"
                    copied.element = gemmi.Element("S")
                new_residue.add_atom(copied)
            normalised_chain.add_residue(new_residue)
            one_letter = gemmi.find_tabulated_residue(residue.name).one_letter_code
            rows.append(
                {
                    "sample_id": sample.sample_id,
                    "residue_key": f"{tool_chain}_{position}",
                    "tool_chain": tool_chain,
                    "tool_residue_number": position,
                    "author_chain": original_chain,
                    "author_residue_number": residue.seqid.num,
                    "insertion_code": residue.seqid.icode.strip(),
                    "residue_name": residue.name,
                    "amino_acid": one_letter.upper(),
                    "fasta_position": None,
                    "plddt": (
                        sum(values) / len(values)
                        if settings.confidence == "plddt"
                        else None
                    ),
                }
            )
        model.add_chain(normalised_chain)
    if incomplete == len(rows):
        raise ValueError(
            "No complete N/CA/C backbone residues; CA-only models unsupported"
        )
    prepared.add_model(model)
    atom_count = sum(len(residue) for chain in prepared[0] for residue in chain)
    if atom_count > 99999:
        raise ValueError("Prepared model exceeds 99999 PDB atom records")
    sequence = "".join(row["amino_acid"] for row in rows)
    sequence_status = "not_supplied"
    if sample.sequence:
        if sequence == sample.sequence:
            offset = 0
            sequence_status = "exact"
        elif (
            settings.allow_fragments
            and sequence in sample.sequence
            and sample.sequence.find(sequence) == sample.sequence.rfind(sequence)
        ):
            offset = sample.sequence.find(sequence)
            sequence_status = "unique_exact_fragment"
        else:
            raise ValueError(
                "Structure sequence does not exactly match FASTA. For a unique exact "
                "fragment use --allow-fragments; inspect mismatches "
                "rather than guessing"
            )
        for position, row in enumerate(rows, start=offset + 1):
            row["fasta_position"] = position
    destination.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_pdb(str(destination))
    plddts = [row["plddt"] for row in rows if row["plddt"] is not None]
    warnings = []
    if excluded:
        warnings.append(
            f"Excluded {excluded} non-protein/water/CA-missing residues; "
            "metal/cofactor effects are not assessed"
        )
    if len(protein_chains) > len(selected):
        warnings.append("Other protein chains excluded by explicit chain selection")
    if len(selected) > 1:
        warnings.append("Complex-level analysis includes inter-chain pockets")
    if incomplete:
        warnings.append(f"{incomplete} residues lack N/CA/C backbone atoms")
    if plddts and len(set(round(value, 4) for value in plddts)) == 1:
        warnings.append(
            "Constant pLDDT values: confirm B fields encode model confidence"
        )
    if not sample.sequence:
        warnings.append("No FASTA supplied: sequence identity and coverage not checked")
    return rows, {
        "residue_count": len(rows),
        "chain_count": len(selected),
        "sequence_status": sequence_status,
        "fasta_length": len(sample.sequence) if sample.sequence else None,
        "fasta_coverage": len(rows) / len(sample.sequence) if sample.sequence else None,
        "mean_plddt": sum(plddts) / len(plddts) if plddts else None,
        "fraction_ge_threshold": (
            sum(value >= settings.high_confidence for value in plddts) / len(rows)
            if plddts
            else None
        ),
        "warnings": "; ".join(warnings),
    }
