"""Validation, queue concurrency, integrity and workspace isolation contracts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

import pytest

from e3app.research.common import (
    ResearchError,
    atomic_json,
    bounded_number,
    file_sha256,
    iter_fasta,
    load_config,
    normalise_protein,
    safe_path,
    utc_now,
    write_tsv,
)
from e3app.research.jobs import (
    artifact_path,
    cancel_job,
    claim_job,
    finish_job,
    get_job,
    job_directory,
    list_jobs,
    submit_job,
)


def test_config_strict_types_paths_and_defaults(tmp_path, monkeypatch):
    """Profiles reject misspellings, malformed paths and mistyped text controls."""
    assert load_config().max_alignment_sequences == 5000
    path = tmp_path / "profile.toml"
    path.write_text(
        f'workspace="{tmp_path / "workspace"}"\nthreads=2\nidentifier_prefixes=["U_"]\n'
    )
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(path))
    config = load_config()
    assert config.threads == 2 and config.identifier_prefixes == ("U_",)
    assert config.workspace == tmp_path / "workspace"
    for text in (
        "unknwon=4",
        "diamond=2",
        "threads=true",
        "threads=1.1",
        "workspace=42",
        "identifier_prefixes=[1]",
        "broken=[",
        "threads=0",
    ):
        path.write_text(text)
        with pytest.raises(ResearchError):
            load_config(path=path)
    with pytest.raises(ResearchError):
        load_config(path=tmp_path / "missing")


@pytest.mark.parametrize("value", [True, None, "no", float("nan"), float("inf"), -1, 11, 1.1])
def test_numeric_validation_rejects_bad_controls(value):
    """Scientific controls are finite and integral when requested."""
    with pytest.raises(ResearchError):
        bounded_number(value=value, label="Count", minimum=0, maximum=10, integer=True)
    assert bounded_number(value="5", label="Count", minimum=0, maximum=10, integer=True) == 5


def test_atomic_files_paths_and_fasta(tmp_path):
    """Artifacts remain contained and inputs retain exact IDs and normalised residues."""
    path = tmp_path / "nested" / "data.json"
    atomic_json(path=path, value={"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert len(file_sha256(path=path)) == 64 and utc_now().endswith("+00:00")
    assert safe_path(root=tmp_path, relative="nested/data.json") == path
    for relative in ("../outside", str(tmp_path / "abs"), "."):
        with pytest.raises(ResearchError):
            safe_path(root=tmp_path, relative=relative)
    with pytest.raises(ValueError):
        atomic_json(path=path, value=float("nan"))
    assert normalise_protein(sequence=" ac d* ") == "ACD"
    assert normalise_protein(sequence="a.c-", aligned=True) == "A-C-"
    for sequence in ("", "AC*D", "123", "---"):
        with pytest.raises(ResearchError):
            normalise_protein(sequence=sequence)
    fasta = tmp_path / "p.fasta"
    fasta.write_text(">NA description\nacd*\n>b\nAAA\n")
    assert list(iter_fasta(path=fasta)) == [("NA", "ACD"), ("b", "AAA")]
    for content in ("ACD\n", ">\nACD\n", ">a\n>a\nACD"):
        fasta.write_text(content)
        with pytest.raises(ResearchError):
            list(iter_fasta(path=fasta))
    table = tmp_path / "data.tsv"
    write_tsv(path=table, rows=[{"id": "NA", "value": None}], columns=("id", "value"))
    assert table.read_text() == "id\tvalue\nNA\t\n"


def test_queue_transaction_claims_each_job_once(tmp_path):
    """Concurrent workers claim each task once and retain immutable request checksums."""
    ids = [
        submit_job(workspace=tmp_path, operation="align", parameters={"n": i}, fasta=">x\nACD\n")
        for i in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: claim_job(workspace=tmp_path), range(4)))
    assert {item["job_id"] for item in claimed} == set(ids)
    assert claim_job(workspace=tmp_path) is None
    for item in claimed:
        assert item["status"] == "RUNNING" and isinstance(item["parameters"]["n"], int)
        finish_job(workspace=tmp_path, job_id=item["job_id"])
    assert get_job(workspace=tmp_path, job_id=ids[0])["status"] == "COMPLETE"
    assert len(list_jobs(workspace=tmp_path)) == 4
    with pytest.raises(ResearchError):
        finish_job(workspace=tmp_path, job_id=ids[0])


def test_queue_cancellation_failure_and_integrity(tmp_path):
    """Only completed contained checksummed outputs can become downstream inputs."""
    job = submit_job(workspace=tmp_path, operation="retrieve", parameters={})
    cancel_job(workspace=tmp_path, job_id=job)
    assert get_job(workspace=tmp_path, job_id=job)["status"] == "CANCELLED"
    for action in (cancel_job, finish_job):
        with pytest.raises(ResearchError):
            action(workspace=tmp_path, job_id=job)
    with pytest.raises(ResearchError):
        artifact_path(workspace=tmp_path, job_id=job, artifact="x")
    job = submit_job(workspace=tmp_path, operation="align", parameters={})
    claim_job(workspace=tmp_path, job_id=job)
    directory = job_directory(workspace=tmp_path, job_id=job)
    path = directory / "out.fasta"
    path.write_text(">a\nACD\n")
    manifest = {"artifacts": {"out.fasta": {"path": "out.fasta", "sha256": file_sha256(path=path)}}}
    atomic_json(path=directory / "manifest.json", value=manifest)
    finish_job(workspace=tmp_path, job_id=job)
    assert artifact_path(workspace=tmp_path, job_id=job, artifact="out.fasta") == path
    with pytest.raises(ResearchError):
        artifact_path(workspace=tmp_path, job_id=job, artifact="missing")
    path.write_text("changed")
    with pytest.raises(ResearchError, match="checksum"):
        artifact_path(workspace=tmp_path, job_id=job, artifact="out.fasta")
    manifest["artifacts"]["out.fasta"]["path"] = "../../outside"
    atomic_json(path=directory / "manifest.json", value=manifest)
    with pytest.raises(ResearchError):
        artifact_path(workspace=tmp_path, job_id=job, artifact="out.fasta")
    failed = submit_job(workspace=tmp_path, operation="predict", parameters={})
    claim_job(workspace=tmp_path, job_id=failed)
    finish_job(workspace=tmp_path, job_id=failed, error="test failure")
    assert get_job(workspace=tmp_path, job_id=failed)["error"] == "test failure"
    for value in ("../escape", "x", "a" * 33):
        with pytest.raises(ResearchError):
            job_directory(workspace=tmp_path, job_id=value)
    with pytest.raises(ResearchError):
        get_job(workspace=tmp_path, job_id="a" * 32)
    with pytest.raises(ResearchError):
        submit_job(workspace=tmp_path, operation="bad", parameters={})
    with pytest.raises(ResearchError):
        submit_job(workspace=tmp_path, operation="align", parameters={}, fasta="x" * 20_000_001)
    with pytest.raises(ResearchError):
        list_jobs(workspace=tmp_path, limit=0)
