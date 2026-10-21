"""Viewer escaping, source adapters and lazy generic Streamlit integration tests."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from e3app.research.common import ResearchError
from e3app.research.e3_adapter import select_e3_cluster_inputs, select_e3_inputs
from e3app.research.jobs import artifact_path, submit_job
from e3app.research.runner import run_next_job
from e3app.research.ui import completed_manifests, read_table, split_identifiers
from e3app.research.viewers import (
    auspice_dataset_url,
    json_for_html,
    nightingale_features,
    viewer_asset,
    viewer_document,
)


def test_viewers_escape_script_content_and_ship_real_libraries():
    """Viewer documents use checksummed local bundles and inert escaped input data."""
    encoded = json_for_html(value={"x": "</script><script>alert(1)</script>&"})
    assert "</script>" not in encoded and json.loads(encoded)["x"].startswith("</script>")
    for name in ("alignment", "jbrowse", "nightingale"):
        document = viewer_document(
            viewer=name, payload={"msa": ">a\nACD", "sequence": "ACD", "features": []}
        )
        assert "https://unpkg.com" not in document and 'id="protein-data"' in document
        assert len(document) > 100_000
    assert "ReactMSAView" in viewer_asset(name="jbrowse.js")
    for name in ("../escape.js", "missing.js"):
        with pytest.raises(ResearchError):
            viewer_asset(name=name)
    with pytest.raises(ResearchError):
        viewer_document(viewer="bad", payload={})
    assert auspice_dataset_url(base_url="http://localhost:4000/proxy", job_id="a" * 32).endswith(
        "/" + "a" * 32 + "?m=div"
    )
    for url in ("javascript:alert(1)", "https://user:pass@host", "https://host/?token=secret"):
        with pytest.raises(ResearchError):
            auspice_dataset_url(base_url=url, job_id="a" * 32)


def test_nightingale_coordinates_require_exact_sequence_version():
    """Domains from another isoform cannot be silently overlaid on a model."""
    row = {
        "sequence_id": "a",
        "sequence_sha256": hashlib.sha256(b"ACDE").hexdigest(),
        "signature_accession": "PF1",
        "start": "1",
        "end": "3",
    }
    features = nightingale_features(
        sequence_id="a", sequence="ACDE", annotations=[row, {"sequence_id": "b"}]
    )
    assert features[0]["locations"][0]["fragments"][0] == {"start": 1, "end": 3}
    for changed in (
        {**row, "end": "5"},
        {**row, "start": "bad"},
        {**row, "sequence_sha256": "different"},
    ):
        with pytest.raises(ResearchError):
            nightingale_features(sequence_id="a", sequence="ACDE", annotations=[changed])
    assert (
        nightingale_features(
            sequence_id="a",
            sequence="ACDE",
            annotations=[{"sequence_id": "a", "description": "eggNOG whole-protein evidence"}],
        )
        == []
    )


def test_e3_hog_and_discovery_adapters_keep_source_context():
    """E3 selectors produce original accessions and seeds, never guessed global IDs."""
    with duckdb.connect() as connection:
        connection.execute(
            (
                "CREATE TABLE hierarchical_membership(group_id VARCHAR, raw_identifier "
                "VARCHAR, parsed_accession VARCHAR)"
            )
        )
        connection.execute(
            (
                "INSERT INTO hierarchical_membership VALUES "
                "('HOG1','sp|P1|HUMAN','P1'),('HOG2','LOCAL2',NULL)"
            )
        )
        assert select_e3_inputs(connection=connection, group_ids=("HOG1",)).input_id.tolist() == [
            "P1"
        ]
        with pytest.raises(ResearchError):
            select_e3_inputs(connection=connection, group_ids=("MISSING",))
        connection.execute(
            ("CREATE TABLE candidate_master_results(cluster_id " "VARCHAR,computational_rank INT)")
        )
        connection.execute(
            "INSERT INTO candidate_master_results VALUES ('LOCAL_A',1),('LOCAL_B',2)"
        )
        connection.execute(
            (
                "CREATE TABLE candidate_evidence(representative_id "
                "VARCHAR,representative_original_id VARCHAR,matched_seed_ids_calculated "
                "VARCHAR)"
            )
        )
        connection.execute(
            (
                "INSERT INTO candidate_evidence VALUES "
                "('LOCAL_A','original_A','P1;P2'),('LOCAL_B','original_B','P3')"
            )
        )
        selected = select_e3_cluster_inputs(connection=connection, maximum_clusters=1)
        assert set(selected.input_id) == {"original_A", "P1", "P2"}
        assert "LOCAL_A" not in selected.input_id.tolist()
        assert set(selected.source_cluster_id) == {"LOCAL_A"}
        explicit = select_e3_cluster_inputs(connection=connection, cluster_ids=("LOCAL_B",))
        assert set(explicit.input_id) == {"original_B", "P3"}
        assert explicit.source_rank.isna().all()
        with pytest.raises(ResearchError, match="silently omitted"):
            select_e3_cluster_inputs(connection=connection, cluster_ids=("UNKNOWN",))
    with duckdb.connect() as connection:
        with pytest.raises(ResearchError):
            select_e3_inputs(connection=connection, group_ids=("HOG1",))
        with pytest.raises(ResearchError):
            select_e3_cluster_inputs(connection=connection)


def test_ui_helpers_and_corrupt_manifest(research_config):
    """UI metadata stays bounded and literal NA identifiers remain identifiers."""
    assert split_identifiers(value="a,b; a\nNA") == ["a", "b", "NA"]
    job = submit_job(
        workspace=research_config.workspace,
        operation="retrieve",
        parameters={"cluster_ids": ["GLOBAL_A"]},
    )
    run_next_job(config=research_config, job_id=job)
    manifests = completed_manifests(config=research_config, operation="retrieve")
    assert (
        job in manifests and completed_manifests(config=research_config, operation="predict") == {}
    )
    path = artifact_path(workspace=research_config.workspace, job_id=job, artifact="clusters.tsv")
    assert len(read_table(path=path, maximum_rows=1)) == 1
    manifest_path = research_config.workspace / "jobs" / job / "manifest.json"
    manifest_path.write_text("bad")
    with pytest.raises(ResearchError, match="manifest"):
        completed_manifests(config=research_config)


def test_generic_app_all_empty_sections_and_real_queue(research_config, tmp_path, monkeypatch):
    """Every generic page renders without E3 data and explicit clicks submit work."""
    config = tmp_path / "profile.toml"
    config.write_text(f'workspace="{research_config.workspace}"\nindex="{research_config.index}"\n')
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(config))
    from e3app.research import ui

    app = AppTest.from_file(
        str(Path(ui.__file__).with_name("standalone.py")), default_timeout=10
    ).run()
    assert not app.exception
    for section in (
        "Family analysis",
        "Alignments and trees",
        "Models",
        "Annotations",
        "Jobs",
        "Discover",
    ):
        app.radio[0].set_value(section).run()
        assert not app.exception
    app.text_area[1].set_value("GLOBAL_A").run()
    next(
        button for button in app.button if button.label == "Queue complete cluster retrieval"
    ).click().run()
    assert app.success and not app.exception
    app.radio[0].set_value("Jobs").run()
    assert not app.exception and len(app.dataframe) >= 1


def test_ranked_e3_seed_context_and_missing_schemas(monkeypatch):
    """Top-N HOG selection preserves inherited seeds and refuses incomplete source schemas."""
    from e3app.research import e3_adapter
    import pandas as pd

    ranking = pd.DataFrame(
        {"primary_group_id": ["HOG1", "HOG2"], "matched_seed_ids_calculated": ["P1;P2", None]}
    )
    monkeypatch.setattr(e3_adapter, "collect_prestructure_ranked_hogs", lambda **kwargs: ranking)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE hierarchical_membership(group_id VARCHAR,raw_identifier VARCHAR,"
            "record_type VARCHAR)"
        )
        connection.execute("INSERT INTO hierarchical_membership VALUES ('HOG1','raw1','root_hog')")
        selected = select_e3_inputs(connection=connection)
        assert set(selected.input_id) == {"raw1", "P1", "P2"}
        with pytest.raises(ResearchError):
            select_e3_inputs(connection=connection, group_ids=tuple(str(i) for i in range(1001)))
        connection.execute("DROP TABLE hierarchical_membership")
        connection.execute("CREATE TABLE hierarchical_membership(unrelated VARCHAR)")
        with pytest.raises(ResearchError, match="group_id"):
            select_e3_inputs(connection=connection)
        connection.execute("CREATE TABLE candidate_master_results(unrelated VARCHAR)")
        with pytest.raises(ResearchError):
            select_e3_cluster_inputs(connection=connection)
        with pytest.raises(ResearchError, match="candidate_evidence"):
            select_e3_cluster_inputs(connection=connection, cluster_ids=("A",))
        connection.execute("CREATE TABLE candidate_evidence(unrelated VARCHAR)")
        with pytest.raises(ResearchError, match="representative_id"):
            select_e3_cluster_inputs(connection=connection, cluster_ids=("A",))


def test_smoke_document_generator_is_reproducible(tmp_path):
    """The shipped developer script creates all three offline synthetic documents."""
    import runpy

    script = Path(__file__).parents[2] / "scripts" / "build_viewer_smoke.py"
    main = runpy.run_path(str(script))["main"]
    assert main(argv=["--output", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.glob("*.html")) == [
        "alignment.html",
        "jbrowse.html",
        "nightingale.html",
    ]


def test_populated_result_pages_render_downloads_and_real_components(
    research_config, model_pdb, tmp_path, monkeypatch
):
    """Completed jobs drive alignment, model, feature and artifact result interfaces."""
    from unittest.mock import Mock
    from e3app.research import analysis, providers, ui

    config = research_config
    profile = tmp_path / "ui.toml"
    profile.write_text(f'workspace="{config.workspace}"\n')
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))

    def command(*, arguments, output, config, stdout=None):
        """Return deterministic scientific tool outputs without running a provider."""
        if "--version" in arguments:
            stdout.write_text("version\n")
        elif "--auto" in arguments:
            stdout.write_text(Path(arguments[-1]).read_text())
        else:
            stdout.write_text("(p:0.1,b:0.2,c:0.3);\n")

    monkeypatch.setattr(analysis, "run_command", command)
    alignment = submit_job(
        workspace=config.workspace,
        operation="align",
        parameters={},
        fasta=">p\nAC\n>b\nAD\n>c\nAE\n",
    )
    run_next_job(config=config, job_id=alignment)
    monkeypatch.setattr(providers, "http_request", Mock(return_value=model_pdb.encode()))
    prediction = submit_job(
        workspace=config.workspace,
        operation="predict",
        parameters={"engine": "atlas", "remote_allowed": True},
        fasta=">p\nAC\n",
    )
    run_next_job(config=config, job_id=prediction)

    def remote(*, sequences, output, config, remote_allowed):
        """Return a standard exact-sequence positional InterPro fixture."""
        import hashlib

        path = output / "interpro.raw.tsv"
        md5 = hashlib.md5(b"AC", usedforsecurity=False).hexdigest()
        path.write_text(f"p\t{md5}\t2\tPfam\tPF1\tDomain\t1\t2\t1e-9\tT\tdate\n")
        return path

    monkeypatch.setattr(providers, "remote_interpro", remote)
    annotation = submit_job(
        workspace=config.workspace,
        operation="annotate",
        parameters={"engine": "interpro_remote", "remote_allowed": True},
        fasta=">p\nAC\n",
    )
    run_next_job(config=config, job_id=annotation)
    assert all(
        manifest["operation"] in {"align", "predict", "annotate"}
        for manifest in completed_manifests(config=config).values()
    )
    app = AppTest.from_file(
        str(Path(ui.__file__).with_name("standalone.py")), default_timeout=15
    ).run()
    for section in ("Alignments and trees", "Models", "Annotations", "Jobs", "Family analysis"):
        app.radio[0].set_value(section).run()
        assert not app.exception and not app.error
        if section == "Alignments and trees":
            for view in ("Alignment Viewer 2", "Statistics", "Auspice tree", "JBrowse MSA"):
                app.radio[1].set_value(view).run()
                assert not app.exception and not app.error
        if section == "Models":
            next(
                item for item in app.selectbox if item.label == "Optional annotation overlay"
            ).set_value(annotation).run()
            assert not app.exception and not app.error
        if section == "Jobs":
            next(
                item for item in app.button if item.label == "Prepare verified download"
            ).click().run()
            assert not app.exception and not app.error


def test_e3_launcher_accepts_and_forwards_generic_profile(resource_db, tmp_path, monkeypatch):
    """The E3 launcher accepts and forwards a generic research profile."""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from e3app import cli as app_cli

    profile = tmp_path / "profile.toml"
    profile.write_text(f'workspace="{tmp_path / "research"}"\n')
    arguments = ["--resource-duckdb", str(resource_db), "--research-config", str(profile)]
    assert app_cli.main([*arguments, "--validate-only"]) == 0
    callback = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(app_cli.subprocess, "run", callback)
    assert app_cli.main(arguments) == 0
    assert callback.call_args.kwargs["env"]["E3_RESEARCH_CONFIG"] == str(profile)
    profile.write_text("invalid_option=true")
    assert app_cli.main(arguments) == 2


def test_e3_bounded_complete_inputs_and_explicit_seed_selection(monkeypatch):
    """Explicit HOGs retain ranked seed links and oversized selections are rejected intact."""
    import pandas as pd
    from e3app.research import e3_adapter

    ranking = pd.DataFrame(
        {"primary_group_id": ["HOG1", "HOG2"], "matched_seed_ids_calculated": [";P1;none", None]}
    )
    monkeypatch.setattr(e3_adapter, "collect_prestructure_ranked_hogs", lambda **kwargs: ranking)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE hierarchical_membership(group_id VARCHAR,raw_identifier VARCHAR)"
        )
        connection.execute("INSERT INTO hierarchical_membership VALUES ('HOG1','raw1')")
        selected = select_e3_inputs(connection=connection, group_ids=("HOG1",))
        assert set(selected.input_id) == {"raw1", "P1"}
        connection.execute(
            "INSERT INTO hierarchical_membership SELECT 'HOG1','p_' || i FROM range(10001) t(i)"
        )
        with pytest.raises(ResearchError, match="10000"):
            select_e3_inputs(connection=connection, group_ids=("HOG1",))
        connection.execute(
            "CREATE TABLE candidate_evidence(representative_id VARCHAR,"
            "representative_original_id VARCHAR,matched_seed_ids_calculated VARCHAR)"
        )
        connection.execute("INSERT INTO candidate_evidence VALUES ('A',NULL,';none')")
        with pytest.raises(ResearchError, match="non-empty"):
            select_e3_cluster_inputs(connection=connection, cluster_ids=("A",))
