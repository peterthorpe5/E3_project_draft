"""Test recorded job provenance and recovery from exact published HOG sequences."""

from pathlib import Path

import duckdb
import pytest

from e3app.external_hog import collect_external_hog_members
from e3app.research.common import ResearchError, atomic_json
from e3app.research.hog_context import hog_member_metadata, job_hog, recover_hog_metadata
from e3app.research.jobs import claim_job, finish_job, job_directory, submit_job


def test_legacy_hog_metadata_requires_exact_id_and_sequence(*, resource_db, tmp_path):
    """Resolve only matching proteins, with an unchanged saved FASTA and no external lookup."""
    fasta = tmp_path / "sequences.fasta"
    with duckdb.connect(database=str(resource_db), read_only=True) as connection:
        hog = "N0.HOG0001"
        members = collect_external_hog_members(connection=connection, hog_id=hog)
        plant, human = tuple(members.itertuples(index=False))
        fasta.write_text(
            f">{plant.fasta_identifier}\n{plant.protein_sequence}\n"
            f">{human.fasta_identifier}\nACDE\n>unverified\nMAAAN\n",
            encoding="utf-8",
        )
        assert recover_hog_metadata(connection=connection, hog_id=hog, fasta=fasta) == {
            plant.fasta_identifier: {"species": "Arabidopsis_thaliana", "taxon_id": 3702},
        }


@pytest.mark.parametrize(
    "member_groups",
    [
        [],
        {"": {}},
        {"Glycine_max": {"taxon_id": "3847", "sequence_ids": ["a"]}},
        {"Glycine_max": {"taxon_id": 3847, "sequence_ids": "a"}},
        {"Glycine_max": {"taxon_id": 3847, "sequence_ids": ["a", "a"]}},
    ],
)
def test_invalid_saved_taxonomy_cannot_assign_species(*, member_groups, tmp_path):
    """Reject ambiguous or malformed taxonomy snapshots."""
    fasta = tmp_path / "sequences.fasta"
    fasta.write_text(">a\nACDE\n", encoding="utf-8")
    with pytest.raises(ResearchError):
        hog_member_metadata(
            workspace=None, fasta=fasta,
            parameters={"e3_hog_id": "N0.HOG0001", "e3_hog_members": member_groups},
        )


def test_legacy_hog_source_survives_ancestry_without_taxonomy(*, tmp_path: Path):
    """Follow old completed requests, with the HOG unavailable when provenance is missing."""
    hog = "N0.HOG0001"
    source = submit_job(workspace=tmp_path, operation="align", parameters={"e3_hog_id": hog})
    parent = submit_job(
        workspace=tmp_path, operation="subcluster", parameters={"source_job": source},
    )
    for identifier, parameters in (
        (source, {"e3_hog_id": hog}),
        (parent, {"source_job": source}),
    ):
        claim_job(workspace=tmp_path, job_id=identifier)
        directory = job_directory(workspace=tmp_path, job_id=identifier)
        atomic_json(
            path=directory / "manifest.json",
            value={"job_id": identifier, "artifacts": {}, "parameters": parameters},
        )
        finish_job(workspace=tmp_path, job_id=identifier)
    assert job_hog(record={"parameters": {"source_job": parent}}, workspace=tmp_path) == hog
    assert job_hog(record={"parameters": {"source_job": "a" * 32}}, workspace=tmp_path) == ""
    assert job_hog(record={"parameters": {}}, workspace=tmp_path) == ""
    assert hog_member_metadata(
        workspace=tmp_path, parameters={"source_job": "a" * 32}, fasta=tmp_path / "unused.fasta",
    ) == {}
