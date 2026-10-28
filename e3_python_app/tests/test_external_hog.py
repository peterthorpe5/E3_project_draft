"""Exact selection, sequence provenance and prepared-model hand-off regressions."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import duckdb
import pandas as pd
import pytest

from e3app.alphafold_hog_bundle import AlphaFoldBundleRecord, AlphaFoldHogBundle
from e3app.errors import AppError
from e3app.external_hog import (
    collect_external_hog_members,
    collect_external_hogs,
    external_hog_pair_fasta,
    prepared_hog_model,
)
from e3app.result_queries import ResourceQuery


def make_model_bundle(
    *, accessions: tuple[str, ...], hog_id: str = "N0.HOG0001",
) -> AlphaFoldHogBundle:
    """Create a deterministic audited model ZIP without any network request."""
    output = BytesIO()
    records = []
    with ZipFile(output, mode="w") as archive:
        for index, accession in enumerate(accessions):
            data = f"data_{accession}\n# exact test coordinate bytes\n".encode()
            archive.writestr(f"e3_{hog_id}_model_{index}.cif", data)
            records.append(AlphaFoldBundleRecord(
                model_index=index, accession=accession, species="test", status="included",
                model_url=f"https://alphafold.ebi.ac.uk/files/AF-{accession}-F1-model_v6.cif",
                model_bytes=len(data), model_sha256=sha256(data).hexdigest(),
                pae_status="not_available", pae_url="", detail="",
            ))
    return AlphaFoldHogBundle(payload=output.getvalue(), records=tuple(records))


def test_members_are_complete_hog_scoped_and_sequence_authority_bound(*, resource_db: Path) -> None:
    """A sequence source cannot introduce non-members or evidence from another HOG/type."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO candidate_group_member_sequences "
            "SELECT * REPLACE ('N0.OTHER' AS group_id, 'GGGG' AS protein_sequence) "
            "FROM candidate_group_member_sequences WHERE species = 'Homo_sapiens'"
        )
        hogs = collect_external_hogs(connection=connection)
        assert hogs["hog_id"].tolist() == ["N0.HOG0001"]
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        assert members["canonical_accession"].tolist() == ["Q9SA03", "P38398"]
        assert members["protein_sequence"].tolist() == ["MSTNPKPN", "MAAAN"]
        assert members["sequence_status"].tolist() == ["AVAILABLE", "AVAILABLE"]
        assert members["member_key"].is_unique
        assert not members["member_species"].eq("Oryza_sativa").any()
        keys = members["member_key"].tolist()
        fasta = external_hog_pair_fasta(
            members=members, first_member_key=keys[1], second_member_key=keys[0],
        ).decode()
        assert fasta.index("MAAAN") < fasta.index("MSTNPKPN")
        assert "Homo_sapiens" in fasta and "Arabidopsis_thaliana" in fasta


@pytest.mark.parametrize("maximum", (0, True, 100_001, 1.5))
def test_interactive_cap_is_validated(*, resource_db: Path, maximum: object) -> None:
    """Bad limits do not generate SQL or silently truncate the selected membership."""
    with duckdb.connect(str(resource_db)) as connection:
        with pytest.raises(AppError, match="limit"):
            collect_external_hog_members(
                connection=connection, hog_id="N0.HOG0001", maximum_members=maximum,
            )


def test_missing_unknown_and_oversized_hogs_fail_without_substitution(*, resource_db: Path) -> None:
    """Unknown identifiers, missing membership and oversized groups cannot select another HOG."""
    with duckdb.connect(str(resource_db)) as connection:
        for value in ("", None):
            with pytest.raises(AppError, match="exact HOG"):
                collect_external_hog_members(connection=connection, hog_id=value)
        with pytest.raises(AppError, match="No published"):
            collect_external_hog_members(connection=connection, hog_id="' OR TRUE --")
        with pytest.raises(AppError, match="exceeds"):
            collect_external_hog_members(
                connection=connection, hog_id="N0.HOG0001", maximum_members=1,
            )
        connection.execute("DROP TABLE hierarchical_membership")
        with pytest.raises(AppError, match="root-level"):
            collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")


def test_optional_sequences_and_null_parsed_accessions_remain_explicit(
    *, resource_db: Path,
) -> None:
    """Raw UniProt identifiers work with null parsed fields, without inventing sequences."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "ALTER TABLE hierarchical_membership ADD COLUMN parsed_accession VARCHAR"
        )
        connection.execute("DROP TABLE candidate_group_member_sequences")
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        assert members["canonical_accession"].tolist() == ["Q9SA03", "P38398"]
        assert set(members["sequence_status"]) == {"UNAVAILABLE"}
        keys = members["member_key"].tolist()
        with pytest.raises(AppError, match="Exact sequence unavailable"):
            external_hog_pair_fasta(
                members=members, first_member_key=keys[0], second_member_key=keys[1],
            )


def test_invalid_conflicting_and_malformed_sequence_authorities(*, resource_db: Path) -> None:
    """Ambiguous or invalid exact sequences are unavailable rather than arbitrarily selected."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO candidate_group_member_sequences "
            "SELECT * REPLACE ('DIFFERENT' AS protein_sequence) "
            "FROM candidate_group_member_sequences WHERE species = 'Homo_sapiens'"
        )
        connection.execute(
            "UPDATE candidate_group_member_sequences SET protein_sequence = 'ACD*' "
            "WHERE species = 'Arabidopsis_thaliana'"
        )
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        assert members["sequence_status"].tolist() == [
            "INVALID_EXACT_SEQUENCE", "CONFLICTING_EXACT_SEQUENCES",
        ]
        assert members["protein_sequence"].eq("").all()
        connection.execute("ALTER TABLE candidate_group_member_sequences DROP COLUMN record_type")
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        assert members["sequence_status"].eq("UNAVAILABLE").all()


def test_member_identity_and_mapping_conflicts_are_not_guessed(*, resource_db: Path) -> None:
    """Conflicting parsed mappings and missing species/IDs fail closed."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "ALTER TABLE hierarchical_membership ADD COLUMN parsed_accession VARCHAR"
        )
        connection.execute(
            "INSERT INTO hierarchical_membership "
            "SELECT * REPLACE ('P12345' AS parsed_accession) FROM hierarchical_membership"
        )
        with pytest.raises(AppError, match="Conflicting accession mappings"):
            collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        connection.execute("DELETE FROM hierarchical_membership WHERE parsed_accession IS NOT NULL")
        connection.execute("UPDATE hierarchical_membership SET species = NULL")
        with pytest.raises(AppError, match="explicit species"):
            collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        connection.execute("UPDATE hierarchical_membership SET species = ' '")
        with pytest.raises(AppError, match="explicit species"):
            collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")


def test_local_and_shared_accessions_preserve_species_specific_sequences(
    *, resource_db: Path,
) -> None:
    """Identical accession text in two species cannot collapse their exact pair sequences."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "UPDATE hierarchical_membership SET raw_identifier = 'P12345'"
        )
        connection.execute(
            "UPDATE candidate_group_member_sequences SET raw_identifier = 'P12345'"
        )
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        keys = members["member_key"].tolist()
        fasta = external_hog_pair_fasta(
            members=members, first_member_key=keys[0], second_member_key=keys[1],
        ).decode()
        assert fasta.count(">P12345|") == 2
        assert "MSTNPKPN" in fasta and "MAAAN" in fasta
        with pytest.raises(AppError, match="two different"):
            external_hog_pair_fasta(
                members=members, first_member_key=keys[0], second_member_key=keys[0],
            )
        with pytest.raises(AppError, match="missing or ambiguous"):
            external_hog_pair_fasta(
                members=members, first_member_key="unknown", second_member_key=keys[0],
            )
        connection.execute("UPDATE hierarchical_membership SET raw_identifier = 'local_gene'")
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        assert members["canonical_accession"].eq("").all()


def test_resource_failures_are_reported(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read failures cannot return a misleading empty or partial selection."""
    with duckdb.connect(str(resource_db)) as connection:
        monkeypatch.setattr(
            "e3app.external_hog.build_result_query",
            lambda **kwargs: ResourceQuery(name="broken", sql="SELECT * FROM absent_table"),
        )
        with pytest.raises(AppError, match="Could not load HOG choices"):
            collect_external_hogs(connection=connection)
        connection.execute("CREATE VIEW broken AS SELECT 1")
        monkeypatch.setattr("e3app.external_hog.SEQUENCE_RELATION", "broken")
        members = collect_external_hog_members(connection=connection, hog_id="N0.HOG0001")
        assert members["sequence_status"].eq("UNAVAILABLE").all()
        with pytest.raises(AppError, match="exact-sequence fields"):
            external_hog_pair_fasta(
                members=pd.DataFrame(), first_member_key="a", second_member_key="b",
            )


def test_prepared_model_download_matches_the_audited_bytes() -> None:
    """The selected accession resolves to its full mmCIF, not another ZIP model."""
    bundle = make_model_bundle(accessions=("Q9SA03", "P38398"))
    assert prepared_hog_model(bundle=bundle, accession="P38398").startswith(b"data_P38398\n")
    with pytest.raises(AppError, match="exactly one"):
        prepared_hog_model(bundle=bundle, accession="P12345")
    with pytest.raises(AppError, match="checksum"):
        prepared_hog_model(
            bundle=replace(bundle, records=(replace(bundle.records[0], model_sha256="wrong"),)),
            accession="Q9SA03",
        )
    with pytest.raises(AppError, match="exactly one"):
        prepared_hog_model(
            bundle=replace(bundle, records=(bundle.records[0], bundle.records[0])),
            accession="Q9SA03",
        )


def test_prepared_model_rejects_corrupt_missing_ambiguous_or_oversized_files(
    *, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model whose ZIP or provenance is invalid is never offered as a valid download."""
    bundle = make_model_bundle(accessions=("P12345",))
    with pytest.raises(AppError, match="archive"):
        prepared_hog_model(bundle=replace(bundle, payload=b"not a ZIP"), accession="P12345")
    output = BytesIO()
    with ZipFile(output, mode="w") as archive:
        archive.writestr("unrelated.cif", "none")
    with pytest.raises(AppError, match="missing, ambiguous"):
        prepared_hog_model(bundle=replace(bundle, payload=output.getvalue()), accession="P12345")
    output = BytesIO()
    with ZipFile(output, mode="w") as archive:
        archive.writestr("first_model_0.cif", "one")
        archive.writestr("second_model_0.cif", "two")
    with pytest.raises(AppError, match="missing, ambiguous"):
        prepared_hog_model(bundle=replace(bundle, payload=output.getvalue()), accession="P12345")
    monkeypatch.setattr("e3app.external_hog.MAX_MODEL_BYTES", 1)
    with pytest.raises(AppError, match="invalid size"):
        prepared_hog_model(bundle=bundle, accession="P12345")
