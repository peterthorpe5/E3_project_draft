"""Protein Imager upload-file contents, bounded retrieval and exact identifiers."""

from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO, StringIO
import json
from zipfile import ZipFile

import pandas as pd
import pytest

from e3app.alphafold_hog_bundle import AlphaFoldModelUnavailable, build_alphafold_hog_bundle
from e3app.errors import AppError
from e3app.protein_imager import prepare_protein_imager_data, protein_imager_member_rows


def make_imager_data(*, group_id: str, accessions: tuple[str, ...], missing: tuple[str, ...] = ()):
    """Create a real prepared data archive using a deterministic coordinate-only provider."""
    requests = []

    def reader(url: str, maximum_bytes: int) -> bytes:
        """Return approved-host metadata/model fixtures and reject unnecessary PAE downloads."""
        requests.append(url)
        if "/api/prediction/" in url:
            accession = url.rsplit("/", 1)[-1]
            if accession in missing:
                raise AlphaFoldModelUnavailable("No model available in test provider")
            return json.dumps([{
                "uniprotAccession": accession,
                "cifUrl": f"https://alphafold.ebi.ac.uk/files/AF-{accession}-F1-model_v6.cif",
                "paeDocUrl": (
                    "https://alphafold.ebi.ac.uk/files/"
                    f"AF-{accession}-F1-predicted_aligned_error_v6.json"
                ),
            }]).encode()
        assert url.endswith(".cif"), "Protein Imager must not fetch unnecessary PAE data"
        accession = url.rsplit("/", 1)[-1].split("-")[1]
        return f"data_{accession}\n# full model fixture\n_atom_site.id 1\n".encode()

    data = prepare_protein_imager_data(
        group_id=group_id, accessions=accessions, reader=reader,
        species_by_accession={accession: "test_species" for accession in accessions},
    )
    return data, requests


def test_prepared_zip_contains_uploadable_full_cif_and_clear_instructions() -> None:
    """Each selected accession has a directly loadable CIF, checksum and source in the ZIP."""
    data, requests = make_imager_data(group_id="N0.HOG0001", accessions=("Q9SA03", "P38398"))
    assert len(requests) == 4
    assert [file.filename for file in data.files] == ["Q9SA03.cif", "P38398.cif"]
    assert all(record.pae_status == "not_requested" for record in data.records)
    with ZipFile(BytesIO(data.payload)) as archive:
        assert set(archive.namelist()) == {
            "models/Q9SA03.cif", "models/P38398.cif", "manifest.tsv", "README.txt",
        }
        audit = list(csv.DictReader(
            StringIO(archive.read("manifest.tsv").decode()), delimiter="\t",
        ))
        assert [row["accession"] for row in audit] == ["Q9SA03", "P38398"]
        for file, row in zip(data.files, audit, strict=True):
            assert archive.read(row["upload_file"]) == file.data
            assert row["model_sha256"] == sha256(file.data).hexdigest()
            assert row["model_url"].endswith(f"AF-{file.accession}-F1-model_v6.cif")
        instructions = archive.read("README.txt").decode()
        assert "Extract this ZIP" in instructions and "select structural files" in instructions
        assert "original prediction model" in instructions


def test_missing_models_have_explicit_status_and_never_substitute_an_accession() -> None:
    """Partial and empty preparations preserve the exact request and its retrieval outcomes."""
    data, _requests = make_imager_data(
        group_id="one_protein", accessions=("Q9SA03", "P38398"), missing=("P38398",),
    )
    assert [file.accession for file in data.files] == ["Q9SA03"]
    assert [record.status for record in data.records] == ["included", "not_available"]
    empty, _requests = make_imager_data(
        group_id="one_protein", accessions=("P38398",), missing=("P38398",),
    )
    assert not empty.files
    with ZipFile(BytesIO(empty.payload)) as archive:
        assert not any(name.endswith(".cif") for name in archive.namelist())
        assert "not_available" in archive.read("manifest.tsv").decode()


@pytest.mark.parametrize("include_pae", (None, "false", 0))
def test_coordinate_only_retrieval_requires_a_boolean_policy(*, include_pae: object) -> None:
    """Ambiguous policy values fail before any external model request."""
    with pytest.raises(AppError, match="include_pae must be boolean"):
        build_alphafold_hog_bundle(
            hog_id="N0.HOG1", accessions=("P12345",), include_pae=include_pae,
            reader=lambda *args: pytest.fail("Invalid policy must not contact a provider"),
        )


def test_member_adapters_preserve_canonical_raw_and_review_identifiers() -> None:
    """HOG and report contexts produce explicit model inputs without guessing another ID."""
    source = pd.DataFrame({
        "candidate_accession": ["Q9SA03", "local_gene"],
        "species_column": ["Arabidopsis_thaliana", None],
    })
    adapted = protein_imager_member_rows(rows=source)
    assert adapted["member_parsed_accession"].tolist() == ["Q9SA03", "local_gene"]
    assert adapted["member_species"].tolist() == ["Arabidopsis_thaliana", ""]
    raw = protein_imager_member_rows(rows=pd.DataFrame({"raw_identifier": ["sp|P38398|BRCA1"]}))
    assert raw["member_raw_identifier"].tolist() == ["sp|P38398|BRCA1"]
    assert protein_imager_member_rows(rows=pd.DataFrame()).empty
    with pytest.raises(AppError, match="explicit protein identifiers"):
        protein_imager_member_rows(rows=pd.DataFrame({"unsupported": ["P12345"]}))


def test_preparation_retains_provider_bounds_and_rejects_local_identifier_guessing() -> None:
    """Protein Imager preparation shares the strict canonical-accession request policy."""
    with pytest.raises(AppError, match="Invalid UniProt"):
        prepare_protein_imager_data(group_id="local", accessions=("local_gene",))
    with pytest.raises(AppError, match="Select at least one"):
        prepare_protein_imager_data(group_id="empty", accessions=())
