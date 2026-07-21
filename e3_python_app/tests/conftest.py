"""Shared application tests and a representative tiny DuckDB resource."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest


@pytest.fixture
def resource_db(tmp_path: Path) -> Path:
    """Create candidate, orthology, pocket and provenance relations."""

    path = tmp_path / "resource.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE candidates(accession VARCHAR, organism VARCHAR, score DOUBLE)"
        )
        connection.execute(
            "INSERT INTO candidates VALUES ('Q9SA03', 'Arabidopsis thaliana', 0.95), "
            "('P38398', 'Homo sapiens', 0.80)"
        )
        connection.execute(
            "CREATE TABLE orthogroup_membership(parsed_accession VARCHAR, orthogroup VARCHAR)"
        )
        connection.execute("INSERT INTO orthogroup_membership VALUES ('Q9SA03', 'OG0001686')")
        connection.execute("CREATE TABLE pocket_scores(accession VARCHAR, p2rank_score DOUBLE)")
        connection.execute("INSERT INTO pocket_scores VALUES ('Q9SA03', 4.2)")
        connection.execute("CREATE TABLE provenance_manifest(path VARCHAR, checksum VARCHAR)")
        connection.execute("INSERT INTO provenance_manifest VALUES ('source', 'abc')")
        connection.execute("CREATE VIEW candidate_view AS SELECT * FROM candidates")
    return path

