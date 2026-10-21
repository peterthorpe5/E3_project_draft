"""Input validation, exact sequence mapping and confidence interpretation."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import gemmi
import pytest
from conftest import make_model

from protein_pockets.io import (
    load_samples,
    read_fasta,
    sha256_file,
    write_json,
    write_tsv,
)
from protein_pockets.models import Sample, Settings
from protein_pockets.structure import prepare_structure


@pytest.mark.parametrize(
    "options",
    [
        {"confidence": "guess"},
        {"threads": 0},
        {"threads": -1},
        {"threads": True},
        {"threads": 1.5},
        {"threads": "2"},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"high_confidence": -1},
        {"high_confidence": 101},
        {"high_confidence": float("nan")},
        {"pocket_fraction": 0},
        {"pocket_fraction": 1.1},
        {"overlap": 0},
        {"overlap": float("nan")},
        {"predict_config": ""},
        {"rescore_config": ""},
    ],
)
def test_invalid_settings(*, options: dict) -> None:
    """Reject impossible thresholds and invalid worker counts before execution."""
    with pytest.raises(expected_exception=ValueError):
        Settings(**options)


@pytest.mark.parametrize(
    "identifier", ["../escape", "a/b", "", "x y", "=formula", "a" * 121]
)
def test_unsafe_sample_ids(*, model_path: Path, identifier: str) -> None:
    """Identifiers cannot escape result folders or become spreadsheet formulae."""
    with pytest.raises(expected_exception=ValueError):
        Sample(sample_id=identifier, model_path=model_path)


def test_missing_empty_and_wrong_model(*, tmp_path: Path) -> None:
    """Reject missing, empty and unsupported model files."""
    path = tmp_path / "missing.pdb"
    with pytest.raises(expected_exception=ValueError):
        Sample(sample_id="valid", model_path=path)
    path.touch()
    with pytest.raises(expected_exception=ValueError):
        Sample(sample_id="valid", model_path=path)
    wrong = tmp_path / "model.txt"
    wrong.write_text(data="text", encoding="utf-8")
    with pytest.raises(expected_exception=ValueError):
        Sample(sample_id="valid", model_path=wrong)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "ACD",
        ">\nACD",
        ">a\nACD\n>a\nACD",
        ">a\n",
        ">a\nAC-D",
        ">a\nACD*",
    ],
)
def test_invalid_fasta(*, tmp_path: Path, content: str) -> None:
    """FASTA ambiguities and invalid sequences produce actionable errors."""
    path = tmp_path / "representatives.fasta"
    path.write_text(data=content, encoding="utf-8")
    with pytest.raises(expected_exception=ValueError):
        read_fasta(path=path)


def test_fasta_and_named_manifest(
    *, tmp_path: Path, model_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An explicit manifest maps arbitrary model names to exact FASTA IDs."""
    fasta = tmp_path / "sequences.fasta"
    fasta.write_text(
        data="\n>seq1 description\nac\nd\n>unused\nAAA\n", encoding="utf-8"
    )
    manifest = tmp_path / "samples.tsv"
    manifest.write_text(
        data="sample_id\tmodel_path\tsequence_id\tcluster\tchain\n"
        f"cluster_01\t{model_path.name}\tseq1\tBRCA1_01\tQ\n",
        encoding="utf-8",
    )
    samples = load_samples(models=None, manifest=manifest, fasta=fasta, chain="")
    assert samples[0].sequence == "ACD"
    assert samples[0].chain == "Q"
    assert samples[0].cluster == "BRCA1_01"
    assert "Unused FASTA" in caplog.text
    assert read_fasta(path=None) == {}


@pytest.mark.parametrize(
    "content",
    [
        "sample_id,model_path\na,a.pdb\n",
        "sample_id\tmodel_path\na\n",
        "sample_id\tmodel_path\na\ta.pdb\textra\n",
        "sample_id\tmodel_path\n",
        "sample_id\tmodel_path\na\t\n",
    ],
)
def test_bad_manifests(*, tmp_path: Path, content: str) -> None:
    """Malformed manifests cannot silently become partial or incorrect input."""
    path = tmp_path / "input.tsv"
    path.write_text(data=content, encoding="utf-8")
    with pytest.raises(expected_exception=ValueError):
        load_samples(models=None, manifest=path, fasta=None, chain="")


def test_directory_mapping_and_duplicates(*, tmp_path: Path, model_path: Path) -> None:
    """Directory inputs require unique stems and match FASTA IDs exactly."""
    samples = load_samples(models=tmp_path, manifest=None, fasta=None, chain="Q")
    assert samples[0].sample_id == model_path.stem
    fasta = tmp_path / "seq.fasta"
    fasta.write_text(data=">different\nACD\n", encoding="utf-8")
    with pytest.raises(expected_exception=ValueError, match="use --manifest"):
        load_samples(models=tmp_path, manifest=None, fasta=fasta, chain="")
    (tmp_path / "Representative.cif").write_text(data="data_x\n", encoding="utf-8")
    with pytest.raises(expected_exception=ValueError, match="Duplicate"):
        load_samples(models=tmp_path, manifest=None, fasta=None, chain="")


def test_input_exclusivity_and_empty_directory(*, tmp_path: Path) -> None:
    """Exactly one populated input route is required."""
    for models, manifest in (
        (None, None),
        (tmp_path, tmp_path / "x.tsv"),
        (tmp_path, None),
        (tmp_path / "absent", None),
    ):
        with pytest.raises(expected_exception=ValueError):
            load_samples(models=models, manifest=manifest, fasta=None, chain="")


@pytest.mark.parametrize("suffix", [".pdb", ".cif", ".mmcif"])
def test_original_residue_and_fasta_mapping(*, tmp_path: Path, suffix: str) -> None:
    """Normalised numbering retains author numbering and insertion codes."""
    model = make_model(path=tmp_path / f"input{suffix}", insertions=True, water=True)
    rows, summary = prepare_structure(
        sample=Sample(
            sample_id="model", model_path=model, sequence="ACD", sequence_id="seq"
        ),
        settings=Settings(),
        destination=tmp_path / "prepared.pdb",
    )
    assert rows[1]["residue_key"] == "A_2"
    assert rows[1]["author_residue_number"] == 11
    assert rows[1]["insertion_code"] == "A"
    assert rows[1]["author_chain"] == "Q"
    assert [row["fasta_position"] for row in rows] == [1, 2, 3]
    assert summary["fasta_coverage"] == 1
    assert summary["sequence_status"] == "exact"
    assert summary["fraction_ge_threshold"] == pytest.approx(expected=2 / 3)
    assert "Excluded" in summary["warnings"]


def test_af3_atom_confidence_and_altloc_selection(
    *, tmp_path: Path, model_path: Path
) -> None:
    """Heavy-atom averaging and highest-occupancy altlocs do not count atoms twice."""
    structure = gemmi.read_structure(str(model_path))
    residue = structure[0][0][0]
    residue[0].b_iso = 50
    extra = residue[1].clone()
    residue[1].altloc = "A"
    residue[1].occ = 0.4
    extra.altloc = "B"
    extra.occ = 0.6
    extra.b_iso = 70
    residue.add_atom(extra)
    hydrogen = gemmi.Atom()
    hydrogen.name = "H"
    hydrogen.element = gemmi.Element("H")
    hydrogen.b_iso = 0
    residue.add_atom(hydrogen)
    structure.make_mmcif_document().write_file(str(tmp_path / "atoms.cif"))
    rows, _ = prepare_structure(
        sample=Sample(sample_id="model", model_path=tmp_path / "atoms.cif"),
        settings=Settings(),
        destination=tmp_path / "prepared.pdb",
    )
    assert rows[0]["plddt"] == pytest.approx(expected=(50 + 70 + 90 + 90) / 4)
    final = gemmi.read_structure(str(tmp_path / "prepared.pdb"))
    assert len(final[0][0][0]) == 4


def test_fragments_are_exact_unique_and_explicit(
    *, tmp_path: Path, model_path: Path
) -> None:
    """A fragment maps to FASTA only when explicitly enabled and unambiguous."""
    sample = Sample(sample_id="model", model_path=model_path, sequence="GGACDWW")
    with pytest.raises(expected_exception=ValueError, match="exactly match"):
        prepare_structure(
            sample=sample, settings=Settings(), destination=tmp_path / "x.pdb"
        )
    rows, summary = prepare_structure(
        sample=sample,
        settings=Settings(allow_fragments=True),
        destination=tmp_path / "x.pdb",
    )
    assert [row["fasta_position"] for row in rows] == [3, 4, 5]
    assert summary["fasta_coverage"] == pytest.approx(expected=3 / 7)
    assert summary["sequence_status"] == "unique_exact_fragment"
    with pytest.raises(expected_exception=ValueError):
        prepare_structure(
            sample=Sample(
                sample_id="ambiguous", model_path=model_path, sequence="ACDACD"
            ),
            settings=Settings(allow_fragments=True),
            destination=tmp_path / "x.pdb",
        )


def test_complex_requires_explicit_chain(*, tmp_path: Path) -> None:
    """Multiple protein chains cannot silently change the target being scored."""
    model = make_model(path=tmp_path / "complex.cif", chains=("LONG", "B"))
    for chain, sequence in (("", ""), ("missing", ""), ("all", "ACD")):
        with pytest.raises(expected_exception=ValueError):
            prepare_structure(
                sample=Sample(
                    sample_id="model", model_path=model, chain=chain, sequence=sequence
                ),
                settings=Settings(),
                destination=tmp_path / "x.pdb",
            )
    rows, metadata = prepare_structure(
        sample=Sample(sample_id="model", model_path=model, chain="LONG"),
        settings=Settings(confidence="none"),
        destination=tmp_path / "x.pdb",
    )
    assert rows[0]["author_chain"] == "LONG"
    assert rows[0]["plddt"] is None
    assert "Other protein chains excluded" in metadata["warnings"]
    _, metadata = prepare_structure(
        sample=Sample(sample_id="model", model_path=model, chain="all"),
        settings=Settings(),
        destination=tmp_path / "x.pdb",
    )
    assert metadata["chain_count"] == 2
    assert "inter-chain" in metadata["warnings"]


@pytest.mark.parametrize(
    "options",
    [
        {"ca_only": True},
        {"model_count": 2},
        {"confidence": (101,)},
        {"confidence": (-1,)},
        {"names": ("HOH",)},
    ],
)
def test_unusable_models(*, tmp_path: Path, options: dict) -> None:
    """Malformed confidence and structurally unsuitable input are rejected."""
    path = make_model(path=tmp_path / "bad.cif", **options)
    with pytest.raises(expected_exception=ValueError):
        prepare_structure(
            sample=Sample(sample_id="bad", model_path=path),
            settings=Settings(),
            destination=tmp_path / "prepared.pdb",
        )


def test_constant_confidence_warning_and_mse(*, tmp_path: Path) -> None:
    """Constant confidence is flagged and selenomethionine maps as methionine."""
    path = make_model(path=tmp_path / "mse.pdb", names=("MSE",), confidence=(90,))
    rows, summary = prepare_structure(
        sample=Sample(sample_id="model", model_path=path, sequence="M"),
        settings=Settings(),
        destination=tmp_path / "x.pdb",
    )
    assert rows[0]["amino_acid"] == "M"
    assert "Constant pLDDT" in summary["warnings"]


def test_atomic_outputs_and_hash(*, tmp_path: Path) -> None:
    """TSV preserves embedded tabs and empty-table headers; JSON refuses NaN."""
    path = tmp_path / "table.tsv"
    write_tsv(path=path, rows=[{"id": "a\tb", "value": 1.25}], columns=["id", "value"])
    with path.open(mode="r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(f=handle, delimiter="\t"))
    assert rows[0]["id"] == "a\tb"
    assert sha256_file(path=path) == hashlib.sha256(path.read_bytes()).hexdigest()
    write_tsv(path=path, rows=[], columns=["id"])
    assert path.read_text(encoding="utf-8").strip() == "id"
    json_path = tmp_path / "state.json"
    write_json(path=json_path, data={"ok": 1})
    with pytest.raises(expected_exception=ValueError):
        write_json(path=json_path, data={"bad": float("nan")})
    assert '"ok": 1' in json_path.read_text(encoding="utf-8")
