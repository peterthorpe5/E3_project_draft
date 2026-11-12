"""App-host worker prerequisites, failure reporting and queue isolation."""

from dataclasses import replace
import json
import os
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from e3app.research.common import ResearchConfig, ResearchError
from e3app.research.jobs import (
    artifact_path,
    claim_job,
    fail_queued_job,
    get_job,
    job_directory,
    list_jobs,
    queued_external_provider_job,
    submit_job,
)
from e3app.research.local_worker import (
    _wait_for_worker,
    start_queued_provider_job,
    submit_local_alignment,
    submit_local_provider_job,
)

FASTA = ">a\nACD\n>b\nACE\n>c\nACF\n"

PROVIDER_STUB = r'''
import os
from pathlib import Path
from urllib.parse import parse_qs

import requests


def deny_network(*args, **kwargs):
    """Prevent live HTTP access if the provider fixture cannot answer."""
    raise AssertionError("Live HTTP is disabled in the provider worker test")


requests.request = deny_network

from e3app.research import providers


def fixture_request(*, url, method="GET", body=None, **kwargs):
    """Serve deterministic Atlas or EBI responses in the worker process."""
    if url == providers.ATLAS_ENDPOINT:
        assert method == "POST" and body == b"AC"
        return Path(os.environ["E3_TEST_PROVIDER_PDB"]).read_bytes()
    if url == providers.INTERPRO_ENDPOINT + "/run":
        assert method == "POST"
        form = parse_qs(body.decode())
        assert form["email"] == ["researcher@example.org"]
        assert form["sequence"] == [">plant_fixture\nAC\n"]
        return b"iprscan5-fixture"
    if url == providers.INTERPRO_ENDPOINT + "/status/iprscan5-fixture":
        return b"FINISHED"
    if url == providers.INTERPRO_ENDPOINT + "/result/iprscan5-fixture/tsv":
        return b""
    raise AssertionError("Unexpected provider fixture request")


providers.http_request = fixture_request
'''


def test_app_host_worker_validates_required_tools_and_alignment_size(tmp_path):
    """Missing tools or an oversized unsampled selection leave the queue untouched."""
    config = ResearchConfig(
        workspace=tmp_path, mafft=str(tmp_path / "missing-mafft"),
        fasttree=str(tmp_path / "missing-fasttree"),
    )
    with pytest.raises(ResearchError, match="MAFFT is unavailable"):
        submit_local_alignment(config=config, parameters={}, fasta=FASTA)
    config = replace(config, mafft=sys.executable)
    with pytest.raises(ResearchError, match="FastTree is unavailable"):
        submit_local_alignment(config=config, parameters={"infer_tree": True}, fasta=FASTA)
    with pytest.raises(ResearchError, match="Alignment size"):
        submit_local_alignment(
            config=replace(config, max_alignment_sequences=2), parameters={}, fasta=FASTA,
        )
    assert list_jobs(workspace=tmp_path) == []


def test_app_host_launch_failure_is_saved(tmp_path, monkeypatch):
    """A failed process launch records a terminal failure for the frozen request."""
    config = ResearchConfig(workspace=tmp_path, mafft=sys.executable)
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=OSError("cannot launch")))
    with pytest.raises(ResearchError, match="Could not start local alignment worker"):
        submit_local_alignment(config=config, parameters={"infer_tree": False}, fasta=FASTA)
    (job,) = list_jobs(workspace=tmp_path)
    assert job["status"] == "FAILED" and "cannot launch" in job["error"]


@pytest.mark.parametrize("returncode", [0, 1])
def test_worker_exit_marks_unclaimed_job_failed(tmp_path, returncode):
    """Report a worker that exits before claiming its request, even with a zero exit code."""
    job_id = submit_job(
        workspace=tmp_path, operation="align", parameters={"execution_target": "app_host"},
    )
    process = Mock()
    process.wait.return_value = returncode
    _wait_for_worker(process=process, config=ResearchConfig(workspace=tmp_path), job_id=job_id)
    job = get_job(workspace=tmp_path, job_id=job_id)
    assert job["status"] == "FAILED" and "local_worker.log" in job["error"]


def test_general_worker_respects_app_host_reservation(tmp_path):
    """A polling worker leaves the app-host request for its exact one-shot worker."""
    local_id = submit_job(
        workspace=tmp_path, operation="align", parameters={"execution_target": "app_host"},
    )
    general_id = submit_job(workspace=tmp_path, operation="align", parameters={})
    assert claim_job(workspace=tmp_path)["job_id"] == general_id
    assert claim_job(workspace=tmp_path) is None
    assert claim_job(workspace=tmp_path, job_id=local_id)["job_id"] == local_id
    fail_queued_job(workspace=tmp_path, job_id=local_id, error="late launch diagnostic")
    assert get_job(workspace=tmp_path, job_id=local_id)["status"] == "RUNNING"


@pytest.mark.parametrize(
    ("operation", "parameters"),
    (
        ("predict", {"engine": "atlas", "remote_allowed": 1}),
        ("predict", {"engine": "local", "remote_allowed": True}),
        ("annotate", {"engine": "interpro_remote", "remote_allowed": False}),
        ("annotate", {"engine": "eggnog", "remote_allowed": True}),
    ),
)
def test_app_host_provider_requires_a_consented_external_request(
    *, tmp_path, operation, parameters,
):
    """New and saved app-host launches enforce the selected external route and consent."""
    config = ResearchConfig(workspace=tmp_path)
    job_id = submit_job(
        workspace=config.workspace, operation=operation, parameters=parameters, fasta=FASTA,
    )
    assert not queued_external_provider_job(workspace=config.workspace, job_id=job_id)
    with pytest.raises(ResearchError, match="sequence submission"):
        submit_local_provider_job(
            config=config, operation=operation, parameters=parameters, fasta=FASTA,
        )
    with pytest.raises(ResearchError, match="sequence-submission consent"):
        start_queued_provider_job(config=config, job_id=job_id)
    assert [job["status"] for job in list_jobs(workspace=config.workspace)] == ["QUEUED"]


@pytest.mark.parametrize("operation", ("predict", "annotate"))
def test_app_host_provider_process_completes_the_exact_request(
    *, tmp_path, model_pdb, monkeypatch, operation,
):
    """Run the real one-shot process with offline HTTP fixtures and the app profile."""
    config = ResearchConfig(workspace=tmp_path / "workspace")
    profile = tmp_path / "research.toml"
    profile.write_text(
        f"workspace={json.dumps(str(config.workspace))}\n", encoding="utf-8",
    )
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    stub = tmp_path / "provider_fixture"
    stub.mkdir()
    (stub / "sitecustomize.py").write_text(PROVIDER_STUB, encoding="utf-8")
    model = stub / "fixture.pdb"
    model.write_text(model_pdb, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(stub), prepend=os.pathsep)
    monkeypatch.setenv("E3_TEST_PROVIDER_PDB", str(model))
    fasta = ">plant_fixture\nAC\n"
    if operation == "predict":
        job_id = submit_local_provider_job(
            config=config, operation=operation,
            parameters={"engine": "atlas", "remote_allowed": True}, fasta=fasta,
        )
        expected = "predictions.tsv"
    else:
        job_id = submit_job(
            workspace=config.workspace, operation=operation,
            parameters={"engine": "interpro_remote", "remote_allowed": True},
            fasta=fasta, interproscan_email="researcher@example.org",
        )
        start_queued_provider_job(config=config, job_id=job_id)
        expected = "annotations.tsv"
    deadline = time.monotonic() + 20
    job = get_job(workspace=config.workspace, job_id=job_id)
    while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(0.1)
        job = get_job(workspace=config.workspace, job_id=job_id)
    log = job_directory(workspace=config.workspace, job_id=job_id) / "local_worker.log"
    assert job["status"] == "COMPLETE", (job, log.read_text(encoding="utf-8"))
    assert artifact_path(workspace=config.workspace, job_id=job_id, artifact=expected).is_file()
    with pytest.raises(ResearchError, match="queued external request"):
        start_queued_provider_job(config=config, job_id=job_id)
    assert len(list_jobs(workspace=config.workspace)) == 1
