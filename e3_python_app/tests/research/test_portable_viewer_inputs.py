"""Check external DeepClust exports and worker-independent protein input validation."""

from io import BytesIO
import json
from zipfile import ZipFile

import duckdb
import pyarrow as pa
from pyarrow import parquet
import pytest

from e3app.research.common import ResearchError
from e3app.research.deepclust_import import extract_family, open_results, results_preview
from e3app.research.feature_catalogue import feature_contexts, published_features
from e3app.research.viewer_inputs import (
    portable_job_archive,
    read_species_mapping,
    uploaded_proteins,
    validate_protein_tree,
)


def encode_table(*, table: pa.Table) -> bytes:
    """Write the fixture through the same Parquet format expected from an external app."""
    stream = pa.BufferOutputStream()
    parquet.write_table(table, stream, row_group_size=40)
    return stream.getvalue().to_pybytes()


def test_parquet_preview_and_complete_selected_family() -> None:
    """A selected family can occur beyond the preview and keep its exact identifiers."""
    table = pa.table({
        "cluster": ["other"] * 105 + ["target"] * 3,
        "protein": [f"a{i}" for i in range(105)] + ["exact|id", "b", "b"],
        "amino_acids": ["ACD"] * 108,
    })
    reader = open_results(content=encode_table(table=table))
    assert reader.metadata.num_rows == 108
    assert results_preview(reader=reader).num_rows == 100
    parameters = {"id_column": "protein", "sequence_column": "amino_acids"}
    assert extract_family(reader=reader, **parameters, cluster_column="cluster",
                          cluster_id="target") == ">exact|id\nACD\n>b\nACD\n"
    with pytest.raises(ResearchError, match="no protein"):
        extract_family(reader=reader, **parameters, cluster_column="cluster", cluster_id="none")
    with pytest.raises(ResearchError, match="distinct"):
        extract_family(reader=reader, id_column="protein", sequence_column="protein")


@pytest.mark.parametrize(("ids", "sequences", "error"), [
    (["a", "a"], ["ACD", "ACE"], "Conflicting"),
    (["a b", "b"], ["ACD", "ACE"], "whitespace-free"),
    (["a", "b"], ["ACD", None], "lacks amino-acid"),
    (["a", "b"], ["ACD", "A!D"], "invalid residues"),
])
def test_import_never_silently_drops_bad_family_members(ids, sequences, error) -> None:
    """Every selected identifier must have one usable exact protein sequence."""
    reader = open_results(content=encode_table(table=pa.table({"id": ids, "seq": sequences})))
    with pytest.raises(ResearchError, match=error):
        extract_family(reader=reader, id_column="id", sequence_column="seq")


def test_bad_or_empty_parquet_fails_without_a_database() -> None:
    """Reject malformed and empty exports before enabling sequence selection."""
    with pytest.raises(ResearchError, match="Parquet"):
        open_results(content=b"not parquet")
    with pytest.raises(ResearchError, match="result rows"):
        open_results(content=encode_table(table=pa.table({"id": []})))
    with pytest.raises(ResearchError, match="200 MB"):
        open_results(content=b"")


def test_upload_alignment_tree_and_reviewed_taxonomy_are_exact() -> None:
    """Treat uploaded alignment, protein tree and species mapping as distinct inputs."""
    records = uploaded_proteins(text=">a annotation\nA-D\n>b\nACD\n", aligned=True)
    assert records == {"a": "A-D", "b": "ACD"}
    assert validate_protein_tree(newick="(a:1,b:2);", identifiers=list(records)) == "(a:1,b:2);"
    for newick, error in (("(a,b)", "complete"), ("(a,c);", "exactly"),
                          ("(a:-1,b:2);", "non-negative"), ("(a,b;", "parse")):
        with pytest.raises(ResearchError, match=error):
            validate_protein_tree(newick=newick, identifiers=list(records))
    mapping = "sequence_id\tspecies\ttaxon_id\na\tHuman\t9606\nb\tRice\t4530\n"
    assert read_species_mapping(text=mapping)["b"]["taxon_id"] == "4530"
    with pytest.raises(ResearchError, match="unique"):
        read_species_mapping(text=mapping + "a\tRice\t4530\n")
    with pytest.raises(ResearchError, match="columns"):
        read_species_mapping(text="protein\tspecies\na\tHuman\n")


@pytest.mark.parametrize(("fasta", "error"), [
    ("", "at least one"), (">a\nAA\n>a\nAA\n", "Duplicate"),
    (">a\nAA\n>b\nAAA\n", "equal lengths"), ("sequence\n", "before its first header"),
])
def test_invalid_alignment_uploads(fasta, error) -> None:
    """Reject ambiguous FASTA before opening JBrowse."""
    with pytest.raises(ResearchError, match=error):
        uploaded_proteins(text=fasta, aligned=True)
    with pytest.raises(ResearchError, match="count"):
        uploaded_proteins(text=">a\nACD\n", maximum_cells=2)


def test_portable_job_archive_keeps_scientific_settings_and_input() -> None:
    """The ZIP is a local CLI input and does not refer to the originating VM's queue."""
    fasta = ">a\nACD\n>b\nACE\n"
    params = {"engine": "local", "sequence_ids": ["b"], "remote_allowed": False}
    payload = portable_job_archive(operation="predict", parameters=params, fasta=fasta)
    with ZipFile(BytesIO(payload)) as archive:
        assert archive.read("input.fasta").decode() == fasta
        assert json.loads(archive.read("parameters.json")) == params
        assert "--operation predict" in archive.read("READ_ME.txt").decode()
    with pytest.raises(ResearchError, match="standalone"):
        portable_job_archive(operation="align", parameters={"source_job": "foreign"}, fasta=fasta)
    with pytest.raises(ResearchError, match="absent"):
        portable_job_archive(operation="predict", parameters={"sequence_ids": ["c"]}, fasta=fasta)
    with pytest.raises(ResearchError, match="explicit list"):
        portable_job_archive(operation="predict", parameters={"sequence_ids": "a"}, fasta=fasta)
    too_many = "".join(f">seq{i}\nACD\n" for i in range(101))
    with pytest.raises(ResearchError, match="100 proteins"):
        portable_job_archive(operation="predict", parameters={}, fasta=too_many)


def test_recorded_features_can_be_selected_by_hog_or_accession() -> None:
    """The feature list binds original coordinates to the accession and group context."""
    with duckdb.connect() as connection:
        with pytest.raises(ResearchError, match="recorded domain hits"):
            feature_contexts(connection=connection, query="Q5ZC88")
        connection.execute("CREATE TABLE domain_hits(member_accession VARCHAR)")
        with pytest.raises(ResearchError, match="coordinate fields"):
            feature_contexts(connection=connection, query="Q5ZC88")
        connection.execute("DROP TABLE domain_hits")
        connection.execute(
            "CREATE TABLE domain_hits(member_accession VARCHAR, primary_group_id VARCHAR, "
            "species_column VARCHAR, protein_length INTEGER, location_start INTEGER, "
            "location_end INTEGER, entry_accession VARCHAR, entry_name VARCHAR)"
        )
        connection.execute(
            "INSERT INTO domain_hits VALUES "
            "('Q5ZC88','N0.HOG0000390','Oryza_sativa',744,1,744,'PF1','Full length'), "
            "('Q5ZC88','N0.HOG0000390','Oryza_sativa',744,25,95,'PF2','Short hit')"
        )
        for query in ("", "q5zc88", "n0.hog0000390"):
            assert feature_contexts(connection=connection, query=query).accession.tolist() == [
                "Q5ZC88"
            ]
        assert len(published_features(connection=connection, accession=" q5zc88 ")) == 2
