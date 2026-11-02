"""Run a synthetic campaign through real DIAMOND, MAFFT and FastTree executables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from e3app.research.campaign import select_campaign, submit_campaign
from e3app.research.common import ResearchConfig, atomic_json, iter_fasta
from e3app.research.jobs import artifact_path, get_job, submit_job
from e3app.research.runner import run_next_job
from e3app.research.species_tree import species_display_tree


def main() -> int:
    """Execute a bounded synthetic scientific workflow without a live database or providers.

    Returns:
        Zero after all sequence, taxonomy, tree and comparison assertions pass.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--diamond', required=True)
    parser.add_argument('--mafft', required=True)
    parser.add_argument('--fasttree', required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    protein = 'M' + 'ACDEFGHIKLMNPQRSTVWY' * 5
    proteins = [protein, protein[:30] + 'W' + protein[31:], protein[:60] + 'A' + protein[61:]]
    identifiers = ['UNIPROT_P1', 'UNIPROT_P2', 'UNIPROT_P3']
    pq.write_table(pa.table({'f0': identifiers, 'f1': proteins, 'f2': ['GLOBAL_A'] * 3,
                             'f3': [0, 1, 2]}), root / 'sequences.parquet', row_group_size=2)
    pq.write_table(pa.table({'CLUSTER': ['GLOBAL_A'], 'NMEMBER': [3], 'RowStart': [0],
                             'RowGroup': ['0,1']}), root / 'index.parquet')
    pq.write_table(pa.table({'f0': identifiers, 'f1': ['GLOBAL_A'] * 3}), root / 'map.parquet')
    pd.DataFrame({'sequence_id': identifiers, 'species': ['Human', 'Plant', 'Fly'],
                  'taxon_id': [9606, 3702, 7227], 'mapping_status': 'REVIEWED'}).to_csv(
        root / 'taxonomy.tsv', sep='\t', index=False,
    )
    config = ResearchConfig(
        workspace=root / 'work', index=str(root / 'index.parquet'),
        sequences=str(root / 'sequences.parquet'), sequence_map=str(root / 'map.parquet'),
        taxonomy=str(root / 'taxonomy.tsv'), diamond=args.diamond, mafft=args.mafft,
        fasttree=args.fasttree, threads=1, memory_gb=1, command_timeout=120,
    )

    def complete(*, operation: str, parameters: dict) -> str:
        job = submit_job(workspace=config.workspace, operation=operation, parameters=parameters)
        run_next_job(config=config, job_id=job)
        state = get_job(workspace=config.workspace, job_id=job)
        if state['status'] != 'COMPLETE':
            raise RuntimeError(state)
        return job

    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE final_evolutionary_candidate_prioritisation AS SELECT "
            "'HIERARCHICAL_ORTHOGROUP' AS primary_group_type,'H1' AS primary_group_id,"
            "1 AS prestructure_evolutionary_group_rank"
        )
        frame = pd.DataFrame({'group_id': 'H1', 'raw_identifier': identifiers})
        connection.register('hierarchical_membership', frame)
        campaign = submit_campaign(config=config,
                                   selection=select_campaign(connection=connection),
                                   transport='worker')
    run_next_job(config=config, job_id=campaign)
    assert get_job(workspace=config.workspace, job_id=campaign)['status'] == 'COMPLETE'
    collected = complete(operation='deepclust_retrieve', parameters={
        'transport': 'worker', 'cluster_ids': ['GLOBAL_A'],
    })
    table = pd.read_csv(artifact_path(workspace=config.workspace, job_id=collected,
                                      artifact='clusters.tsv'), sep='\t')
    fasta = table.iloc[0]['fasta_artifact']
    families = []
    for identity in (70, 100):
        families.append(complete(operation='subcluster', parameters={
            'source_job': collected, 'source_artifact': fasta,
            'identity': identity, 'mutual_coverage': 90, 'evalue': 1e-5,
        }))
    strict = families[-1]
    members = pd.read_csv(artifact_path(workspace=config.workspace, job_id=strict,
                                        artifact='membership.tsv'), sep='\t')
    assert set(members.sequence_id) == set(identifiers)
    assert members.subcluster_id.nunique() == 3
    alignment = complete(operation='align', parameters={
        'source_job': strict, 'source_artifact': 'sequences.fasta', 'infer_tree': True,
    })
    records = dict(iter_fasta(path=artifact_path(workspace=config.workspace, job_id=alignment,
                                                 artifact='alignment.fasta'), aligned=True))
    assert set(records) == set(identifiers)
    assert all(value.replace('-', '') in proteins for value in records.values())
    complete(operation='compare', parameters={
        'kind': 'alignment', 'source_job': alignment, 'sequence_ids': identifiers,
    })
    complete(operation='compare', parameters={
        'kind': 'species', 'source_job': strict, 'cluster_ids': members.subcluster_id.tolist(),
    })
    metadata = pd.read_csv(artifact_path(workspace=config.workspace, job_id=alignment,
                                         artifact='member_taxonomy.tsv'), sep='\t')
    tree, mapping = species_display_tree(
        newick='((9606:1,3702:1):1,7227:2);', sequence_ids=list(records),
        metadata={row['sequence_id']: row for row in metadata.to_dict(orient='records')},
    )
    (root / 'reviewed_species_display.nwk').write_text(tree)
    pd.DataFrame(mapping).to_csv(root / 'species_mapping.tsv', sep='\t', index=False)
    atomic_json(path=root / 'validation.json', value={
        'status': 'PASS', 'synthetic_only': True, 'input_proteins': 3,
        'exact_100_percent_subclusters': 3, 'campaign_job': campaign,
        'retrieval_job': collected, 'subcluster_jobs': families, 'alignment_job': alignment,
        'alignment_and_species_comparisons': 'COMPLETE',
    })
    print(json.dumps({'status': 'PASS', 'output': str(root)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
