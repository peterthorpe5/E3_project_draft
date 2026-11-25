"""Validate full-model identity, local WhatRes execution and the upstream output contract."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, call

import pandas as pd
import pytest
from Bio.PDB import MMCIFIO, MMCIFParser, PDBParser

from e3app import whatres
from e3app.errors import AppError
from test_external_hog import make_model_bundle

PDB = (
    "ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00 80.00           N  \n"
    "ATOM      2  CA  ALA A   1       2.000   2.000   3.000  1.00 80.00           C  \n"
    "ATOM      3  C   ALA A   1       3.000   2.000   3.000  1.00 80.00           C  \n"
    "ATOM      4  O   ALA A   1       4.000   2.000   3.000  1.00 80.00           O  \n"
    "ATOM      5  CB  ALA A   1       2.000   2.500   3.000  1.00 80.00           C  \n"
    "ATOM      6  N   GLY A   2       3.000   3.000   3.000  1.00 60.00           N  \n"
    "ATOM      7  CA  GLY A   2       4.000   3.000   3.000  1.00 60.00           C  \n"
    "ATOM      8  C   GLY A   2       5.000   3.000   3.000  1.00 60.00           C  \n"
    "ATOM      9  O   GLY A   2       6.000   3.000   3.000  1.00 60.00           O  \n"
    "TER\nEND\n"
).encode("ascii")

CLI = r"""
import argparse
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("operation", choices=["score"])
parser.add_argument("structure", type=Path)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--features-out", type=Path, required=True)
args = parser.parse_args()
structure_id = args.structure.stem
assert b"ATOM  " in args.structure.read_bytes()
assert Path(os.environ["WHATRES_FEATURES"]).parent == Path.cwd() / "whatres-features"
assert Path(os.environ["WHATRES_MODELS_DIR"]) == Path.cwd() / "models"
assert Path(os.environ["TMPDIR"]) == args.structure.parent
args.features_out.write_text(
    f"id\tqc_n_residues\tsurf_n_chains\tdist_test\n{structure_id}\t2\t1\t1\n",
    encoding="utf-8",
)
args.out.write_text(
    f"id\tapparent_resolution\trealism\tnote\n{structure_id}\t2.35\t42.5\t\n",
    encoding="utf-8",
)
"""


RESIDUE_CLI = r"""#!/usr/bin/env python3
import sys
from pathlib import Path

assert sys.argv[1:] == ["-do", "pdb_quality_check", "-in", "model.list", "-opt", "Options.txt"]
model = Path(Path("model.list").read_text().strip())
assert model.parent == Path.cwd() and b" CB " in model.read_bytes()
assert "<qc_reference_db>reference.bin;" in Path("Options.txt").read_text()
assert Path("reference.bin").is_file()
Path("local_quality_report.tsv").write_text(
    "pdb\tchain\taa\tresnum\tref_count\tresidue_score\tn_outliers\tworst_metric\tworst_score\n"
    "e3_model\tA\tG\t2\t200\t12.25\t0\tbond_N_CA\t2.50\n"
    "e3_model\tA\tA\t1\t100\t30.25\t2\tclashscore\t6.64\n"
)
"""


@pytest.fixture
def local_whatres(*, tmp_path: Path) -> Path:
    """Install a test CLI with the file layout and TSV protocol of the real release."""
    root = tmp_path / "WhatRes source"
    files = {
        "whatres/__init__.py": '__version__ = "1.0.0"\n',
        "whatres/cli.py": CLI,
        "whatres-features/whatres-features": RESIDUE_CLI,
        "data/Options_features.txt": ("<qc_reference_db>original;\n<prefix>fx_;\n"
                                      "<qc_min_ref_count>5;\n"),
        "data/native49_structure_reference.bin": "",
        "models/apparent_resolution_model.joblib": "",
        "models/over_regularisation_model.joblib": "",
        "models/training_oof_apparent_resolution.tsv": "",
        "models/training_oof_realism.tsv": "",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / "whatres-features/whatres-features").chmod(0o755)
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").symlink_to(sys.executable)
    return root


def make_mmcif(*, pdb: bytes = PDB) -> bytes:
    """Convert fixture atoms to a small mmCIF for the inverse conversion test."""
    structure = PDBParser(QUIET=True).get_structure("fixture", StringIO(pdb.decode()))
    writer = MMCIFIO()
    writer.set_structure(structure)
    output = StringIO()
    writer.save(output)
    return output.getvalue().encode()


def test_whatres_directory_is_optional_and_validates_assets(
    *, local_whatres: Path, tmp_path: Path,
) -> None:
    """Resolve an opted-in host checkout and explain missing or incompatible installs."""
    assert whatres.whatres_directory(environment={}) is None
    config = {"E3_WHATRES_DIR": str(local_whatres)}
    assert whatres.whatres_directory(environment=config) == local_whatres
    with pytest.raises(AppError, match="must point to the WhatRes checkout"):
        whatres.whatres_directory(environment={"E3_WHATRES_DIR": str(tmp_path / "absent")})
    model = local_whatres / "models/apparent_resolution_model.joblib"
    model.unlink()
    (local_whatres / "whatres-features/whatres-features").chmod(0o644)
    with pytest.raises(AppError, match=r"Missing: .*apparent_resolution_model.*whatres-features"):
        whatres.whatres_directory(environment=config)
    (local_whatres / "whatres/__init__.py").write_text("__version__ = '2.0.0'", encoding="utf-8")
    with pytest.raises(AppError, match="Use the WhatRes v1.0.0 release"):
        whatres.whatres_directory(environment=config)


@pytest.mark.parametrize(
    "filename,identifier",
    [("9HKI.pdb", "9hki"), ("AF-Q9SA03-F1.cif", "e3_model"),
     ("../../--features-out.pdb", "e3_model"), ("0123.pdb", "e3_model"),
     ("safe/1000.pdb", "e3_model"), ("structure name.pdb", "e3_model")],
)
def test_structure_id_preserves_only_an_exact_pdb_id(*, filename: str, identifier: str) -> None:
    """Only a standard PDB ID can request the upstream training-structure lookup."""
    assert whatres.whatres_structure_id(filename=filename) == identifier


def test_recorded_targets_bind_native_hashes_to_group_species_and_pair_roles() -> None:
    """Reject another HOG, release rank, species, missing hash or an ambiguous member."""
    row = {"review_rank": 1, "primary_group_id": "HOG1", "candidate_accession": "P1",
           "species_column": "Species_A", "model_sha256": "B" * 64}
    inventory = pd.DataFrame([
        row,
        {**row, "species_column": "Species_B", "model_sha256": "a" * 64},
        {**row, "candidate_accession": "P2", "model_sha256": ""},
        {**row, "candidate_accession": "P3"},
        {**row, "candidate_accession": "P3", "model_sha256": "e" * 64},
        {**row, "candidate_accession": "P4", "primary_group_id": "HOG2"},
        {**row, "candidate_accession": "P5", "review_rank": 2},
    ])
    targets = whatres.recorded_whatres_targets(inventory=inventory, review_rank=1, group_id="HOG1")
    assert [target.label for target in targets] == ["P1 · Species A", "P1 · Species B"]
    pair = whatres.recorded_whatres_targets(
        inventory=inventory, review_rank=1, group_id="HOG1",
        pair_members={"reference": ("P1", "Species_B"), "mobile": ("P1", "Species_A")},
    )
    assert [target.label for target in pair] == [
        "Reference · P1 · Species B", "Mobile · P1 · Species A",
    ]
    assert [target.model_sha256 for target in pair] == ["a" * 64, "b" * 64]
    assert not whatres.recorded_whatres_targets(
        inventory=inventory, review_rank=1, group_id="HOG1",
        pair_members={"mobile": ("P1", "Unknown_species")},
    )
    assert not whatres.recorded_whatres_targets(
        inventory=inventory.drop(columns="model_sha256"), review_rank=1, group_id="HOG1",
    )


def test_legacy_review_can_retrieve_a_full_model_by_uniprot_accession() -> None:
    """Provide a public lookup without claiming that it identifies the reviewed coordinate file."""
    inventory = pd.DataFrame([{
        "review_rank": 1, "primary_group_id": "HOG1", "candidate_accession": "Q6NKN8",
        "species_column": "Arabidopsis_thaliana",
    }])
    targets = whatres.recorded_whatres_targets(
        inventory=inventory, review_rank=1, group_id="HOG1",
    )
    assert targets == (whatres.WhatResTarget(
        label="Q6NKN8 · Arabidopsis thaliana", alphafold_accession="Q6NKN8",
        group_id="HOG1", species="Arabidopsis_thaliana", review_accession="Q6NKN8",
    ),)
    assert not whatres.recorded_whatres_targets(
        inventory=inventory.iloc[:0], review_rank=1, group_id="HOG1",
    )


def test_prepare_pdb_retains_all_atom_coordinates_and_confidence() -> None:
    """Keep a PDB byte-for-byte and convert each original atom from an mmCIF."""
    assert whatres._prepare_pdb(content=PDB, filename="source.PDB") == (PDB, "PDB")
    assert whatres._prepare_pdb(
        content=b"\xef\xbb\xbf" + PDB, filename="with_bom.pdb",
    ) == (PDB, "PDB")
    cif = make_mmcif()
    rebuilt, input_format = whatres._prepare_pdb(content=cif, filename="source.mmcif")
    assert input_format == "mmCIF"
    original = MMCIFParser(QUIET=True).get_structure("original", StringIO(cif.decode()))
    converted = PDBParser(QUIET=True).get_structure("converted", StringIO(rebuilt.decode()))
    atoms = list(zip(original.get_atoms(), converted.get_atoms(), strict=True))
    assert len(atoms) == 9
    for before, after in atoms:
        assert before.full_id[1:] == after.full_id[1:]
        assert before.coord == pytest.approx(after.coord)
        assert before.bfactor == pytest.approx(after.bfactor)
        assert before.occupancy == pytest.approx(after.occupancy)


@pytest.mark.parametrize(
    "content,filename,problem",
    [
        (b"", "empty.pdb", "non-empty"),
        (PDB, "wrong.txt", "PDB or mmCIF"),
        (b"data_corrupt\n", "broken.cif", "valid PDB or convertible mmCIF"),
        (b"\xff", "bad.pdb", "valid PDB"),
        (PDB.splitlines(keepends=True)[1], "trace.pdb", "full atomic"),
        (PDB.replace(PDB.splitlines(keepends=True)[4], b""), "backbone.pdb", "side-chain"),
        (PDB.replace(b"   1.000", b"     nan", 1), "invalid.pdb", "finite"),
    ],
)
def test_prepare_pdb_rejects_unusable_models(
    *, content: bytes, filename: str, problem: str,
) -> None:
    """Require representable atom geometry before invoking the external tool."""
    with pytest.raises(AppError, match=problem):
        whatres._prepare_pdb(content=content, filename=filename)


def test_size_limit_is_checked_before_coordinates_are_parsed(
    *, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enforce the coordinate size bound for uploaded and programmatic inputs."""
    monkeypatch.setattr(whatres, "MAX_COORDINATE_BYTES", len(PDB) - 1)
    with pytest.raises(AppError, match="20 MB"):
        whatres._prepare_pdb(content=PDB, filename="large.pdb")


@pytest.mark.parametrize(
    "body",
    ["", "id\trealism\ne3_model\n", "id\trealism\nwrong\t99\n",
     "id\tid\nwrong\te3_model\n",
     "id\trealism\ne3_model\t10\t30\n", "id\trealism\ne3_model\t10\ne3_model\t30\n"],
)
def test_read_whatres_row_requires_one_complete_identity_bound_result(
    *, body: str, tmp_path: Path,
) -> None:
    """Handle incomplete, duplicated or mismatched output without returning a score."""
    table = tmp_path / "scores.tsv"
    table.write_text(body, encoding="utf-8")
    with pytest.raises(AppError, match="invalid scores.tsv"):
        whatres._read_whatres_row(path=table, structure_id="e3_model")
    with pytest.raises(AppError, match="invalid missing.tsv"):
        whatres._read_whatres_row(path=tmp_path / "missing.tsv", structure_id="e3_model")


def test_score_whatres_bundle_keeps_audit_and_scores_after_failures(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Score verified ZIP members independently and preserve the full request order."""
    hog = "N0.HOG0001"
    accessions = ("P38398", "Q9SA03", "Q12345", "Q6NKN8")
    bundle = make_model_bundle(accessions=accessions, hog_id=hog)
    missing, broken, mismatched, included = bundle.records
    bundle = replace(bundle, records=(
        replace(missing, status="not_available", model_sha256="", detail="Unavailable"),
        broken, replace(mismatched, model_sha256="f" * 64), included,
    ))
    score = whatres.WhatResScore(
        model_sha256=included.model_sha256, scored_pdb_sha256="a" * 64,
        input_format="mmCIF", structure_id="e3_model", realism=45.6, apparent_resolution=2.1,
        note="",
    )
    assess = Mock(side_effect=[AppError("Geometry failed"), score])
    monkeypatch.setattr(whatres, "score_whatres", assess)
    progress = Mock()
    report = whatres.score_whatres_bundle(
        directory=tmp_path, bundle=bundle, hog_id=hog, progress=progress,
    )
    assert report["hog_id"].tolist() == [hog] * len(accessions)
    assert report["accession"].tolist() == list(accessions)
    assert report["retrieval_status"].tolist() == ["not_available"] + ["included"] * 3
    assert report["scoring_status"].tolist() == ["not_attempted", "error", "error", "scored"]
    assert report["detail"].tolist() == [
        "Unavailable", "Geometry failed",
        "Prepared model checksum differs from its audit record", "",
    ]
    assert report.loc[:2, ["realism", "apparent_resolution"]].isna().all().all()
    assert report.loc[3, ["realism", "apparent_resolution"]].tolist() == [45.6, 2.1]
    assert report.loc[3, "model_url"] == included.model_url
    assert report.loc[3, "scored_pdb_sha256"] == "a" * 64
    assert report.loc[3, "whatres_version"] == "1.0.0"
    assert assess.call_args_list == [
        call(
            directory=tmp_path,
            content=f"data_{row.accession}\n# exact test coordinate bytes\n".encode(),
            filename="alphafold.cif", expected_sha256=row.model_sha256,
        )
        for row in (broken, included)
    ]
    assert progress.call_args_list == [
        call(completed=index, total=len(accessions)) for index in range(1, len(accessions) + 1)
    ]


def test_score_whatres_bundle_with_no_downloads_returns_blank_metrics(*, tmp_path: Path) -> None:
    """Keep the TSV schema even when every requested model is unavailable."""
    hog = "N0.HOG0001"
    bundle = make_model_bundle(accessions=("Q9SA03",), hog_id=hog)
    record = replace(bundle.records[0], status="error", model_sha256="", detail="Connection error")
    report = whatres.score_whatres_bundle(
        directory=tmp_path, bundle=replace(bundle, records=(record,)), hog_id=hog,
    )
    assert tuple(report.columns) == whatres.HOG_SCORE_COLUMNS
    assert report.loc[0, "scoring_status"] == "not_attempted"
    assert report.loc[0, ["realism", "apparent_resolution"]].isna().all()


def test_score_whatres_runs_the_cli_with_private_scratch_and_checks_provenance(
    *, local_whatres: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute a local process, ignoring inherited tool overrides, and return exact input hashes."""
    monkeypatch.setenv("WHATRES_MODELS_DIR", "/wrong/models")
    monkeypatch.setenv("WHATRES_FEATURES", "/wrong/executable")
    digest = sha256(PDB).hexdigest()
    score = whatres.score_whatres(
        directory=local_whatres, content=PDB, filename="9HKI.pdb", expected_sha256=digest,
    )
    assert score == whatres.WhatResScore(
        model_sha256=digest, scored_pdb_sha256=digest, input_format="PDB",
        structure_id="9hki", apparent_resolution=2.35, realism=42.5, note="",
    )
    with pytest.raises(AppError, match="differs from the original review model"):
        whatres.score_whatres(
            directory=local_whatres, content=PDB, filename="model.pdb", expected_sha256="a" * 64,
        )
    cif = make_mmcif()
    converted = whatres.score_whatres(directory=local_whatres, content=cif, filename="model.cif")
    assert converted.input_format == "mmCIF"
    assert converted.model_sha256 == sha256(cif).hexdigest()
    assert converted.scored_pdb_sha256 != converted.model_sha256


@pytest.mark.parametrize(
    "metric_line,feature_line",
    [
        ("e3_model\tnan\t42\t", "e3_model\t2\t1\t1"),
        ("e3_model\t2.5\t101\t", "e3_model\t2\t1\t1"),
        ("e3_model\t2.5\t0\t", "e3_model\t0\t1\t1"),
        ("e3_model\t2.5\t0\t", "e3_model\t2\t0\t1"),
        ("e3_model\t2.5\t0\t", "e3_model\t2\t1\t"),
    ],
)
def test_score_whatres_rejects_failed_features_and_invalid_metrics(
    *, metric_line: str, feature_line: str, local_whatres: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject scores derived from a failed feature extractor and non-physical values."""
    def write_outputs(*, directory: Path, pdb_path: Path, scratch: Path) -> None:
        """Simulate a CLI that returned a corrupt numerical value or feature row."""
        assert directory == local_whatres and pdb_path.is_file()
        (scratch / "scores.tsv").write_text(
            "id\tapparent_resolution\trealism\tnote\n" + metric_line + "\n", encoding="utf-8",
        )
        (scratch / "features.tsv").write_text(
            "id\tqc_n_residues\tsurf_n_chains\tdist_test\n" + feature_line + "\n", encoding="utf-8",
        )

    monkeypatch.setattr(whatres, "_run_whatres", write_outputs)
    with pytest.raises(AppError, match="complete geometry features and valid scores"):
        whatres.score_whatres(directory=local_whatres, content=PDB, filename="model.pdb")


def test_run_whatres_handles_launch_failure_cli_failure_and_timeout(
    *, local_whatres: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Terminate the process group on expiry and surface a recoverable scoring error."""
    input_file = tmp_path / "model.pdb"
    input_file.write_bytes(PDB)
    with pytest.raises(AppError, match="Could not run WhatRes"):
        whatres._run_whatres(directory=tmp_path / "absent", pdb_path=input_file, scratch=tmp_path)
    cli = local_whatres / "whatres/cli.py"
    cli.write_text("raise SystemExit('feature extractor failed')", encoding="utf-8")
    with pytest.raises(AppError, match="Check the app host log"):
        whatres._run_whatres(directory=local_whatres, pdb_path=input_file, scratch=tmp_path)
    assert "feature extractor failed" in caplog.text
    cli.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(whatres, "SCORE_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(AppError, match="exceeded 0.1 seconds"):
        whatres._run_whatres(directory=local_whatres, pdb_path=input_file, scratch=tmp_path)


def test_score_whatres_handles_unwritable_scratch(
    *, local_whatres: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report temporary storage failures without exposing implementation exceptions."""
    def unable_to_write(**kwargs: object) -> None:
        """Simulate a full or inaccessible scratch filesystem."""
        raise OSError("no scratch")

    monkeypatch.setattr(whatres, "TemporaryDirectory", unable_to_write)
    with pytest.raises(AppError, match="temporary directory"):
        whatres.score_whatres(directory=local_whatres, content=PDB, filename="model.pdb")


@pytest.mark.parametrize("name", ["9hki", "AF-P02787"])
@pytest.mark.skipif(
    not os.getenv("E3_WHATRES_TEST_DIR"), reason="requires the upstream test models",
)
def test_real_whatres_matches_the_authors_published_scores(*, name: str) -> None:
    """Cross-check a reference crystal structure and a predicted model using the real tool."""
    directory = whatres.whatres_directory(
        environment={"E3_WHATRES_DIR": os.environ["E3_WHATRES_TEST_DIR"]},
    )
    expected = pd.read_csv(directory / "tests/expected_scores.tsv", sep="\t", keep_default_na=False)
    row = expected.set_index("id").loc[name.lower()]
    path = directory / f"tests/structures/{name}.pdb"
    result = whatres.score_whatres(
        directory=directory, content=path.read_bytes(), filename=path.name,
    )
    assert result.apparent_resolution == pytest.approx(row.apparent_resolution, abs=0.0001)
    assert result.realism == pytest.approx(row.realism, abs=0.0001)
    assert result.note == row.note
