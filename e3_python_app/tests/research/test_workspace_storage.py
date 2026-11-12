"""Exercise the research scratch paths and explicitly previewed index cleanup."""

from datetime import datetime, timedelta, timezone
import os
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from e3app.research.common import (
    ResearchConfig, ResearchError, analysis_temporary_root, atomic_json,
)
from e3app.research.jobs import claim_job, finish_job, job_directory, submit_job
from e3app.research.workspace_storage import clear_job_intermediates, preview_job_cleanup


@pytest.fixture
def saved_index_job(*, tmp_path):
    """Provide a factory for jobs with real queue states and dated index fixtures."""
    workspace = tmp_path / "research"

    def create(*, status: str = "COMPLETE", days: int = 45, published: bool = False):
        """Create one job, an index and a manifest indicating retained artifacts."""
        job_id = submit_job(
            workspace=workspace, operation="align", parameters={}, fasta=">P1\nACDE\n",
        )
        directory = job_directory(workspace=workspace, job_id=job_id)
        index = directory / "input.sqlite"
        index.write_bytes(b"index fixture")
        if status != "QUEUED":
            claim_job(workspace=workspace, job_id=job_id)
        if status in {"COMPLETE", "FAILED"}:
            atomic_json(path=directory / "manifest.json", value={
                "schema_version": 1, "job_id": job_id,
                "artifacts": {"input index": {"path": index.name}} if published else {},
            })
            finish_job(
                workspace=workspace, job_id=job_id, error="failure" if status == "FAILED" else None,
            )
        moment = datetime.now(timezone.utc) - timedelta(days=days)
        with sqlite3.connect(database=workspace / "jobs.sqlite") as connection:
            connection.execute(
                "UPDATE jobs SET finished_at=? WHERE job_id=? AND finished_at IS NOT NULL",
                (moment.isoformat(), job_id),
            )
        os.utime(index, times=(moment.timestamp(), moment.timestamp()))
        return index

    return workspace, create


@pytest.mark.parametrize("tmpdir", [None, "", "worker_scratch"])
def test_scratch_paths_follow_worker_environment(*, tmpdir, tmp_path, monkeypatch):
    """An empty or absent TMPDIR uses the workspace, otherwise use that process setting."""
    config = ResearchConfig(workspace=tmp_path / "workspace")
    expected = config.workspace / "temporary"
    if tmpdir is None:
        monkeypatch.delenv("TMPDIR", raising=False)
    else:
        if tmpdir:
            expected = tmp_path / tmpdir
        monkeypatch.setenv("TMPDIR", str(expected) if tmpdir else "")
    assert analysis_temporary_root(config=config) == expected.resolve()


def test_preview_and_clear_only_old_unpublished_indexes(*, saved_index_job, tmp_path):
    """Keep live and young jobs, source FASTAs, shared files, logs and manifest entries."""
    workspace, create = saved_index_job
    disposable = create()
    logs = disposable.parent / "worker.log"
    logs.write_text("job log", encoding="utf-8")
    retained = [
        create(status="RUNNING"), create(status="QUEUED"), create(status="FAILED"),
        create(days=2), create(published=True),
        disposable.parent / "input.fasta", disposable.parent / "manifest.json", logs,
    ]
    outside = tmp_path / "unrelated.sqlite"
    outside.write_bytes(b"keep")
    linked = create()
    linked.unlink()
    linked.symlink_to(outside)
    retained.extend([linked, outside])
    hardlinked = create()
    hardlinked.unlink()
    hardlinked.hardlink_to(outside)
    retained.append(hardlinked)
    changed = create()
    corrupt = create()
    (corrupt.parent / "manifest.json").write_text("not a manifest", encoding="utf-8")
    retained.append(corrupt)

    preview = preview_job_cleanup(workspace=workspace, retention_days=30)
    assert {item.job_id for item in preview} == {disposable.parent.name, changed.parent.name}
    assert disposable.exists() and changed.exists()
    changed.write_bytes(b"replaced after preview")
    new_after_preview = create()
    removed = clear_job_intermediates(workspace=workspace, retention_days=30, preview=preview)
    assert [item.job_id for item in removed] == [disposable.parent.name]
    assert not disposable.exists()
    assert all(path.exists() for path in (*retained, changed, new_after_preview))
    assert clear_job_intermediates(workspace=workspace, retention_days=30, preview=preview) == ()
    assert (workspace / "jobs.sqlite").exists()


@pytest.mark.parametrize("days", [False, 0, 1.5, 10**15])
def test_cleanup_validates_retention(*, tmp_path, days):
    """Reject invalid ages before examining the queue."""
    with pytest.raises(ResearchError):
        preview_job_cleanup(workspace=tmp_path, retention_days=days)


def test_storage_panel_requires_preview_before_clear(*, saved_index_job, monkeypatch):
    """Use the actual Streamlit controls and show the current workspace and byte total."""
    workspace, create = saved_index_job
    index = create()
    monkeypatch.setenv("E3_STORAGE_TEST_WORKSPACE", str(workspace))
    app = AppTest.from_string(
        "from os import environ\n"
        "from pathlib import Path\n"
        "from e3app.research.common import ResearchConfig\n"
        "from e3app.research.ui import render_workspace_storage\n"
        "render_workspace_storage(config=ResearchConfig("
        "workspace=Path(environ['E3_STORAGE_TEST_WORKSPACE'])))\n"
    ).run()
    assert any(str(workspace / "jobs") in item.value for item in app.markdown)
    assert "research_clear_cleanup" not in {button.key for button in app.button}
    app.button(key="research_preview_cleanup").click().run()
    assert index.exists() and app.dataframe[0].value["Index"].tolist() == ["input.sqlite"]
    app.number_input(key="research_cleanup_days").set_value(90).run()
    assert "research_clear_cleanup" not in {button.key for button in app.button}
    app.number_input(key="research_cleanup_days").set_value(30).run()
    app.button(key="research_preview_cleanup").click().run()
    app.button(key="research_clear_cleanup").click().run()
    assert any("Cleared 1 index (" in item.value for item in app.success)
    assert not index.exists() and not app.exception and not app.error
