"""Exact global membership, official physical groups and reviewed taxonomy tests."""

from dataclasses import replace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from e3app.research.catalogue import (
    _column,
    _row_groups,
    browse_clusters,
    build_cluster_taxonomy,
    extract_clusters,
    open_catalogue,
    resolve_sequence_ids,
    sequence_aliases,
)
from e3app.research.common import ResearchError, iter_fasta


def test_aliases_are_explicit_and_mapping_retains_all_states(research_config):
    """No guessed orthology-to-global mapping or one-to-many match is discarded."""
    assert sequence_aliases(identifier="sp|P1|NAME", prefixes=("UNIPROT_",)) == (
        "sp|P1|NAME",
        "P1",
        "UNIPROT_sp|P1|NAME",
        "UNIPROT_P1",
    )
    with open_catalogue(config=research_config) as connection:
        frame = resolve_sequence_ids(
            connection=connection,
            identifiers=["P1", "local-A", "multi", "small", "missing"],
            prefixes=("UNIPROT_",),
        )
        assert set(frame[frame.input_id == "multi"].cluster_id) == {"GLOBAL_A", "GLOBAL_B"}
        assert set(frame[frame.input_id == "missing"].mapping_status) == {"UNMATCHED"}
        assert set(frame[frame.input_id == "small"].mapping_status) == {
            "MAPPED_WITHOUT_ROW_GROUP_INDEX"
        }
        assert set(frame[frame.input_id == "local-A"].sequence_id) == {"B"}
        assert set(frame[frame.input_id == "P1"].mapping_status) == {"EXPLICIT_ALIAS"}
        assert len(resolve_sequence_ids(connection=connection, identifiers=["B"])) == 1
        assert list(browse_clusters(connection=connection).cluster_id) == [
            "GLOBAL_A",
            "GLOBAL_B",
            "GLOBAL_C",
        ]
        assert len(browse_clusters(connection=connection, cluster_ids=["GLOBAL_B"])) == 1
        with pytest.raises(ResearchError, match="Species"):
            browse_clusters(connection=connection, taxon_ids=[9606])
        with pytest.raises(ResearchError):
            resolve_sequence_ids(connection=connection, identifiers=[])
    for identifier in ("", "a b", "a\nx"):
        with pytest.raises(ResearchError):
            sequence_aliases(identifier=identifier)


def test_retrieval_reads_all_indexed_groups_and_reconciles_counts(research_config, tmp_path):
    """A cluster spanning physical groups is complete and other clusters do not leak in."""
    output = tmp_path / "out"
    output.mkdir()
    artifacts = extract_clusters(config=research_config, cluster_ids=["GLOBAL_A"], output=output)
    fasta = next(path for name, path in artifacts.items() if name.endswith("fasta"))
    assert dict(iter_fasta(path=fasta)) == {"UNIPROT_P1": "ACDE", "B": "ACDF", "UNIPROT_P2": "ACDE"}
    assert "True" in artifacts["members.tsv"].read_text()
    assert "GLOBAL_A\t3\t3" in artifacts["clusters.tsv"].read_text()
    with pytest.raises(ResearchError, match="overwrite"):
        extract_clusters(config=research_config, cluster_ids=["GLOBAL_A"], output=output)
    with pytest.raises(ResearchError, match="max_sequences"):
        extract_clusters(
            config=replace(research_config, max_sequences=2),
            cluster_ids=["GLOBAL_A"],
            output=output,
        )
    for ids in ([], ["UNKNOWN"]):
        with pytest.raises(ResearchError):
            extract_clusters(config=research_config, cluster_ids=ids, output=output)
    bad = tmp_path / "bad.parquet"
    pq.write_table(pa.table({"CLUSTER": ["GLOBAL_A"], "NMEMBER": [4], "RowGroup": ["0,1"]}), bad)
    mismatch = tmp_path / "mismatch"
    mismatch.mkdir()
    with pytest.raises(ResearchError, match="counts disagree"):
        extract_clusters(
            config=replace(research_config, index=str(bad)),
            cluster_ids=["GLOBAL_A"],
            output=mismatch,
        )


def test_taxonomy_index_uses_only_reviewed_assignments(research_config, tmp_path):
    """Species filters distinguish any/all and exclude unreviewed metadata."""
    output = tmp_path / "taxonomy_out"
    output.mkdir()
    path = build_cluster_taxonomy(config=research_config, output=output)
    config = replace(research_config, cluster_taxonomy=str(path))
    with open_catalogue(config=config) as connection:
        assert list(browse_clusters(connection=connection, taxon_ids=[3702]).cluster_id) == [
            "GLOBAL_A"
        ]
        assert list(
            browse_clusters(
                connection=connection, taxon_ids=[3702, 9606], require_all_taxa=True
            ).cluster_id
        ) == ["GLOBAL_A"]
        assert len(browse_clusters(connection=connection, taxon_ids=[3702, 9606])) == 2
        assert len(browse_clusters(connection=connection, any_annotated_species=True)) == 2
    with open_catalogue(
        config=replace(research_config, index=""), require_index=False
    ) as connection:
        assert connection.execute("SELECT count(*) FROM taxonomy").fetchone()[0] == 3
    with pytest.raises(ResearchError):
        with open_catalogue(config=replace(config, index="")):
            pass
    with open(research_config.taxonomy, "a") as handle:
        handle.write("B\tConflicting\t999\tREVIEWED\n")
    with pytest.raises(ResearchError, match="conflicting"):
        build_cluster_taxonomy(config=research_config, output=output)


def test_schema_and_row_group_validation(research_config):
    """Invalid schema names and physical offsets fail before extraction."""
    assert _column(columns=["f0"], choices=("sequence_id", "f0")) == '"f0"'
    assert _column(columns=[], choices=("x",), required=False) == "NULL"
    with pytest.raises(ResearchError):
        _column(columns=[], choices=("required",))
    assert _row_groups(value="[0, 2, 2]", maximum=3) == (0, 2)
    for value in (None, "-1", "1.5", "3", "", "NaN"):
        with pytest.raises(ResearchError):
            _row_groups(value=value, maximum=3)
    with open_catalogue(config=replace(research_config, sequence_map="")) as connection:
        with pytest.raises(ResearchError):
            resolve_sequence_ids(connection=connection, identifiers=["a"])
    with pytest.raises(ResearchError):
        with open_catalogue(config=replace(research_config, index="missing")):
            pass


def test_catalogue_rejects_corrupt_and_incomplete_reviewed_sources(research_config, tmp_path):
    """Unreadable data or absent taxonomy contracts cannot masquerade as empty results."""
    path = tmp_path / "corrupt.parquet"
    path.write_text("not parquet")
    with pytest.raises(ResearchError, match="inspect"):
        with open_catalogue(config=replace(research_config, index=str(path))):
            pass
    with pytest.raises(ResearchError, match="requires"):
        build_cluster_taxonomy(config=replace(research_config, taxonomy=""), output=tmp_path)
    taxonomy = tmp_path / "invalid.tsv"
    taxonomy.write_text("sequence_id\tspecies\na\tHuman\n")
    with pytest.raises(ResearchError, match="taxon_id"):
        with open_catalogue(config=replace(research_config, taxonomy=str(taxonomy))):
            pass
    bridge = tmp_path / "invalid_bridge.tsv"
    bridge.write_text("unrelated\na\n")
    with pytest.raises(ResearchError, match="schema"):
        with open_catalogue(config=replace(research_config, identifier_bridge=str(bridge))):
            pass
