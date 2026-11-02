"""Complete E3 campaign selection and request-bound mounted/SSH protocol tests."""

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import duckdb
import pandas as pd
import pytest

from e3app.research import campaign, cli, remote
from e3app.research.common import ResearchError, iter_fasta
from e3app.research.jobs import artifact_path, get_job, job_directory
from e3app.research.runner import run_next_job


def e3_connection(*, members=3, path=':memory:'):
    """Build a ranked HOG, orthogroup fallback and unresolved primary group."""
    connection = duckdb.connect(path)
    connection.execute(
        "CREATE TABLE final_evolutionary_candidate_prioritisation AS SELECT * FROM "
        "(VALUES ('HIERARCHICAL_ORTHOGROUP','H1',1,'multi;P1'),"
        "('ORTHOGROUP','O1',2,'small'),('HIERARCHICAL_ORTHOGROUP','EMPTY',3,NULL)) "
        "v(primary_group_type,primary_group_id,prestructure_evolutionary_group_rank,"
        "candidate_accessions)"
    )
    connection.execute(
        "CREATE TABLE hierarchical_membership AS SELECT 'H1' AS group_id,"
        "CASE WHEN i=0 THEN 'P1' WHEN i=1 THEN 'unknown' ELSE 'x'||i::VARCHAR END "
        "AS raw_identifier,'Human' AS species,'root_hog' AS record_type "
        "FROM range(?) v(i)", [members],
    )
    connection.execute(
        "CREATE TABLE orthogroup_membership AS SELECT 'O1' AS group_id,'C' AS raw_identifier"
    )
    return connection


def test_campaign_keeps_complete_context_and_missing_groups(research_config):
    """A real queue worker retains all groups, multiple matches and unknown IDs."""
    with e3_connection() as connection:
        selected = campaign.select_campaign(connection=connection)
    assert selected.groups.source_group_id.tolist() == ['H1', 'O1', 'EMPTY']
    assert set(selected.inputs.input_id) == {'P1', 'unknown', 'x2', 'multi', 'C', 'small'}
    job = campaign.submit_campaign(config=research_config, selection=selected, transport='worker')
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'QUEUED'
    run_next_job(config=research_config, job_id=job)
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'COMPLETE'
    groups = pd.read_csv(artifact_path(workspace=research_config.workspace, job_id=job,
                                       artifact='campaign_groups.tsv'), sep='\t')
    assert groups.mapping_status.tolist() == ['PARTIAL', 'MAPPED', 'NO_IDENTIFIERS']
    assert groups.global_cluster_count.tolist() == [2, 2, 0]
    clusters = pd.read_csv(artifact_path(workspace=research_config.workspace, job_id=job,
                                         artifact='global_clusters.tsv'), sep='\t')
    assert clusters.cluster_id.tolist() == ['GLOBAL_A', 'GLOBAL_B', 'UNINDEXED']
    assert clusters.retrievable.tolist() == [True, True, False]
    mapping = pd.read_csv(artifact_path(workspace=research_config.workspace, job_id=job,
                                        artifact='global_cluster_mapping.tsv'), sep='\t')
    assert len(mapping.loc[mapping.input_id.eq('multi')]) == 2
    assert set(mapping.source_group_id) == {'H1', 'O1'}


def test_campaign_expands_beyond_preview_and_batches(research_config, monkeypatch, tmp_path):
    """Complete >10k membership is split into protocol batches, never a preview prefix."""
    with e3_connection(members=10003) as connection:
        selection = campaign.select_campaign(connection=connection, maximum_groups=1)
    assert len(selection.inputs) == 10005
    calls = []

    def respond(*, config, request, output, transport):
        calls.append(request['identifiers'])
        output.mkdir(parents=True)
        path = output / 'global_cluster_mapping.tsv'
        pd.DataFrame({'input_id': request['identifiers'], 'cluster_id': '', 'member_count': '',
                      'mapping_status': 'UNMATCHED'}).to_csv(path, sep='\t', index=False)
        return {path.name: path}

    monkeypatch.setattr(campaign, 'exchange', respond)
    job = campaign.submit_campaign(config=research_config, selection=selection, transport='ssh')
    run_next_job(config=research_config, job_id=job)
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'COMPLETE'
    assert [len(values) for values in calls] == [10000, 4]
    assert 'x10002' in set().union(*map(set, calls))


def test_campaign_contracts_and_snapshot_integrity(research_config):
    """Incomplete or modified inventories fail instead of changing the requested science."""
    with duckdb.connect() as connection:
        with pytest.raises(ResearchError, match='published'):
            campaign.select_campaign(connection=connection)
    with e3_connection() as connection:
        connection.execute('UPDATE final_evolutionary_candidate_prioritisation SET '
                           'prestructure_evolutionary_group_rank=1')
        with pytest.raises(ResearchError, match='unique'):
            campaign.select_campaign(connection=connection)
    with e3_connection() as connection:
        selected = campaign.select_campaign(connection=connection)
    with pytest.raises(ResearchError, match='connection'):
        campaign.submit_campaign(config=research_config, selection=selected, transport='http')
    job = campaign.submit_campaign(config=research_config, selection=selected, transport='worker')
    request = json.loads((job_directory(workspace=research_config.workspace, job_id=job)
                          / 'request.json').read_text())
    (research_config.workspace / request['parameters']['inputs_manifest']).write_text('altered')
    run_next_job(config=research_config, job_id=job)
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'FAILED'


def test_checked_exchange_retrieves_only_selected_clusters(research_config, tmp_path):
    """Physical-rowgroup extraction carries all selected sequences and reviewed taxonomy."""
    artifacts = remote.exchange(config=research_config, transport='worker',
                                request={'operation': 'retrieve', 'cluster_ids': ['GLOBAL_A']},
                                output=tmp_path / 'received')
    fasta = next(path for name, path in artifacts.items() if name.endswith('.fasta'))
    assert set(dict(iter_fasta(path=fasta))) == {'UNIPROT_P1', 'B', 'UNIPROT_P2'}
    assert 'member_taxonomy.tsv' in artifacts
    metadata = pd.read_csv(artifacts['member_taxonomy.tsv'], sep='\t')
    assert set(metadata.loc[metadata.taxon_id.notna(), 'sequence_id']) == {'UNIPROT_P1', 'B'}
    assert not list((research_config.workspace / 'exchange').iterdir())


@pytest.mark.parametrize('payload', [
    {}, {'operation': 'delete', 'cluster_ids': ['A']},
    {'operation': 'resolve', 'identifiers': []},
    {'operation': 'resolve', 'identifiers': ['a\nb']},
    {'operation': 'resolve', 'identifiers': [2]},
    {'operation': 'retrieve', 'cluster_ids': ['A'], 'path': '/etc'},
])
def test_protocol_rejects_invalid_requests(payload):
    """Only bounded exact read-only requests can cross the SSH connection."""
    with pytest.raises(ResearchError):
        remote.request_bytes(request=payload)


def response_fixture(*, config, tmp_path):
    """Return a genuine resolver response and its request."""
    request = {'operation': 'resolve', 'identifiers': ['P1', 'multi', 'unknown']}
    stream = BytesIO()
    remote.write_response(config=config, request=request, destination=stream)
    path = tmp_path / 'response.zip'
    path.write_bytes(stream.getvalue())
    return request, path


@pytest.mark.parametrize('fault', ['checksum', 'size', 'request', 'protocol', 'inventory', 'path'])
def test_response_rejects_corruption_before_publication(research_config, tmp_path, fault):
    """All inventory entries are checked before any FASTA/table can be published."""
    request, source = response_fixture(config=research_config, tmp_path=tmp_path)
    with ZipFile(source) as archive:
        values = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(values[remote.MANIFEST_NAME])
    if fault == 'checksum':
        metadata['artifacts'][0]['sha256'] = '0' * 64
    elif fault == 'size':
        metadata['artifacts'][0]['size_bytes'] += 1
    elif fault == 'request':
        metadata['request_sha256'] = '0' * 64
    elif fault == 'protocol':
        metadata['protocol_version'] = 0
    elif fault == 'inventory':
        metadata['artifacts'] = []
    else:
        values['../escape.fasta'] = b'>bad\nAAAA\n'
    values[remote.MANIFEST_NAME] = json.dumps(metadata).encode()
    with ZipFile(source, 'w') as archive:
        for name, content in values.items():
            archive.writestr(name, content)
    target = tmp_path / 'invalid'
    with pytest.raises(ResearchError):
        remote.read_response(config=research_config, request=request, source=source, output=target)
    assert not target.exists() or not list(target.iterdir())


def test_response_limits_and_existing_result(research_config, tmp_path):
    """Byte limits and existing outputs prevent uncontrolled transfer and replacement."""
    request, path = response_fixture(config=research_config, tmp_path=tmp_path)
    with pytest.raises(ResearchError, match='transfer_max_bytes'):
        remote.read_response(config=replace(research_config, transfer_max_bytes=1), request=request,
                             source=path, output=tmp_path / 'small')
    with pytest.raises(ResearchError, match='transfer_max_bytes'):
        remote.write_response(config=replace(research_config, transfer_max_bytes=1),
                              request=request,
                              destination=BytesIO())
    target = tmp_path / 'exists'
    target.mkdir()
    (target / 'global_cluster_mapping.tsv').write_text('keep')
    with pytest.raises(ResearchError, match='replace'):
        remote.read_response(config=research_config, request=request, source=path, output=target)
    assert (target / 'global_cluster_mapping.tsv').read_text() == 'keep'


def test_ssh_uses_operator_alias_quoted_command_and_stdin(research_config, monkeypatch, tmp_path):
    """Identifiers never become shell operands and the local process uses argv."""
    config = replace(research_config, remote_host='denbi-existing',
                     remote_executable='/installed path/protein-research-workbench',
                     remote_config='/profile with spaces/research.toml')
    request, response = response_fixture(config=config, tmp_path=tmp_path)

    def run(**kwargs):
        assert kwargs['args'][6] == 'denbi-existing'
        assert "'/installed path/protein-research-workbench'" in kwargs['args'][7]
        assert 'P1' not in kwargs['args'][7]
        assert json.loads(kwargs['input']) == request
        kwargs['stdout'].write(response.read_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(remote.subprocess, 'run', run)
    results = remote.exchange(config=config, request=request,
                              transport='ssh', output=tmp_path / 'ssh')
    assert 'deepclust_ssh.log' in results
    for invalid in ('-proxy', 'host;uname', 'user@host extra', ''):
        with pytest.raises(ResearchError, match='SSH alias'):
            remote.ssh_command(config=replace(config, remote_host=invalid))
    with pytest.raises(ResearchError, match='profile'):
        remote.ssh_command(config=replace(config, remote_config=''))


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'missing', 'transport'])
def test_exchange_failure_diagnostics(research_config, tmp_path, monkeypatch, failure):
    """Connection failures remain explicit job errors and retain separate diagnostics."""
    config = replace(research_config, remote_host='denbi', remote_config='/research.toml')

    def failed(**kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(cmd='ssh', timeout=1)
        if failure == 'missing':
            raise FileNotFoundError('ssh')
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(remote.subprocess, 'run', failed)
    with pytest.raises(ResearchError):
        remote.exchange(config=config, request={'operation': 'resolve', 'identifiers': ['P1']},
                        output=tmp_path / 'failed',
                        transport='bad' if failure == 'transport' else 'ssh')


def test_cli_binary_channel_is_usable(research_config, monkeypatch, capsys):
    """CLI stdout is a genuine ZIP; progress logging never corrupts the data channel."""
    request = {'operation': 'resolve', 'identifiers': ['P1']}
    output = BytesIO()
    monkeypatch.setattr(cli, 'load_config', lambda **_: research_config)
    monkeypatch.setattr(cli.sys, 'stdin', SimpleNamespace(
        buffer=BytesIO(json.dumps(request).encode())))
    monkeypatch.setattr(cli.sys, 'stdout', SimpleNamespace(buffer=output))
    assert cli.main(argv=['export-deepclust', '--request-stdin']) == 0
    with ZipFile(BytesIO(output.getvalue())) as archive:
        assert remote.MANIFEST_NAME in archive.namelist()


@pytest.mark.parametrize(('change', 'message'), [
    ('DELETE FROM final_evolutionary_candidate_prioritisation', 'no ranked'),
    ("UPDATE final_evolutionary_candidate_prioritisation SET primary_group_type='UNKNOWN'",
     'unsupported'),
    ('DROP TABLE hierarchical_membership', 'requires hierarchical'),
    ('ALTER TABLE hierarchical_membership DROP raw_identifier', 'exact group'),
])
def test_campaign_fails_closed_on_incomplete_published_contracts(change, message):
    """Unsupported/missing membership cannot become an apparently complete Top-N export."""
    with e3_connection() as connection:
        connection.execute(change)
        with pytest.raises(ResearchError, match=message):
            campaign.select_campaign(connection=connection)


def test_campaign_rejects_truncation_and_tampered_existing_snapshots(
    research_config, monkeypatch,
):
    """Complete-size bounds and content-addressed source snapshots are enforced."""
    with e3_connection() as connection:
        selection = campaign.select_campaign(connection=connection)
        monkeypatch.setattr(campaign, 'MAX_INPUT_ROWS', 1)
        with pytest.raises(ResearchError, match='200000'):
            campaign.select_campaign(connection=connection)
    monkeypatch.setattr(campaign, 'MAX_INPUT_ROWS', 200000)
    job = campaign.submit_campaign(config=research_config, selection=selection, transport='worker')
    record = json.loads((job_directory(workspace=research_config.workspace, job_id=job)
                         / 'request.json').read_text())
    (research_config.workspace / record['parameters']['groups_manifest']).write_text('changed')
    with pytest.raises(ResearchError, match='Existing campaign'):
        campaign.submit_campaign(config=research_config, selection=selection, transport='worker')
    monkeypatch.setattr(campaign, 'MAX_MANIFEST_BYTES', 1)
    with pytest.raises(ResearchError, match='50 MB'):
        campaign.submit_campaign(config=research_config, selection=selection, transport='worker')
