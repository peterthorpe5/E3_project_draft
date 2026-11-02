"""Dedicated campaign, comparison, shared feature and species-tree UI behaviour."""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from e3app.research import ui
from e3app.research.jobs import get_job, list_jobs
from e3app.research.runner import run_next_job

from test_campaign_remote import e3_connection


def control(*, items, label):
    """Find an explicit visible control without relying on widget position."""
    return next(item for item in items if item.label == label)


def campaign_app(*, tmp_path, config, monkeypatch, title='DeepClust workbench'):
    """Create an E3-backed UI with the same entry point as the main application."""
    source = tmp_path / 'e3.duckdb'
    with e3_connection(path=str(source)):
        pass
    profile = tmp_path / 'research.toml'
    profile.write_text('\n'.join(
        f'{key}={json.dumps(str(getattr(config, key)))}'
        for key in ('workspace', 'index', 'sequences', 'sequence_map', 'taxonomy')
    ))
    monkeypatch.setenv('E3_RESEARCH_CONFIG', str(profile))
    script = (
        'import duckdb\nfrom e3app.research.ui import render_research_workbench\n'
        f'connection=duckdb.connect({str(source)!r},read_only=True)\n'
        'render_research_workbench(connection=connection, '
        f'initial_section="Top-200 cluster campaign",title={title!r})\n'
    )
    return AppTest.from_string(script, default_timeout=30).run()


def test_top200_ui_maps_retrieves_and_compares(research_config, tmp_path, monkeypatch):
    """User clicks queue real fixture jobs; opening pages never runs external work."""
    app = campaign_app(tmp_path=tmp_path, config=research_config, monkeypatch=monkeypatch)
    assert not app.exception and not app.error
    assert app.radio(key='research_section').value == 'Top-200 cluster campaign'
    assert app.number_input(key='campaign_top_n').value == 200
    assert list_jobs(workspace=research_config.workspace) == []
    control(items=app.button, label='Prepare complete Top-N E3 mapping inputs').click().run()
    assert not app.exception and not app.error
    assert len(app.get('download_button')) == 2
    assert list_jobs(workspace=research_config.workspace) == []
    control(items=app.button,
            label='Queue Top-N mapping through the command-line connection').click().run()
    mapping = list_jobs(workspace=research_config.workspace)[0]['job_id']
    run_next_job(config=research_config, job_id=mapping)
    app.run()
    assert not app.exception and not app.error
    assert app.multiselect(key='campaign_collect_ids').options == ['GLOBAL_A', 'GLOBAL_B']
    app.multiselect(key='campaign_collect_ids').set_value(['GLOBAL_A', 'GLOBAL_B']).run()
    control(items=app.button, label='Queue complete selected cluster retrieval').click().run()
    retrieval = list_jobs(workspace=research_config.workspace)[0]['job_id']
    run_next_job(config=research_config, job_id=retrieval)
    assert get_job(workspace=research_config.workspace, job_id=retrieval)['status'] == 'COMPLETE'
    app.radio(key='research_section').set_value('Cluster comparisons').run()
    assert not app.exception and not app.error
    assert len(app.get('plotly_chart')) == 1
    control(items=app.button, label='Queue species overlap and hierarchical heatmap').click().run()
    comparison = list_jobs(workspace=research_config.workspace)[0]['job_id']
    run_next_job(config=research_config, job_id=comparison)
    app.run()
    assert not app.exception and not app.error
    assert len(app.get('plotly_chart')) == 4
    app.radio(key='research_section').set_value('Family analysis').run()
    assert not app.exception and not app.error
    assert any('Collect selected clusters' in option or 'command-line' in option
               for option in app.selectbox(key='analyse_source').options)


def test_campaign_preparation_invalidates_when_top_n_changes(
    research_config, tmp_path, monkeypatch,
):
    """Prepared complete inputs cannot accidentally be queued for a different selection."""
    app = campaign_app(tmp_path=tmp_path, config=research_config, monkeypatch=monkeypatch)
    control(items=app.button, label='Prepare complete Top-N E3 mapping inputs').click().run()
    app.number_input(key='campaign_top_n').set_value(1).run()
    assert not any('Queue Top-N mapping' in item.label for item in app.button)
    assert list_jobs(workspace=research_config.workspace) == []


def test_feature_surface_exposes_nightingale_annotation_and_esmfold(
    research_config, tmp_path, monkeypatch,
):
    """Normal E3 features use original coordinates; arbitrary sequences use shared job forms."""
    app = campaign_app(tmp_path=tmp_path, config=research_config, monkeypatch=monkeypatch)
    app.radio(key='research_section').set_value('Protein features').run()
    assert 'Recorded E3 domain features' in app.radio(key='feature_browser_route').options
    assert not app.exception and not app.error
    app.radio(key='feature_browser_route').set_value(
        'InterProScan / eggNOG for selected sequences').run()
    assert app.selectbox(key='annotation_engine').options
    app.radio(key='annotate_route').set_value('Paste FASTA').run()
    assert any('FASTA' in item.label for item in app.text_area)
    app.radio(key='feature_browser_route').set_value('ESMFold for selected sequences').run()
    assert not app.exception and not app.error
    assert app.selectbox(key='fold_engine').options[0].startswith('ESM Atlas')
    assert list_jobs(workspace=research_config.workspace) == []
