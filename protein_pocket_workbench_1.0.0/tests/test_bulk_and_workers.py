"""Critical real-world import, tool-adapter and worker regression tests."""

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import duckdb
import gemmi
import pytest

from pocket_workbench import jobs
from pocket_workbench.comparison import compare_pair
from pocket_workbench.core import (
    ComparisonSettings,
    WorkbenchError,
    load_project,
    settings_record,
    write_json,
)
from pocket_workbench.importing import (
    import_project,
    read_pipeline_database,
)
from pocket_workbench.sequences import fasta_text


def test_report_and_nested_af3_cifs_restore_coordinates_and_fasta_mapping(
    project, tmp_path
):
    """A report plus original model ZIPs restores tool keys and original labels."""
    data = load_project(root=project)
    report = tmp_path / "report.html"
    report.write_text(
        '<script id="data" type="application/json">'
        + json.dumps(
            {
                "samples": data["models"],
                "pockets": data["pockets"],
                "ranked": [
                    row for row in data["pockets"] if row["method"] == "fpocket"
                ],
            }
        )
        + "</script>"
    )
    archive = tmp_path / "alphafold_models.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for model in data["models"]:
            structure = gemmi.read_structure(str(project / model["prepared_model"]))
            structure[0][0].name = "B"
            for residue in structure[0][0]:
                residue.seqid = gemmi.SeqId(residue.seqid.num + 100, " ")
            text = structure.make_mmcif_document().as_string()
            handle.writestr(
                f"alpha_fold_models/fold_{model['sample_id']}/{model['sample_id']}.cif",
                text,
            )
    fasta = tmp_path / "representatives.fasta"
    fasta.write_text(fasta_text(records=data["sequences"]))
    root = import_project(
        sources=[report, archive], output=tmp_path / "rebuilt", fasta=fasta
    )
    result = load_project(root=root)
    assert len(result["pockets"]) == 6
    assert all(
        row["coordinates"] and row["mapping_status"] == "exact_sequence"
        for row in result["models"]
    )
    residue = json.loads((root / result["models"][0]["coordinates"]).read_text())[0]
    assert residue["author_chain"] == "B"
    assert residue["author_residue_number"] == 101
    assert residue["residue_key"] == "A_1"
    fit = compare_pair(
        root=root,
        data=result,
        reference="synthetic_reference",
        mobile="synthetic_mobile",
        settings=ComparisonSettings(engine="sequence_kabsch"),
    )
    assert fit["rmsd"] < 0.002


def test_attach_model_zip_to_a_report_only_workbench_project(project, tmp_path):
    """The app's add-models route retains the current evidence and adds structures."""
    data = load_project(root=project)
    for model in data["models"]:
        model["coordinates"] = None
        model["prepared_model"] = None
    report = tmp_path / "report.html"
    report.write_text(
        '<script id="data" type="application/json">'
        + json.dumps({"samples": data["models"], "pockets": data["pockets"]})
        + "</script>"
    )
    base = import_project(sources=[report], output=tmp_path / "base")
    raw = tmp_path / "models"
    raw.mkdir()
    for model in load_project(root=project)["models"]:
        (raw / (model["sample_id"] + ".pdb")).write_bytes(
            (project / model["prepared_model"]).read_bytes()
        )
    combined = import_project(sources=[base, raw], output=tmp_path / "combined")
    assert len(load_project(root=combined)["pockets"]) == 6
    assert all(model["coordinates"] for model in load_project(root=combined)["models"])


def test_pipeline_database_reader_requires_real_tables(tmp_path):
    """Database import reads the original materialised tables and residue keys."""
    path = tmp_path / "protein_pockets.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE samples (sample_id VARCHAR)")
        db.execute("INSERT INTO samples VALUES ('a')")
        db.execute("CREATE TABLE pockets (sample_id VARCHAR, residue_ids VARCHAR)")
        db.execute("INSERT INTO pockets VALUES ('a', 'A_1;A_2')")
        db.execute("CREATE TABLE ranked_pockets AS SELECT * FROM pockets")
        db.execute("CREATE TABLE method_runs (sample_id VARCHAR)")
    result = read_pipeline_database(path=path)
    assert result["pockets"][0]["residues"] == ["A_1", "A_2"]
    invalid = tmp_path / "invalid.duckdb"
    with duckdb.connect(str(invalid)) as db:
        db.execute("CREATE VIEW samples AS SELECT 'a' AS sample_id")
    with pytest.raises(WorkbenchError, match="materialised"):
        read_pipeline_database(path=invalid)


def test_prediction_worker_merges_ranks_and_invalidates_old_comparisons(
    project, monkeypatch
):
    """New predictor evidence is merged without replacing model/sequence maps."""
    original = load_project(root=project)

    def predictor(command, check):
        """Write a deterministic completed predictor report at its requested output."""
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True)
        samples = [
            dict(
                row,
                fpocket_status="complete",
                p2rank_status="complete",
                rescore_status="complete",
            )
            for row in original["models"]
        ]
        report = {
            "samples": samples,
            "pockets": original["pockets"],
            "ranked": original["pockets"],
            "methods": [],
            "manifest": {"test": True},
        }
        (output / "report.html").write_text(
            '<script id="data" type="application/json">'
            + json.dumps(report)
            + "</script>"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(jobs.subprocess, "run", predictor)
    assert (
        jobs.run_prediction(root=project, options={"threads": 1}, job_id="job_test")
        == 0
    )
    data = load_project(root=project)
    assert data["comparisons"] == []
    assert data["models"][0]["coordinates"] == original["models"][0]["coordinates"]
    assert data["models"][0]["sequence_id"] == original["models"][0]["sequence_id"]
    assert len(data["pockets"]) == 6


def test_sequence_worker_runs_without_browser_state(project):
    """Persisted requests can perform an actual local MSA/tree independently."""
    path = project / "jobs/job_alignment/request.json"
    write_json(
        path=path,
        value={
            "root": str(project),
            "job_id": "job_alignment",
            "task": "sequences",
            "options": {"threads": 1, "bootstrap": 0},
        },
    )
    assert jobs.run_job(request_path=path) == 0
    assert json.loads(path.with_name("status.json").read_text())["status"] == "complete"


def test_failed_process_launch_cannot_leave_a_permanent_queued_job(
    project, monkeypatch
):
    """An executable launch failure becomes a visible terminal job failure."""

    def fail(*args, **kwargs):
        """Simulate process creation failing before a worker can write status."""
        raise OSError("launch failed")

    monkeypatch.setattr(jobs.subprocess, "Popen", fail)
    with pytest.raises(WorkbenchError, match="Could not launch"):
        jobs.start_job(root=project, task="compare", options={})
    statuses = [
        json.loads(path.read_text())["status"]
        for path in (project / "jobs").glob("*/status.json")
    ]
    assert statuses == ["failed"]


def test_usalign_adapter_runs_argv_in_the_recorded_working_directory(
    project, monkeypatch
):
    """The external adapter applies USalign's transform without shell evaluation."""
    from pocket_workbench import comparison

    executable = project / "fake_usalign"
    executable.write_text("executable fixture")
    monkeypatch.setattr(comparison.shutil, "which", lambda value: str(executable))

    def aligner(command, cwd, **kwargs):
        """Return an independently checked rigid fit through the external format."""
        original = json.loads(
            (
                project / load_project(root=project)["comparisons"][0]["result_path"]
            ).read_text()
        )
        lines = [
            f"{i} {original['translation'][i]} "
            + " ".join(str(value) for value in original["rotation"][i])
            for i in range(3)
        ]
        (cwd / "matrix.txt").write_text("\n".join(lines))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Aligned length= 32, RMSD= 0.001, Seq_ID=n_identical/n_aligned="
                " 0.97\nTM-score= 0.99\nTM-score= 0.98\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(comparison.subprocess, "run", aligner)
    result = compare_pair(
        root=project,
        data=load_project(root=project),
        reference="synthetic_reference",
        mobile="synthetic_mobile",
        settings=ComparisonSettings(engine="usalign"),
    )
    assert result["engine"] == "usalign"
    assert result["tm_reference"] == 0.98
    assert result["pocket_matches"][0]["fold_supported"] is True
    assert (
        project / "comparisons" / result["comparison_id"] / "command.json"
    ).is_file()
    assert settings_record(settings=ComparisonSettings())["radius"] == 4
