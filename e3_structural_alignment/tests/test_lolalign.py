"""LoL-align score semantics, rigid transforms, failures and real-tool integration."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from e3structalign import lolalign
from e3structalign.errors import ToolExecutionError
from e3structalign.io_utils import read_records, sha256_file
from e3structalign.pipeline import AlignmentSettings, run_pipeline
from e3structalign.structure_io import parse_ca_atoms

VALID_ROW = (
    "ref\tmobile\t4\t5\tAC-D\tACED\t0.8\t0.7\t0.25\t0.9\t0.99\t"
    "0,1,0,-1,0,0,0,0,1\t7,12,-4\n"
)


def test_parse_local_alignment_and_transform_direction() -> None:
    """Keep local scores separate and map the mobile target onto the reference query."""
    result = lolalign.parse_lolalign_output(text=VALID_ROW, version="revision")
    assert result.aligned_length == 3
    assert result.sequence_identity == 1.0
    assert result.tm_score_reference_normalised == 0.8
    assert result.tm_score_mobile_normalised == 0.7
    assert result.lol_normalised_score == 0.9
    assert result.lol_homology_probability == 0.99
    assert result.alignment_scope == "local"
    assert result.transform.apply(coordinate=(10.0, 2.0, 7.0)) == (9.0, 2.0, 3.0)


@pytest.mark.parametrize("text", ["", VALID_ROW * 2, "only\ttwo\n"])
def test_parse_rejects_missing_ambiguous_or_wrong_schema(*, text: str) -> None:
    """Never treat absent or multi-chain hits as one valid monomer comparison."""
    with pytest.raises(ToolExecutionError):
        lolalign.parse_lolalign_output(text=text, version="revision")


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (2, "0"), (2, "bad"), (4, ""), (5, "A"), (5, "A--D"),
        (6, "1.1"), (7, "nan"), (8, "-1"), (9, "2"), (10, "-0.1"),
        (11, "1,0,0,0,1,0,0,0,-1"), (11, "1,0,0,0,1,0,0,0,2"),
        (11, "1,0"), (12, "bad,0,0"), (12, "inf,0,0"),
    ],
)
def test_parse_rejects_invalid_values(*, index: int, value: str) -> None:
    """Reject non-finite scores, inconsistent sequences and improper transforms."""
    cells = VALID_ROW.rstrip("\n").split("\t")
    cells[index] = value
    with pytest.raises(ToolExecutionError):
        lolalign.parse_lolalign_output(text="\t".join(cells), version="revision")


def test_version_requires_capability(*, monkeypatch) -> None:
    """An old Foldseek binary must fail preflight rather than run another alignment mode."""
    calls = []

    def completed(*, args, **kwargs):
        """Return a version and current capability help."""
        calls.append(args)
        text = "revision\n" if args[-1] == "version" else "--lolalign-multidomain"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=text, stderr="")

    monkeypatch.setattr(lolalign.subprocess, "run", completed)
    assert lolalign.foldseek_version(executable="foldseek") == "revision"
    assert calls == [["foldseek", "version"], ["foldseek", "easy-search", "-h"]]
    monkeypatch.setattr(
        lolalign.subprocess, "run",
        lambda **kwargs: subprocess.CompletedProcess(
            args=kwargs["args"], returncode=0, stdout="old", stderr=""
        ),
    )
    with pytest.raises(ToolExecutionError, match="lacks LoL-align"):
        lolalign.foldseek_version(executable="old_foldseek")


def test_version_execution_failure(*, monkeypatch) -> None:
    """Explain an unavailable executable."""
    def failed(**kwargs):
        """Simulate an executable missing from PATH."""
        raise OSError("not installed")

    monkeypatch.setattr(lolalign.subprocess, "run", failed)
    with pytest.raises(ToolExecutionError, match="Could not inspect"):
        lolalign.foldseek_version(executable="missing")


def test_run_retains_raw_output_and_uses_exhaustive_local_mode(*, tmp_path, monkeypatch) -> None:
    """One pair is aligned without a search prefilter and retains score provenance."""
    reference, mobile = tmp_path / "reference.pdb", tmp_path / "mobile.pdb"
    reference.write_text(data="model", encoding="utf-8")
    mobile.write_text(data="model", encoding="utf-8")
    calls = []

    def completed(*, args, **kwargs):
        """Produce a documented pairwise TSV result."""
        calls.append(args)
        Path(args[4]).write_text(data=VALID_ROW, encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ran", stderr="")

    monkeypatch.setattr(lolalign.subprocess, "run", completed)
    matrix = tmp_path / "pair.matrix.txt"
    stdout = tmp_path / "pair.stdout.txt"
    result = lolalign.run_lolalign(
        executable="foldseek", reference_path=reference, mobile_path=mobile,
        matrix_path=matrix, stdout_path=stdout, version="revision", multidomain=False,
    )
    assert calls[0][2:4] == [str(reference), str(mobile)]
    assert calls[0][calls[0].index("--alignment-type") + 1] == "3"
    assert calls[0][calls[0].index("--exhaustive-search") + 1] == "1"
    assert calls[0][calls[0].index("--threads") + 1] == "1"
    assert calls[0][calls[0].index("--lolalign-multidomain") + 1] == "0"
    assert matrix.is_file() and stdout.with_suffix(".alignment.tsv").is_file()
    assert result.lol_homology_probability == 0.99


@pytest.mark.parametrize("mode", ["exit", "timeout", "missing_output"])
def test_run_failure_never_publishes_matrix(*, tmp_path, monkeypatch, mode: str) -> None:
    """Failed commands cannot leave a stale transform available to downstream scoring."""
    model = tmp_path / "model.pdb"
    model.write_text(data="model", encoding="utf-8")
    matrix, stdout = tmp_path / "matrix.txt", tmp_path / "stdout.txt"
    matrix.write_text(data="stale", encoding="utf-8")

    def failed(*, args, **kwargs):
        """Simulate the selected external execution failure."""
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd=args, timeout=1)
        return subprocess.CompletedProcess(
            args=args, returncode=1 if mode == "exit" else 0, stdout="", stderr="failed"
        )

    monkeypatch.setattr(lolalign.subprocess, "run", failed)
    with pytest.raises(ToolExecutionError):
        lolalign.run_lolalign(
            executable="foldseek", reference_path=model, mobile_path=model,
            matrix_path=matrix, stdout_path=stdout, version="revision",
        )
    assert not matrix.exists()
    assert stdout.is_file()


@pytest.mark.skipif(
    not os.environ.get("FOLDSEEK_EXE") or not os.environ.get("FOLDSEEK_REFERENCE_MODEL"),
    reason="Set FOLDSEEK_EXE and FOLDSEEK_REFERENCE_MODEL for the real-tool integration test",
)
def test_real_foldseek_rigid_rotation_and_translation(*, tmp_path: Path) -> None:
    """Recover a known non-trivial rigid transform with the actual LoL-align binary."""
    source = Path(os.environ["FOLDSEEK_REFERENCE_MODEL"])
    if source.suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
        destination = tmp_path / "source.pdb"
        shutil.copyfile(src=source, dst=destination)
        source = destination
    atoms = parse_ca_atoms(source)
    assert len(atoms) >= 30
    reference, mobile = tmp_path / "reference.pdb", tmp_path / "mobile.pdb"
    reference_lines, mobile_lines = [], []
    for index, atom in enumerate(atoms, start=1):
        x, y, z = atom.coordinate
        common = f"ATOM  {index:5d}  CA  {atom.residue_name:>3s} A{index:4d}    "
        reference_lines.append(common + f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 90.00           C\n")
        mobile_lines.append(
            common + f"{-y + 12:8.3f}{x - 7:8.3f}{z + 4:8.3f}  1.00 90.00           C\n"
        )
    reference.write_text(data="".join(reference_lines) + "END\n", encoding="utf-8")
    mobile.write_text(data="".join(mobile_lines) + "END\n", encoding="utf-8")
    executable = os.environ["FOLDSEEK_EXE"]
    version = lolalign.foldseek_version(executable=executable)
    result = lolalign.run_lolalign(
        executable=executable, reference_path=reference, mobile_path=mobile,
        matrix_path=tmp_path / "matrix.txt", stdout_path=tmp_path / "stdout.txt", version=version,
    )
    assert result.tm_score_mobile_normalised > 0.99
    assert result.tm_score_reference_normalised > 0.99
    assert result.rmsd_angstrom < 0.1
    for original in atoms:
        x, y, z = original.coordinate
        transformed = result.transform.apply(coordinate=(-y + 12, x - 7, z + 4))
        assert math.dist(original.coordinate, transformed) < 0.1

    selected = tmp_path / "selected.tsv"
    selected.write_text(
        data="cluster_id\tprimary_group_type\tprimary_group_id\tcandidate_accession\t"
        "species_column\tpocket_number\tdruggability_score\tmapping_fraction\t"
        "conservative_fraction_plddt_ge_70\tpredictor_agreement\tstructural_evidence_status\n"
        "test\torthogroup\tOG_TEST\tREF\tone\t1\t1.0\t1.0\t1.0\ttrue\tSELECTED_HIGH_CONFIDENCE\n"
        "test\torthogroup\tOG_TEST\tMOBILE\ttwo\t1\t0.8\t1.0\t1.0\ttrue\t"
        "SELECTED_HIGH_CONFIDENCE\n",
        encoding="utf-8",
    )
    mappings = tmp_path / "mappings.tsv"
    mappings.write_text(
        data="accession\tpocket_number\tmapping_status\tmodel_label_chain\tmodel_label_seq_id\t"
        "model_auth_chain\tmodel_auth_seq_id\tmodel_insertion_code\n"
        + "".join(
            f"{accession}\t1\tMAPPED\tA\t{index}\tA\t{index}\t\n"
            for accession in ("REF", "MOBILE") for index in range(1, 11)
        ), encoding="utf-8",
    )
    assets = tmp_path / "assets.tsv"
    assets.write_text(
        data="accession\tpath\tsha256\n"
        + f"REF\t{reference}\t{sha256_file(reference)}\n"
        + f"MOBILE\t{mobile}\t{sha256_file(mobile)}\n", encoding="utf-8",
    )
    output = tmp_path / "real_pipeline"
    run_pipeline(
        selected_pockets_path=selected, pocket_residue_mappings_path=mappings,
        asset_manifest_path=assets, output_dir=output,
        settings=AlignmentSettings(
            run_usalign=False, run_tmalign=False, run_lolalign=True,
            foldseek_executable=executable, threads=1,
        ), resume=False, force=False, verbose=False,
    )
    summary = read_records(output / "tables" / "structural_alignment_summary.parquet")[0]
    assert summary["alignment_tools"] == "LoL-align"
    assert summary["position_alignment_status"] == "SAME_3D_POCKET_POSITION_SUPPORTED"
    alignments = read_records(output / "tables" / "structural_alignments.parquet")
    pair = next(row for row in alignments if row["status"] == "COMPLETE")
    assert pair["lol_homology_probability"] is not None
    assert pair["alignment_scope"] == "local"
