"""App navigation, independent workers and named command integration."""

import io
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pocket_workbench import cli, jobs, ui
from pocket_workbench.core import (
    ComparisonSettings,
    WorkbenchError,
    write_json,
)


@pytest.mark.parametrize(
    "page",
    [
        "Start / import",
        "Models & pockets",
        "Input quality",
        "Compare structures",
        "Alignment & trees",
        "Jobs",
        "Methods & glossary",
        "Downloads",
    ],
)
def test_all_app_pages_render_without_exceptions(project, monkeypatch, tmp_path, page):
    """Every navigation route renders against an actual typed demo resource."""
    monkeypatch.setenv("POCKET_WORKBENCH_RESOURCE", str(project))
    monkeypatch.setenv("POCKET_WORKBENCH_WORKSPACE", str(tmp_path / "workspace"))
    app = AppTest.from_file(str(Path(ui.__file__)), default_timeout=20).run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception
    assert not app.error, [element.value for element in app.error]
    if page == "Compare structures":
        assert app.get("iframe")
    if page == "Methods & glossary":
        assert any("Searchable glossary" in str(element) for element in app.tabs)


def test_empty_app_has_guided_import_and_help(monkeypatch, tmp_path):
    """The app explains its inputs before a resource is selected."""
    monkeypatch.delenv("POCKET_WORKBENCH_RESOURCE", raising=False)
    monkeypatch.setenv("POCKET_WORKBENCH_WORKSPACE", str(tmp_path / "workspace"))
    app = AppTest.from_file(str(Path(ui.__file__))).run()
    assert not app.exception
    assert any("Which files" in item.label for item in app.expander)


def test_uploaded_bytes_use_safe_filenames_and_tsv():
    """Uploaded bytes and browser table exports preserve the intended data."""
    assert ui.tsv_bytes(rows=[{"a": 1, "b": 2}]).startswith(b"a\tb\n")


def test_upload_stream_helper_rejects_duplicate_names(tmp_path):
    """A second upload cannot silently overwrite the first input."""
    value = io.BytesIO(b"model bytes")
    value.name = "model.cif"
    path = ui.upload_file(uploaded=value, directory=tmp_path)
    assert path.read_bytes() == b"model bytes"
    with pytest.raises(WorkbenchError):
        ui.upload_file(uploaded=value, directory=tmp_path)


def test_background_request_is_saved_before_worker_launch(project, monkeypatch):
    """Detached launch uses argv and preserves a request/status/log boundary."""
    calls = []
    monkeypatch.setattr(
        jobs.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    identifier = jobs.start_job(
        root=project,
        task="compare",
        options={
            "pairs": [["synthetic_reference", "synthetic_mobile"]],
            "settings": asdict(ComparisonSettings(engine="sequence_kabsch")),
        },
    )
    request = project / "jobs" / identifier / "request.json"
    assert request.is_file()
    assert calls[0][1]["start_new_session"] is True
    assert jobs.run_job(request_path=request) == 0
    assert (
        json.loads(request.with_name("status.json").read_text())["status"] == "complete"
    )


def test_failed_worker_keeps_error_and_terminal_status(project):
    """A failed task retains its actionable reason instead of staying running."""
    directory = project / "jobs" / "job_test"
    request = directory / "request.json"
    write_json(
        path=request,
        value={
            "job_id": "job_test",
            "root": str(project),
            "task": "invalid",
            "options": {},
        },
    )
    assert jobs.run_job(request_path=request) == 1
    status = json.loads((directory / "status.json").read_text())
    assert status["status"] == "failed"
    assert "Unknown" in status["error"]


def test_active_worker_prevents_second_project_mutation(project):
    """Queued jobs block competing project mutation tasks."""
    write_json(path=project / "jobs/job_old/status.json", value={"status": "queued"})
    with pytest.raises(WorkbenchError, match="active"):
        jobs.start_job(root=project, task="compare", options={})


def test_named_cli_commands_export_and_reject_invalid_inputs(project, tmp_path):
    """The CLI produces exports and rejects missing/incompatible selections."""
    assert (
        cli.main(
            [
                "export",
                "--resource",
                str(project),
                "--output",
                str(tmp_path / "exported"),
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "pack",
                "--resource",
                str(project),
                "--output",
                str(tmp_path / "packed.zip"),
            ]
        )
        == 0
    )
    assert cli.main(["compare", "--resource", str(project)]) == 1
    assert cli.main(["app", "--resource", str(project), "--port", "0"]) == 1
    assert (
        cli.main(
            [
                "compare",
                "--resource",
                str(project),
                "--reference",
                "synthetic_reference",
                "--mobile",
                "synthetic_mobile",
                "--engine",
                "sequence_kabsch",
            ]
        )
        == 0
    )


def test_cli_launch_uses_selected_resource_and_workspace(
    project, tmp_path, monkeypatch
):
    """App launch keeps paths as separate arguments and binds locally by default."""
    calls = []
    monkeypatch.setattr(
        cli.subprocess,
        "call",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )
    assert (
        cli.main(
            ["app", "--resource", str(project), "--workspace", str(tmp_path / "space")]
        )
        == 0
    )
    arguments, options = calls[0]
    assert "127.0.0.1" in arguments[0]
    assert options["env"]["POCKET_WORKBENCH_RESOURCE"] == str(project)
