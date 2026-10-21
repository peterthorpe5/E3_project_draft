"""Small artificial structures and deterministic external-output contracts.

These fixtures exercise software behaviour. They are not biological predictions.
Real-tool compatibility is checked separately with the external marker.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import gemmi
import pytest


def make_model(
    *,
    path: Path,
    chains: tuple[str, ...] = ("Q",),
    names: tuple[str, ...] = ("ALA", "CYS", "ASP"),
    confidence: tuple[float, ...] = (90, 60, 80),
    insertions: bool = False,
    ca_only: bool = False,
    water: bool = False,
    model_count: int = 1,
) -> Path:
    """Write an artificial PDB/mmCIF for mapping and input-validation tests.

    Args:
        path: Destination.
        chains: Author chain names.
        names: Three-letter protein residues.
        confidence: Residue confidence values, cycled when required.
        insertions: Add an insertion code to the second residue.
        ca_only: Write only alpha carbons.
        water: Add a water to exercise non-protein exclusion.
        model_count: Number of coordinate models.

    Returns:
        Written model path.
    """
    structure = gemmi.Structure()
    for model_index in range(model_count):
        model = gemmi.Model(str(model_index + 1))
        for chain_name in chains:
            chain = gemmi.Chain(chain_name)
            for index, name in enumerate(names):
                residue = gemmi.Residue()
                residue.name = name
                residue.het_flag = "A"
                residue.seqid = gemmi.SeqId(
                    index + 10, "A" if insertions and index == 1 else " "
                )
                for atom_index, atom_name in enumerate(
                    ("CA",) if ca_only else ("N", "CA", "C", "O")
                ):
                    atom = gemmi.Atom()
                    atom.name = atom_name
                    atom.element = gemmi.Element(atom_name[0])
                    atom.pos = gemmi.Position(
                        index * 4 + atom_index, atom_index % 2, index
                    )
                    atom.b_iso = confidence[index % len(confidence)]
                    atom.occ = 1.0
                    residue.add_atom(atom)
                chain.add_residue(residue)
            if water:
                residue = gemmi.Residue()
                residue.name = "HOH"
                residue.het_flag = "H"
                residue.seqid = gemmi.SeqId(200, " ")
                atom = gemmi.Atom()
                atom.name = "O"
                atom.element = gemmi.Element("O")
                residue.add_atom(atom)
                chain.add_residue(residue)
            model.add_chain(chain)
        structure.add_model(model)
    if path.suffix == ".pdb":
        structure.write_pdb(str(path))
    else:
        structure.make_mmcif_document().write_file(str(path))
    return path


@pytest.fixture
def model_path(*, tmp_path: Path) -> Path:
    """Provide a three-residue model with original author numbering."""
    return make_model(path=tmp_path / "representative.pdb")


@pytest.fixture
def tool_identity() -> dict:
    """Provide explicit fake tool identities for orchestration tests."""
    return {
        "fpocket": {"executable": "fixture-fpocket", "sha256": "fixture-fpocket"},
        "p2rank": {"executable": "fixture-prank", "sha256": "fixture-prank"},
    }


def emulate_command(
    *, command: list[str], cwd: Path, log_prefix: Path, timeout: float
) -> dict:
    """Emulate version-pinned native output contracts for unit tests.

    Args:
        command: External argument vector.
        cwd: Tool working directory.
        log_prefix: Persistent logs prefix.
        timeout: Accepted to match the command interface.

    Returns:
        Minimal command record.
    """
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    log_prefix.with_suffix(".stdout.log").write_text(
        data="Unit test fixture\n", encoding="utf-8"
    )
    log_prefix.with_suffix(".stderr.log").write_text(data="", encoding="utf-8")
    if command[0] == "fixture-fpocket":
        output = cwd / "model_out"
        (output / "pockets").mkdir(parents=True)
        (output / "model_info.txt").write_text(
            data="Pocket 1 :\n Score : 0.7\n Druggability Score : 0.8\n Volume : 200\n"
            " Total SASA : 123.4\nPocket 2 :\n Score : 0.3\n"
            " Druggability Score : 0.2\n Volume : 100\n",
            encoding="utf-8",
        )
        shutil.copy2(src=cwd / "model.pdb", dst=output / "model_out.pdb")
        lines = (cwd / "model.pdb").read_text(encoding="utf-8").splitlines()
        for pocket_id in (1, 2):
            (output / "pockets" / f"pocket{pocket_id}_atm.pdb").write_text(
                data="\n".join(line for line in lines if line.startswith("ATOM"))
                + "\n",
                encoding="utf-8",
            )
    else:
        output = cwd / "output"
        output.mkdir()
        names = ("pocket.2", "pocket.1") if command[1] == "rescore" else ("pocket1",)
        content = "name, rank, score, probability, center_x, center_y, center_z, "
        content += "residue_ids\n"
        for rank, name in enumerate(names, start=1):
            content += f"{name}, {rank}, {10 / rank}, {0.8 / rank}, 1, 2, 3, A_1 A_3\n"
        (output / "model.pdb_predictions.csv").write_text(
            data=content, encoding="utf-8"
        )
    return {"argv": command, "return_code": 0}


@pytest.fixture
def emulated_tools(*, monkeypatch: pytest.MonkeyPatch, tool_identity: dict) -> dict:
    """Patch only command execution; use the real parsers and exporters."""
    monkeypatch.setattr("protein_pockets.pipeline.run_command", emulate_command)
    return tool_identity
