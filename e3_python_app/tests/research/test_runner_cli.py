"""Worker orchestration, provenance and independent CLI contracts."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from e3app.research import cli, runner
from e3app.research.cli import build_parser, installation_status, main, work_queue
from e3app.research.common import ResearchError, iter_fasta
from e3app.research.jobs import artifact_path, claim_job, get_job, job_directory, submit_job
from e3app.research.runner import (
    execute_job,
    family_metadata,
    prepare_input,
    run_next_job,
    search_representatives,
    selected_input,
)


def test_retrieval_mapping_and_downstream_artifact_flow(research_config):
    """Completed results carry checksums/runtime provenance and supply exact next-stage input."""
    config = research_config
    job = submit_job(
        workspace=config.workspace, operation="retrieve", parameters={"cluster_ids": ["GLOBAL_A"]}
    )
    assert run_next_job(config=config, job_id=job) == job
    assert get_job(workspace=config.workspace, job_id=job)["status"] == "COMPLETE"
    directory = job_directory(workspace=config.workspace, job_id=job)
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["runtime"]["application"] == "0.19.1"
    assert manifest["data_sources"]["sequences"]["bytes"] > 0
    fasta_name = next(key for key in manifest["artifacts"] if key.endswith("fasta"))
    assert (
        len(
            dict(
                iter_fasta(
                    path=artifact_path(workspace=config.workspace, job_id=job, artifact=fasta_name)
                )
            )
        )
        == 3
    )
    next_id = submit_job(
        workspace=config.workspace,
        operation="align",
        parameters={"source_job": job, "source_artifact": fasta_name},
    )
    next_job = claim_job(workspace=config.workspace, job_id=next_id)
    next_dir = job_directory(workspace=config.workspace, job_id=next_id)
    source = prepare_input(config=config, job=next_job, output=next_dir)
    subset = selected_input(
        config=config, source=source, output=next_dir, parameters={"sequence_ids": ["B"]}
    )
    assert dict(iter_fasta(path=subset)) == {"B": "ACDF"}
    assert family_metadata(config=replace(config, index=""), source=source)["B"]["taxon_id"] == 3702
    assert family_metadata(config=replace(config, taxonomy=""), source=source) == {}
    resolve = submit_job(
        workspace=config.workspace,
        operation="resolve",
        parameters={
            "identifiers": ["P1", "unknown"],
            "context": [{"input_id": "P1", "source_group_id": "E3_LOCAL"}],
        },
    )
    run_next_job(config=config, job_id=resolve)
    mapping = artifact_path(
        workspace=config.workspace, job_id=resolve, artifact="global_cluster_mapping.tsv"
    ).read_text()
    assert "UNMATCHED" in mapping and "GLOBAL_A" in mapping and "E3_LOCAL" in mapping
    taxonomy = submit_job(workspace=config.workspace, operation="taxonomy_index", parameters={})
    run_next_job(config=config, job_id=taxonomy)
    assert artifact_path(
        workspace=config.workspace, job_id=taxonomy, artifact="cluster_taxonomy.parquet"
    ).exists()
    assert run_next_job(config=config) is None


def test_input_integrity_dispatch_and_failures(
    research_config, protein_fasta, tmp_path, monkeypatch
):
    """Tampered inputs and invalid worker artifacts never become complete results."""
    config = research_config
    job_id = submit_job(
        workspace=config.workspace,
        operation="align",
        parameters={},
        fasta=protein_fasta.read_text(),
    )
    directory = job_directory(workspace=config.workspace, job_id=job_id)
    job = claim_job(workspace=config.workspace, job_id=job_id)
    assert prepare_input(config=config, job=job, output=directory).name == "input.fasta"
    (directory / "input.fasta").write_text("changed")
    with pytest.raises(ResearchError, match="changed"):
        prepare_input(config=config, job=job, output=directory)
    with pytest.raises(ResearchError):
        prepare_input(config=config, job={"parameters": {}}, output=tmp_path)
    with pytest.raises(ResearchError):
        selected_input(
            config=config, source=protein_fasta, output=tmp_path, parameters={"sequence_ids": "a"}
        )
    for operation, function in (
        ("subcluster", "subcluster"),
        ("predict", "predict_batch"),
        ("annotate", "annotate_batch"),
        ("search", "search_representatives"),
    ):
        identifier = submit_job(
            workspace=config.workspace,
            operation=operation,
            parameters={},
            fasta=protein_fasta.read_text(),
        )
        claimed = claim_job(workspace=config.workspace, job_id=identifier)
        callback = Mock(return_value={"ok": protein_fasta})
        monkeypatch.setattr(runner, function, callback)
        assert execute_job(config=config, job=claimed)["ok"] == protein_fasta
        assert callback.call_count == 1
    invalid = submit_job(
        workspace=config.workspace, operation="retrieve", parameters={"cluster_ids": "not-list"}
    )
    run_next_job(config=config, job_id=invalid)
    assert get_job(workspace=config.workspace, job_id=invalid)["status"] == "FAILED"
    assert (job_directory(workspace=config.workspace, job_id=invalid) / "worker.log").exists()
    identifier = submit_job(workspace=config.workspace, operation="retrieve", parameters={})
    monkeypatch.setattr(runner, "execute_job", Mock(return_value={"outside": protein_fasta}))
    run_next_job(config=config, job_id=identifier)
    assert get_job(workspace=config.workspace, job_id=identifier)["status"] == "FAILED"


def test_centroid_search_reports_homology_not_membership(
    research_config, protein_fasta, tmp_path, monkeypatch
):
    """A new query is not declared an exact global member from similarity alone."""
    database = tmp_path / "centroids.dmnd"
    database.touch()
    with pytest.raises(ResearchError):
        search_representatives(config=research_config, source=protein_fasta, output=tmp_path)

    def fake_command(*, arguments, output, config):
        (output / "representative_hits.raw.tsv").write_text(
            "a\tGLOBAL_A\t90\t100\t100\t1\t100\t1\t100\t100\t1e-20\t200\t90\n"
        )

    monkeypatch.setattr(runner, "run_command", fake_command)
    result = search_representatives(
        config=replace(research_config, centroid_database=str(database)),
        source=protein_fasta,
        output=tmp_path,
    )
    assert (
        "HOMOLOGY_TO_GLOBAL_CENTROID_NOT_EXACT_MEMBERSHIP"
        in result["representative_hits.tsv"].read_text()
    )


def test_cli_doctor_submit_worker_cancel_serve(research_config, tmp_path, monkeypatch, capsys):
    """Generic commands do not require an E3 resource or automatically invoke providers."""
    profile = tmp_path / "profile.toml"
    profile.write_text(f'workspace="{research_config.workspace}"\n')
    args = ["--config", str(profile)]
    assert build_parser().parse_args(["worker", "--once"]).once
    assert "executables" in installation_status(config=research_config)
    assert main(argv=[*args, "doctor"]) == 0
    assert "workspace" in capsys.readouterr().out
    assert main(argv=[*args, "jobs"]) == 0
    source = tmp_path / "input.fasta"
    source.write_text(">a\nACD\n")
    assert main(argv=[*args, "submit", "--operation", "align", "--fasta", str(source)]) == 0
    job = cli.list_jobs(workspace=research_config.workspace)[0]["job_id"]
    assert main(argv=[*args, "cancel", "--job-id", job]) == 0
    assert main(argv=[*args, "worker", "--once"]) == 0
    parameters = tmp_path / "params.json"
    parameters.write_text("[]")
    assert (
        main(argv=[*args, "submit", "--operation", "align", "--parameters", str(parameters)]) == 2
    )
    call = Mock(return_value=0)
    monkeypatch.setattr(cli.subprocess, "call", call)
    assert main(argv=[*args, "serve", "--port", "8503"]) == 0
    assert "standalone.py" in " ".join(call.call_args.args[0])
    assert call.call_args.kwargs["env"]["E3_RESEARCH_CONFIG"] == str(profile)
    assert main(argv=[*args, "serve", "--host", "bad host"]) == 2
    monkeypatch.setattr(cli, "run_next_job", Mock(side_effect=KeyboardInterrupt))
    assert main(argv=[*args, "worker", "--once"]) == 130


def test_bounded_worker_failure_exit_and_polling(research_config, monkeypatch):
    """Persistent workers poll briefly and bounded workers return unsuccessful job status."""
    job = submit_job(workspace=research_config.workspace, operation="retrieve", parameters={})
    assert work_queue(config=research_config, once=True, job_id=job) == 1
    callback = Mock(side_effect=[None, "a" * 32])
    monkeypatch.setattr(cli, "run_next_job", callback)
    monkeypatch.setattr(cli, "get_job", Mock(return_value={"status": "COMPLETE"}))
    pause = Mock()
    monkeypatch.setattr(cli.time, "sleep", pause)
    assert work_queue(config=research_config, maximum_jobs=1, poll_seconds=0.1) == 0
    pause.assert_called_once_with(0.1)


def test_alignment_worker_publishes_auspice_and_handles_interrupt(
    research_config, tmp_path, monkeypatch
):
    """The worker publishes real tree metadata and interrupt status, preserving job boundaries."""
    from e3app.research import analysis

    config = research_config

    def fake_command(*, arguments, output, config, stdout=None):
        if "--version" in arguments:
            stdout.write_text("MAFFT test\n")
        elif "--auto" in arguments:
            stdout.write_text(Path(arguments[-1]).read_text())
        else:
            stdout.write_text("(UNIPROT_P1:0.1,B:0.2,C:0.3);\n")

    monkeypatch.setattr(analysis, "run_command", fake_command)
    identifier = submit_job(
        workspace=config.workspace,
        operation="align",
        parameters={},
        fasta=">UNIPROT_P1\nACDE\n>B\nACDF\n>C\nAAAA\n",
    )
    run_next_job(config=config, job_id=identifier)
    assert get_job(workspace=config.workspace, job_id=identifier)["status"] == "COMPLETE"
    dataset = artifact_path(workspace=config.workspace, job_id=identifier, artifact="auspice.json")
    assert "Human" in dataset.read_text() and "Plant" in dataset.read_text()
    assert (
        config.workspace / "datasets" / f"{identifier}.json"
    ).read_bytes() == dataset.read_bytes()
    identifier = submit_job(
        workspace=config.workspace, operation="align", parameters={}, fasta=">a\nACD\n"
    )
    run_next_job(config=config, job_id=identifier)
    assert get_job(workspace=config.workspace, job_id=identifier)["status"] == "COMPLETE"
    identifier = submit_job(workspace=config.workspace, operation="retrieve", parameters={})
    monkeypatch.setattr(runner, "execute_job", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        run_next_job(config=config, job_id=identifier)
    assert get_job(workspace=config.workspace, job_id=identifier)["status"] == "FAILED"


def test_source_and_resolution_error_contracts(
    research_config, protein_fasta, tmp_path, monkeypatch
):
    """Malformed dispatch inputs and cross-dataset IDs fail with clear diagnostics."""
    config = research_config
    output = tmp_path / "selection_bad"
    output.mkdir()
    with pytest.raises(ResearchError, match="absent"):
        selected_input(
            config=config,
            source=protein_fasta,
            output=output,
            parameters={"sequence_ids": ["missing"]},
        )
    with pytest.raises(ResearchError, match="100000"):
        selected_input(
            config=config,
            source=protein_fasta,
            output=output,
            parameters={"sequence_ids": ["a"] * 100001},
        )
    for parameters in (
        {"identifiers": "bad"},
        {"identifiers": ["a"], "context": [{"input_id": "outside"}]},
    ):
        identifier = submit_job(
            workspace=config.workspace, operation="resolve", parameters=parameters
        )
        job = claim_job(workspace=config.workspace, job_id=identifier)
        with pytest.raises(ResearchError):
            execute_job(config=config, job=job)
    assert family_metadata(config=replace(config, taxonomy=""), source=protein_fasta) == {}
    with pytest.raises(ResearchError):
        family_metadata(config=replace(config, max_sequences=1), source=protein_fasta)
