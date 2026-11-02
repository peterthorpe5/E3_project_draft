"""Scientific comparison denominators, species trees and coordinate provenance checks."""

from dataclasses import replace
from io import StringIO
import json

from Bio import Phylo
import duckdb
import numpy as np
import pandas as pd
import pytest

from e3app.research import comparisons, feature_catalogue, species_tree, taxonomy
from e3app.research.common import ResearchError
from e3app.research.jobs import artifact_path, get_job, submit_job
from e3app.research.runner import run_next_job


def species_rows():
    """Create overlapping taxa with an explicitly unclassified family."""
    return pd.DataFrame([
        ('A', 'Human', '9606', 5), ('A', 'Plant', '3702', 2),
        ('A', 'UNCLASSIFIED', '', 3), ('B', 'Human', '9606', 1),
        ('B', 'Fly', '7227', 2), ('C', 'Plant', '3702', 4),
        ('D', 'UNCLASSIFIED', '', 6),
    ], columns=['cluster_id', 'species', 'taxon_id', 'member_count'])


def test_pairwise_identity_uses_known_aligned_residues():
    """Gaps and X never create identity or a comparable-residue denominator."""
    result = comparisons.alignment_comparison(records={'a': 'ACDX-', 'b': 'ACEXA', 'c': 'ACDXA'})
    assert result.similarity.loc['a', 'b'] == pytest.approx(2 / 3)
    assert result.denominators.loc['a', 'b'] == 3
    assert result.similarity.loc['a', 'c'] == 1
    assert result.denominators.loc['b', 'c'] == 4
    assert result.similarity.loc['b', 'c'] == .75
    assert np.allclose(result.similarity, result.similarity.T)
    assert set(result.order) == {'a', 'b', 'c'}
    assert len(result.linkage_matrix) == 2
    single = comparisons.alignment_comparison(records={'a': 'AX'})
    assert single.hierarchy_status == 'AT_LEAST_TWO_ROWS_REQUIRED'
    unknown = comparisons.alignment_comparison(records={'a': 'X-A', 'b': 'AX-'})
    assert np.isnan(unknown.similarity.loc['a', 'b'])
    assert unknown.denominators.loc['a', 'b'] == 0
    assert unknown.hierarchy_status == 'UNDEFINED_PAIRS_NO_HIERARCHY'


@pytest.mark.parametrize('records', [{}, {'a': 'AC', 'b': 'A'}, {'a': 'AB?'}])
def test_pairwise_rejects_invalid_alignments(records):
    """Non-aligned or invalid protein input never yields a numerical heatmap."""
    with pytest.raises(ResearchError):
        comparisons.alignment_comparison(records=records)


def test_comparison_dimension_limits(monkeypatch):
    """Large matrix requests fail explicitly instead of silently sampling."""
    monkeypatch.setattr(comparisons, 'MAX_COMPARISON_ROWS', 1)
    with pytest.raises(ResearchError, match='Select 1'):
        comparisons.alignment_comparison(records={'a': 'AA', 'b': 'AA'})
    monkeypatch.setattr(comparisons, 'MAX_COMPARISON_CELLS', 1)
    with pytest.raises(ResearchError, match='cell bound'):
        comparisons.alignment_comparison(records={'a': 'AA'})
    with pytest.raises(ResearchError, match='at most'):
        comparisons.species_comparison(rows=species_rows())


def test_taxon_jaccard_venn_and_unknown_coverage():
    """Unique species, not abundance or unknown labels, determine overlap."""
    rows = species_rows()
    matrix, coverage = comparisons.species_comparison(rows=rows)
    assert matrix.similarity.loc['A', 'B'] == pytest.approx(1 / 3)
    assert matrix.denominators.loc['A', 'B'] == 3
    assert np.isnan(matrix.similarity.loc['D', 'A'])
    assert matrix.hierarchy_status == 'UNDEFINED_PAIRS_NO_HIERARCHY'
    assert coverage.set_index('cluster_id').loc['A', 'classification_fraction'] == .7
    assert coverage.set_index('cluster_id').loc['D', 'unclassified_members'] == 6
    assert comparisons.venn_regions(rows=rows, cluster_ids=['A', 'B']) == {
        '01': 1, '10': 1, '11': 1,
    }
    regions = comparisons.venn_regions(rows=rows, cluster_ids=['A', 'B', 'C'])
    assert regions['110'] == 1 and regions['101'] == 1 and regions['010'] == 1
    assert sum(regions.values()) == 3
    with pytest.raises(ResearchError, match='reviewed'):
        comparisons.venn_regions(rows=rows, cluster_ids=['A', 'D'])
    with pytest.raises(ResearchError, match='distinct'):
        comparisons.venn_regions(rows=rows, cluster_ids=['A', 'A'])
    for bad in (pd.DataFrame(), rows.assign(member_count=-1), rows.assign(member_count=1.5)):
        with pytest.raises(ResearchError):
            comparisons.species_comparison(rows=bad)


def test_species_backbone_keeps_all_proteins_and_reviewed_mapping():
    """Extra species are pruned; same-species proteins form an explicit display polytomy."""
    result, audit = species_tree.species_display_tree(
        newick='((9606:1,3702:2):1,7227:1);', sequence_ids=['human1', 'human2', 'plant'],
        metadata={'human1': {'species': 'Human', 'taxon_id': 9606},
                  'human2': {'species': 'Human', 'taxon_id': 9606},
                  'plant': {'species': 'Plant', 'taxon_id': 3702}},
    )
    tree = Phylo.read(StringIO(result), 'newick')
    assert {tip.name for tip in tree.get_terminals()} == {'human1', 'human2', 'plant'}
    human = next(tree.find_clades(name='species_9606'))
    assert {tip.name for tip in human.clades} == {'human1', 'human2'}
    assert all(tip.branch_length == 0 for tip in human.clades)
    assert len(audit) == 3
    assert 'display only' in audit[0]['interpretation']


@pytest.mark.parametrize(('newick', 'metadata', 'message'), [
    ('(Human:1,Human:2);', {'species': 'Human'}, 'unique'),
    ('(Human:-1,Plant:1);', {'species': 'Human'}, 'non-negative'),
    ('(Human:1,Plant:1);', {}, 'one exact'),
    ('(Human:1,9606:1);', {'species': 'Human', 'taxon_id': 9606}, 'one exact'),
    ('(Human:1,Plant:1)', {'species': 'Human'}, 'complete'),
    ('((Human:1,Plant:1);', {'species': 'Human'}, 'parse'),
])
def test_species_backbone_rejects_unsupported_evidence(newick, metadata, message):
    """Species identities and topology are never guessed from protein IDs."""
    with pytest.raises(ResearchError, match=message):
        species_tree.species_display_tree(newick=newick, sequence_ids=[
                                          'a'], metadata={'a': metadata})
    with pytest.raises(ResearchError, match='unique'):
        species_tree.species_display_tree(newick=newick, sequence_ids=[], metadata={})


def feature_rows():
    """Provide exact historical feature coordinates without a sequence checksum."""
    return pd.DataFrame([{'member_accession': 'P1', 'primary_group_id': 'H1',
                          'species_column': 'Human', 'protein_length': 100,
                          'location_start': 2, 'location_end': 30,
                          'entry_accession': 'IPR0001', 'entry_name': 'Domain'}])


def test_recorded_features_use_original_length_without_invented_sequence():
    """Published positions remain tied to the original annotation coordinate scope."""
    rows = feature_rows()
    with duckdb.connect() as connection:
        connection.register('input', rows)
        connection.execute('CREATE TABLE domain_hits AS SELECT * FROM input')
        exact = feature_catalogue.published_features(connection=connection, accession='P1')
        assert len(exact) == 1
        assert feature_catalogue.published_features(connection=connection, accession='P').empty
        payload = feature_catalogue.recorded_feature_payload(rows=exact)
    assert payload['sequence'] == '' and payload['length'] == 100
    assert payload['features'][0]['locations'][0]['fragments'] == [{'start': 2, 'end': 30}]
    assert 'not verified' in payload['coordinate_scope']
    with pytest.raises(ResearchError, match='exact'):
        feature_catalogue.recorded_feature_payload(rows=pd.concat([rows, rows.assign(
            member_accession='P2')]))
    for bad in (pd.DataFrame(), rows.assign(protein_length=None), rows.assign(location_end=101)):
        with pytest.raises(ResearchError):
            feature_catalogue.recorded_feature_payload(rows=bad)
    with duckdb.connect() as connection:
        with pytest.raises(ResearchError, match='domain_hits'):
            feature_catalogue.published_features(connection=connection, accession='P1')
        with pytest.raises(ResearchError, match='accession'):
            feature_catalogue.published_features(connection=connection, accession='bad\nid')


def test_retrieved_taxonomy_survives_remote_profile_and_subclustering(research_config, tmp_path):
    """Review status and exact metadata survive when the receiving host lacks the global TSV."""
    job = submit_job(workspace=research_config.workspace, operation='deepclust_retrieve',
                     parameters={'cluster_ids': ['GLOBAL_A', 'GLOBAL_B'],
                                 'transport': 'worker'})
    run_next_job(config=research_config, job_id=job)
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'COMPLETE'
    imported = replace(research_config, taxonomy='')
    source = tmp_path / 'selected.fasta'
    source.write_text('>UNIPROT_P1\nAAAA\n>B\nAAAA\n>D\nAAAA\n')
    metadata = taxonomy.reviewed_metadata(config=imported, source=source, source_job=job)
    assert set(metadata) == {'UNIPROT_P1', 'B'}
    membership = tmp_path / 'membership.tsv'
    membership.write_text('sequence_id\tsubcluster_id\nUNIPROT_P1\tsub1\nB\tsub1\nD\tsub2\n')
    paths = taxonomy.subcluster_species(config=imported, source=source, source_job=job,
                                        membership=membership, output=tmp_path)
    rows = pd.read_csv(paths['cluster_species.tsv'], sep='\t', keep_default_na=False)
    assert rows.member_count.sum() == 3
    assert rows.loc[rows.cluster_id.eq('sub2'), 'species'].tolist() == ['UNCLASSIFIED']
    assert taxonomy.reviewed_metadata(config=imported, source=source) == {}
    assert taxonomy.subcluster_species(config=imported, source=source, source_job='',
                                       membership=membership, output=tmp_path) == {}
    with pytest.raises(ResearchError, match='max_sequences'):
        taxonomy.reviewed_metadata(config=replace(imported, max_sequences=1), source=source)


def test_species_comparison_worker_publishes_complete_artifacts(research_config):
    """Queued species comparison uses complete source artifacts and publishes denominators."""
    retrieval = submit_job(workspace=research_config.workspace, operation='deepclust_retrieve',
                           parameters={'cluster_ids': ['GLOBAL_A', 'GLOBAL_B'],
                                       'transport': 'worker'})
    run_next_job(config=research_config, job_id=retrieval)
    job = submit_job(workspace=research_config.workspace, operation='compare', parameters={
        'kind': 'species', 'source_job': retrieval, 'cluster_ids': ['GLOBAL_A', 'GLOBAL_B'],
    })
    run_next_job(config=research_config, job_id=job)
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'COMPLETE'
    summary = json.loads(artifact_path(workspace=research_config.workspace, job_id=job,
                                       artifact='comparison_summary.json').read_text())
    assert summary['venn_regions'] == {'01': 0, '10': 1, '11': 1}
    assert summary['hierarchy_status'] == 'AVERAGE_LINKAGE_1_MINUS_SIMILARITY'
    frame = pd.read_csv(artifact_path(workspace=research_config.workspace, job_id=job,
                                      artifact='denominators.tsv'), sep='\t', index_col=0)
    assert frame.loc['GLOBAL_A', 'GLOBAL_B'] == 2


def test_alignment_comparison_worker_keeps_selection_and_rejects_missing_ids(
    research_config, monkeypatch,
):
    """A comparison reads a checksummed completed alignment and keeps exact selected rows."""
    from e3app.research import runner

    def alignment(**kwargs):
        artifacts = {}
        for name in ('alignment.fasta', 'sequences.fasta'):
            path = kwargs['output'] / name
            path.write_text('>a\nACDE\n>b\nACDF\n>c\nAAAA\n')
            artifacts[name] = path
        return artifacts

    monkeypatch.setattr(runner, 'align_family', alignment)
    source = submit_job(workspace=research_config.workspace, operation='align', parameters={},
                        fasta='>a\nACDE\n>b\nACDF\n>c\nAAAA\n')
    run_next_job(config=research_config, job_id=source)
    job = submit_job(workspace=research_config.workspace, operation='compare', parameters={
        'kind': 'alignment', 'source_job': source, 'sequence_ids': ['a', 'b'],
    })
    run_next_job(config=research_config, job_id=job)
    assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'COMPLETE'
    matrix = pd.read_csv(artifact_path(workspace=research_config.workspace, job_id=job,
                                       artifact='similarity.tsv'), sep='\t', index_col=0)
    assert list(matrix) == ['a', 'b'] and matrix.loc['a', 'b'] == .75
    for kind, ids in [('alignment', ['missing']), ('alignment', []),
                      ('alignment', ['a', 'a']), ('bad', ['a']), ('species', ['absent'])]:
        job = submit_job(workspace=research_config.workspace, operation='compare', parameters={
            'kind': kind, 'source_job': source,
            'sequence_ids' if kind == 'alignment' else 'cluster_ids': ids,
        })
        run_next_job(config=research_config, job_id=job)
        assert get_job(workspace=research_config.workspace, job_id=job)['status'] == 'FAILED'
