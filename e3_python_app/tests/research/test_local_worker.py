"""App-host worker prerequisites, failure reporting and queue isolation."""

from dataclasses import replace
import subprocess
import sys
from unittest.mock import Mock

import pytest

from e3app.research.common import ResearchConfig, ResearchError
from e3app.research.jobs import claim_job, fail_queued_job, get_job, list_jobs, submit_job
from e3app.research.local_worker import _wait_for_worker, submit_local_alignment

FASTA = ">a\nACD\n>b\nACE\n>c\nACF\n"


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
