"""Upstream centroid contracts and selected-export workflows without a global database."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from streamlit.testing.v1 import AppTest

from e3app.research.catalogue import open_catalogue, resolve_sequence_ids, sequence_aliases
from e3app.research.cli import main
from e3app.research.common import ResearchConfig, ResearchError, iter_fasta
from e3app.research.deepclust_exchange import centroid_list, import_cluster
from e3app.research.jobs import artifact_path, get_job, job_directory, list_jobs, submit_job
from e3app.research.runner import run_next_job


@pytest.fixture
def exported_cluster(tmp_path):
    """Create the exact ID layout emitted by upstream per-cluster extraction mode."""
    source = tmp_path / "NR_UGC79169.1.fa"
    source.write_text(
        ">NR_UGC79169.1\nacde*\n>UNIPROT_P12345\nACDF\n>AGNOSTOS_member_1\nACD\n",
        encoding="utf-8",
    )
    return source


def test_centroid_file_preserves_namespace_case_versions_and_order():
    """A centroid list never turns an accession or a local HOG into a guessed global ID."""
    identifiers = ["NR_UGC79169.1", "UNIPROT_P12345", "AGNOSTOS_a_+_1", "NR_UGC79169.1"]
    assert centroid_list(identifiers=identifiers) == (
        "NR_UGC79169.1\nUNIPROT_P12345\nAGNOSTOS_a_+_1\n"
    )
    assert centroid_list(identifiers=["NR_x.1", "nr_x.1"]) == "NR_x.1\nnr_x.1\n"
    for value in ([], "NR_X", ["x"] * 1001, [None], [" x"], ["x y"], [""], ["x\x00y"]):
        with pytest.raises(ResearchError):
            centroid_list(identifiers=value)
    for value in ("x\x00y", "x\x1fy", "x\x7fy"):
        with pytest.raises(ResearchError):
            sequence_aliases(identifier=value)


def test_official_sequence_map_column_names_and_nr_prefix(research_config, tmp_path):
    """The documented SEQID/CLUSTERID schema joins exactly, retaining accession versions."""
    source = tmp_path / "SeqIdMapClustId.parquet"
    pq.write_table(
        table=pa.table({"SEQID": ["NR_UGC79169.1"], "CLUSTERID": ["GLOBAL_A"]}), where=source
    )
    with open_catalogue(config=replace(research_config, sequence_map=str(source))) as connection:
        frame = resolve_sequence_ids(
            connection=connection,
            identifiers=["UGC79169.1", "NR_UGC79169.1", "UGC79169"],
            prefixes=("NR_",),
        ).set_index(keys="input_id")
    assert frame.loc["UGC79169.1", "matched_alias"] == "NR_UGC79169.1"
    assert frame.loc["NR_UGC79169.1", "mapping_status"] == "EXACT_ID"
    assert frame.loc["UGC79169", "mapping_status"] == "UNMATCHED"


@pytest.mark.parametrize("expected", [None, 3])
def test_import_audits_subset_without_global_sources(exported_cluster, tmp_path, expected):
    """An export retains exact membership, normalised sequences and honest count evidence."""
    output = tmp_path / "output"
    output.mkdir()
    result = import_cluster(
        config=ResearchConfig(workspace=tmp_path / "workspace"),
        source=exported_cluster,
        output=output,
        cluster_id="NR_UGC79169.1",
        source_label="Selected release export",
        expected_members=expected,
    )
    assert dict(iter_fasta(path=result["cluster.fasta"])) == {
        "NR_UGC79169.1": "ACDE",
        "UNIPROT_P12345": "ACDF",
        "AGNOSTOS_member_1": "ACD",
    }
    audit = pd.read_csv(filepath_or_buffer=result["clusters.tsv"], sep="\t").iloc[0]
    assert audit["imported_members"] == 3
    assert audit["input_sha256"] == hashlib.sha256(exported_cluster.read_bytes()).hexdigest()
    assert audit["count_status"] == (
        "COUNT_NOT_SUPPLIED" if expected is None else "MATCHES_SUPPLIED_COUNT"
    )
    members = pd.read_csv(filepath_or_buffer=result["members.tsv"], sep="\t")
    assert members["sequence_length"].tolist() == [3, 4, 4]
    assert members.loc[members.sequence_id == "NR_UGC79169.1", "sequence_sha256"].iloc[0] == (
        hashlib.sha256(b"ACDE").hexdigest()
    )
    summary = pd.read_csv(filepath_or_buffer=result["cluster_summary.tsv"], sep="\t").iloc[0]
    assert summary["minimum_length"] == 3 and summary["maximum_length"] == 4
    assert summary["mean_length"] == pytest.approx(11 / 3)
    assert summary["scope"] == "IMPORTED_EXPORT_ONLY"
    with pytest.raises(ResearchError, match="overwrite"):
        import_cluster(
            config=ResearchConfig(),
            source=exported_cluster,
            output=output,
            cluster_id="NR_UGC79169.1",
            source_label="Export",
        )


@pytest.mark.parametrize(
    "change, message",
    [
        ({"cluster_id": "UGC79169.1"}, "centroid"),
        ({"expected_members": 4}, "count differs"),
        ({"expected_members": 0}, "Expected members"),
        ({"expected_members": True}, "Expected members"),
        ({"source_label": ""}, "source label"),
        ({"source_label": "release\tunknown"}, "source label"),
    ],
)
def test_import_rejects_mismatched_export_contracts(exported_cluster, tmp_path, change, message):
    """Malformed provenance, wrong source namespaces and incomplete exports fail visibly."""
    output = tmp_path / "output"
    output.mkdir()
    controls = {"cluster_id": "NR_UGC79169.1", "source_label": "Export", **change}
    with pytest.raises(ResearchError, match=message):
        import_cluster(config=ResearchConfig(), source=exported_cluster, output=output, **controls)
    assert not (output / "cluster.fasta").exists()


@pytest.mark.parametrize(
    "content,maximum,message",
    [
        (">NR_X\nACD\n>NR_X\nACD\n", 10, "Duplicate"),
        (">1_NR_X\nACD\n", 10, "centroid"),
        (">NR_X\nACD\n>B\nACD\n", 1, "sequence bound"),
        (">NR_X\nAC*D\n", 10, "invalid residues"),
        ("", 10, "no records"),
    ],
)
def test_import_never_truncates_or_guesses_modified_headers(tmp_path, content, maximum, message):
    """Combined upstream output is rejected because its headers are deliberately renamed."""
    source = tmp_path / "export.fa"
    source.write_text(content, encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ResearchError, match=message):
        import_cluster(
            config=ResearchConfig(max_sequences=maximum),
            source=source,
            output=output,
            cluster_id="NR_X",
            source_label="Export",
        )


def test_large_file_queue_is_a_private_checksummed_snapshot(tmp_path):
    """Large exports bypass only the web size limit and cannot change with their source."""
    source = tmp_path / "large.fa"
    source.write_text(">NR_X\n" + "A" * 20_000_001 + "\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    job = submit_job(
        workspace=workspace, operation="import_cluster", parameters={}, fasta_path=source
    )
    directory = job_directory(workspace=workspace, job_id=job)
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("changed", encoding="utf-8")
    assert request["input_sha256"] == original
    assert hashlib.sha256((directory / "input.fasta").read_bytes()).hexdigest() == original
    with pytest.raises(ResearchError, match="not both"):
        submit_job(
            workspace=workspace,
            operation="import_cluster",
            parameters={},
            fasta=">a\nACD",
            fasta_path=source,
        )
    with pytest.raises(ResearchError, match="does not exist"):
        submit_job(
            workspace=workspace,
            operation="import_cluster",
            parameters={},
            fasta_path=tmp_path / "missing.fa",
        )


def test_cli_import_to_analysis_handoff_without_deepclust(exported_cluster, tmp_path, monkeypatch):
    """A real queued import supplies a verified FASTA to a subsequent family job."""
    profile = tmp_path / "research.toml"
    workspace = tmp_path / "workspace"
    profile.write_text(f'workspace="{workspace}"\n', encoding="utf-8")
    args = ["--config", str(profile)]
    assert (
        main(
            argv=[
                *args,
                "import-deepclust",
                "--fasta",
                str(exported_cluster),
                "--cluster-id",
                "NR_UGC79169.1",
                "--source-label",
                "Release export",
                "--expected-members",
                "3",
            ]
        )
        == 0
    )
    job = list_jobs(workspace=workspace)[0]["job_id"]
    assert main(argv=[*args, "worker", "--once", "--job-id", job]) == 0
    assert get_job(workspace=workspace, job_id=job)["status"] == "COMPLETE"
    directory = job_directory(workspace=workspace, job_id=job)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_sources"] == {}
    fasta = artifact_path(workspace=workspace, job_id=job, artifact="cluster.fasta")
    from e3app.research import runner

    def fake_alignment(*, config, source, output, parameters, membership):
        assert source == fasta
        assert len(dict(iter_fasta(path=source))) == 3
        result = output / "alignment.fa"
        result.write_bytes(source.read_bytes())
        return {result.name: result}

    monkeypatch.setattr(runner, "align_family", fake_alignment)
    alignment = submit_job(
        workspace=workspace,
        operation="align",
        parameters={"source_job": job, "source_artifact": "cluster.fasta"},
    )
    run_next_job(config=ResearchConfig(workspace=workspace), job_id=alignment)
    assert get_job(workspace=workspace, job_id=alignment)["status"] == "COMPLETE"


def test_import_page_defaults_to_selected_export_without_database(
    exported_cluster, tmp_path, monkeypatch
):
    """A user without the global catalogue sees the supported import route and can submit it."""
    from e3app.research import ui

    profile = tmp_path / "profile.toml"
    workspace = tmp_path / "workspace"
    profile.write_text(f'workspace="{workspace}"\n', encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setattr(
        ui.st,
        "file_uploader",
        lambda *args, **kwargs: SimpleNamespace(
            size=exported_cluster.stat().st_size, getvalue=exported_cluster.read_bytes
        ),
    )
    app = AppTest.from_file(
        str(Path(ui.__file__).with_name("standalone.py")), default_timeout=10
    ).run()
    assert not app.exception
    app.radio(key="research_section").set_value("Discover").run()
    assert app.radio[1].value == "Import extracted cluster"
    next(item for item in app.text_input if item.label == "Exact DeepClust centroid ID").set_value(
        "NR_UGC79169.1"
    )
    next(
        item for item in app.text_input if item.label == "Export source / database release"
    ).set_value("Release export")
    next(item for item in app.button if item.label == "Queue cluster import").click().run()
    assert not app.exception and app.success
    job = list_jobs(workspace=workspace)[0]["job_id"]
    run_next_job(config=ResearchConfig(workspace=workspace), job_id=job)
    assert get_job(workspace=workspace, job_id=job)["status"] == "COMPLETE"


@pytest.mark.parametrize(
    "case,message",
    [
        ("missing_file", "Select a per-cluster"),
        ("missing_source", "Supply the export source"),
        ("missing_centroid", "Sequence identifiers"),
        ("large", "exceeds 20 MB"),
        ("encoding", "UTF-8"),
    ],
)
def test_import_form_reports_invalid_inputs_before_queueing(tmp_path, monkeypatch, case, message):
    """A malformed browser submission gives a recoverable diagnostic without creating work."""
    from e3app.research import ui

    workspace = tmp_path / "workspace"
    profile = tmp_path / "profile.toml"
    profile.write_text(f'workspace="{workspace}"\n', encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    uploaded = (
        None
        if case == "missing_file"
        else SimpleNamespace(
            size=20_000_001 if case == "large" else 12,
            getvalue=lambda: b"\xff" if case == "encoding" else b">NR_X\nACD\n",
        )
    )
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: uploaded)
    app = AppTest.from_file(
        str(Path(ui.__file__).with_name("standalone.py")), default_timeout=10
    ).run()
    app.radio(key="research_section").set_value("Discover").run()
    next(item for item in app.text_input if item.label == "Exact DeepClust centroid ID").set_value(
        "" if case == "missing_centroid" else "NR_X"
    )
    next(
        item for item in app.text_input if item.label == "Export source / database release"
    ).set_value("" if case == "missing_source" else "Release export")
    next(item for item in app.button if item.label == "Queue cluster import").click().run()
    assert not app.exception
    assert any(message in item.value for item in app.error)
    assert list_jobs(workspace=workspace) == []
