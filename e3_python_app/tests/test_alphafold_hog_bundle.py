"""Tests for bounded HOG-member AlphaFold Database model bundles."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

import pandas as pd
import pytest

from e3app import __version__
from e3app.alphafold_hog_bundle import (
    ALPHAFOLD_API_BASE_URL,
    MAX_METADATA_BYTES,
    MAX_MODEL_BYTES,
    MAX_PAE_BYTES,
    AlphaFoldModelUnavailable,
    _read_https,
    build_alphafold_hog_bundle,
    convert_alphafold_pae_for_inspector,
    hog_model_candidates,
    parse_model_reference,
)
from e3app.errors import AppError


def _metadata(*, accession: str, include_pae: bool = True) -> bytes:
    """Return one deterministic AlphaFold Database metadata document."""
    record = {
        "uniprotAccession": accession,
        "cifUrl": (
            "https://alphafold.ebi.ac.uk/files/"
            f"AF-{accession}-F1-model_v6.cif"
        ),
    }
    if include_pae:
        record["paeDocUrl"] = (
            "https://alphafold.ebi.ac.uk/files/"
            f"AF-{accession}-F1-predicted_aligned_error_v6.json"
        )
    return json.dumps([record]).encode("utf-8")


def test_hog_model_candidates_are_unique_labelled_and_ordered() -> None:
    """Only canonical accessions enter the default-all selector."""
    members = pd.DataFrame(
        {
            "member_parsed_accession": [
                "p12345",
                "P12345",
                None,
                "local",
                None,
            ],
            "member_structural_accession": [None, None, "Q8LGH4", None, None],
            "member_raw_identifier": [
                "sp|P12345|ONE",
                "sp|P12345|ONE",
                "tr|Q8LGH4|TWO",
                "local",
                "sp|O98765|THREE",
            ],
            "member_species": [
                "Arabidopsis_thaliana",
                "Arabidopsis_thaliana",
                "Homo_sapiens",
                "Other",
                "Oryza_sativa",
            ],
            "member_structural_readiness_rank": [1, 2, 3, 4, 5],
        }
    )
    candidates = hog_model_candidates(members=members)
    assert [candidate.accession for candidate in candidates] == [
        "P12345",
        "Q8LGH4",
        "O98765",
    ]
    assert candidates[0].species == "Arabidopsis_thaliana"
    assert candidates[0].label == (
        "P12345 · Arabidopsis thaliana · within-HOG rank 1"
    )
    assert candidates[1].label.startswith("Q8LGH4 · Homo sapiens")

    with pytest.raises(AppError, match="accession source"):
        hog_model_candidates(members=pd.DataFrame({"other": ["P12345"]}))


def test_hog_model_candidates_parse_standard_raw_uniprot_identifiers() -> None:
    """Legacy membership rows can supply strict UniProt FASTA identifiers."""
    members = pd.DataFrame(
        {
            "member_raw_identifier": [
                "sp|Q9SA03|FB27_ARATH",
                "tr|P38398|BRCA1_HUMAN description",
                "prefix|Q8LGH4|not_uniprot",
                "Q8LGH4",
            ],
            "member_species": ["A", "B", "C", "D"],
        }
    )
    candidates = hog_model_candidates(members=members)
    assert [candidate.accession for candidate in candidates] == [
        "Q9SA03",
        "P38398",
        "Q8LGH4",
    ]


def test_model_reference_requires_exact_approved_mmcif_metadata() -> None:
    """Metadata cannot redirect model retrieval or ambiguously select a model."""
    reference = parse_model_reference(
        payload=_metadata(accession="P12345"),
        accession="P12345",
    )
    assert reference.accession == "P12345"
    assert reference.model_url.endswith("AF-P12345-F1-model_v6.cif")
    assert reference.pae_url is not None
    assert reference.pae_url.endswith("predicted_aligned_error_v6.json")

    with pytest.raises(AlphaFoldModelUnavailable, match="no AlphaFold"):
        parse_model_reference(payload=b"[]", accession="P12345")
    with pytest.raises(AppError, match="prediction list"):
        parse_model_reference(payload=b"{}", accession="P12345")
    with pytest.raises(AppError, match="valid UTF-8 JSON"):
        parse_model_reference(payload=b"{bad", accession="P12345")
    unsafe = json.dumps(
        [
            {
                "uniprotAccession": "P12345",
                "cifUrl": "https://example.org/model.cif",
            }
        ]
    ).encode("utf-8")
    with pytest.raises(AppError, match="invalid .cif URL"):
        parse_model_reference(payload=unsafe, accession="P12345")


def test_pae_conversion_validates_matrix_and_adds_monomer_labels() -> None:
    """AlphaFold DB PAE becomes the full-data subset read by the Inspector."""
    payload = json.dumps(
        [{"predicted_aligned_error": [[0.0, 2.5], [2.0, 0.0]]}]
    ).encode("utf-8")
    converted = json.loads(
        convert_alphafold_pae_for_inspector(payload=payload).decode("utf-8")
    )
    assert converted == {
        "pae": [[0.0, 2.5], [2.0, 0.0]],
        "token_chain_ids": ["A", "A"],
        "token_res_ids": [1, 2],
    }

    for invalid in (
        b"{bad",
        b"{}",
        json.dumps({"pae": [[0, 1]]}).encode("utf-8"),
        json.dumps({"pae": [[0, True], [1, 0]]}).encode("utf-8"),
    ):
        with pytest.raises(AppError):
            convert_alphafold_pae_for_inspector(payload=invalid)


def test_bundle_contains_available_models_pae_manifest_and_boundary() -> None:
    """Missing and failed models are audited without blocking valid files."""
    model = b"data_AF-P12345-F1\n_entry.id AF-P12345-F1\n"
    pae = json.dumps(
        [{"predicted_aligned_error": [[0.0, 1.0], [1.0, 0.0]]}]
    ).encode("utf-8")

    def reader(url: str, maximum_bytes: int) -> bytes:
        """Return deterministic metadata, model and PAE fixtures."""
        if url == f"{ALPHAFOLD_API_BASE_URL}P12345":
            assert maximum_bytes == MAX_METADATA_BYTES
            return _metadata(accession="P12345")
        if url == f"{ALPHAFOLD_API_BASE_URL}Q8LGH4":
            return b"[]"
        if url == f"{ALPHAFOLD_API_BASE_URL}O98765":
            raise AppError("temporary service failure")
        if url.endswith("model_v6.cif"):
            assert maximum_bytes == MAX_MODEL_BYTES
            return model
        if url.endswith("predicted_aligned_error_v6.json"):
            assert maximum_bytes == MAX_PAE_BYTES
            return pae
        raise AssertionError(f"Unexpected URL: {url}")

    bundle = build_alphafold_hog_bundle(
        hog_id="N0.HOG0001",
        accessions=("P12345", "Q8LGH4", "O98765"),
        species_by_accession={"P12345": "Arabidopsis_thaliana"},
        reader=reader,
        maximum_workers=2,
    )
    assert bundle.requested_count == 3
    assert bundle.included_count == 1
    assert bundle.pae_count == 1
    assert bundle.skipped_accessions == ("Q8LGH4", "O98765")
    assert [record.status for record in bundle.records] == [
        "included",
        "not_available",
        "error",
    ]
    assert bundle.records[0].model_sha256 == sha256(model).hexdigest()
    assert bundle.records[0].species == "Arabidopsis_thaliana"

    with ZipFile(BytesIO(bundle.payload)) as archive:
        names = set(archive.namelist())
        assert "e3_N0.HOG0001_model_0.cif" in names
        assert "e3_N0.HOG0001_full_data_0.json" in names
        assert "e3_N0.HOG0001_model_1.cif" not in names
        assert {"manifest.tsv", "README.txt"}.issubset(names)
        manifest = archive.read("manifest.tsv").decode("utf-8")
        assert "P12345\tArabidopsis_thaliana\tincluded" in manifest
        assert "Q8LGH4\t\tnot_available" in manifest
        readme = archive.read("README.txt").decode("utf-8")
        assert "alternative AlphaFold 3 conformers" in readme
        assert "interpreted as zero-valued evidence" in readme


def test_bundle_keeps_model_when_optional_pae_fails_and_enforces_size() -> None:
    """PAE is optional and the aggregate payload limit is fail-closed."""
    model = b"data_AF-P12345-F1\n_entry.id AF-P12345-F1\n"

    def reader(url: str, _maximum_bytes: int) -> bytes:
        """Return one model while failing only its optional PAE request."""
        if url.startswith(ALPHAFOLD_API_BASE_URL):
            return _metadata(accession="P12345")
        if url.endswith(".cif"):
            return model
        raise AppError("PAE offline")

    bundle = build_alphafold_hog_bundle(
        hog_id="N0.HOG0001",
        accessions=("P12345",),
        reader=reader,
        maximum_workers=1,
    )
    assert bundle.included_count == 1
    assert bundle.pae_count == 0
    assert bundle.records[0].pae_status == "error"
    assert "PAE unavailable" in bundle.records[0].detail

    limited = build_alphafold_hog_bundle(
        hog_id="N0.HOG0001",
        accessions=("P12345",),
        reader=reader,
        maximum_workers=1,
        maximum_bundle_bytes=1,
    )
    assert limited.included_count == 0
    assert limited.records[0].status == "bundle_limit"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"hog_id": "", "accessions": ("P12345",)}, "HOG identifier"),
        ({"hog_id": "HOG", "accessions": ()}, "Select at least one"),
        ({"hog_id": "HOG", "accessions": ("bad",)}, "Invalid UniProt"),
        (
            {
                "hog_id": "HOG",
                "accessions": ("P12345",),
                "maximum_workers": 0,
            },
            "maximum_workers",
        ),
        (
            {
                "hog_id": "HOG",
                "accessions": ("P12345",),
                "maximum_bundle_bytes": 0,
            },
            "maximum_bundle_bytes",
        ),
    ],
)
def test_bundle_request_validation_fails_before_network(
    kwargs: dict[str, object], message: str
) -> None:
    """Unsafe identifiers and resource limits cannot start retrieval."""
    with pytest.raises(AppError, match=message):
        build_alphafold_hog_bundle(
            **kwargs,
            reader=lambda _url, _maximum: b"",
        )


def test_https_reader_restricts_host_size_status_and_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The network boundary accepts only bounded AlphaFold HTTPS responses."""
    with pytest.raises(AppError, match="unapproved"):
        _read_https("https://example.org/model.cif", 10)

    class Response:
        """Minimal context-managed response fixture."""

        def __enter__(self) -> "Response":
            """Return this fixture."""
            return self

        def __exit__(self, *_args: object) -> None:
            """Close without suppressing errors."""

        def read(self, _maximum: int) -> bytes:
            """Return a deliberately oversized payload."""
            return b"1234"

    requests: list[object] = []

    def open_response(request: object, timeout: int) -> Response:
        """Capture the request and return a bounded fixture."""
        requests.append(request)
        assert timeout > 0
        return Response()

    monkeypatch.setattr("e3app.alphafold_hog_bundle.urlopen", open_response)
    with pytest.raises(AppError, match="size limit"):
        _read_https("https://alphafold.ebi.ac.uk/model.cif", 3)
    assert requests[0].get_header("User-agent") == f"e3-python-app/{__version__}"

    def missing_urlopen(_request: object, timeout: int) -> None:
        """Raise an HTTP 404 fixture."""
        raise HTTPError("url", 404, "missing", {}, None)

    monkeypatch.setattr("e3app.alphafold_hog_bundle.urlopen", missing_urlopen)
    with pytest.raises(AlphaFoldModelUnavailable):
        _read_https("https://alphafold.ebi.ac.uk/model.cif", 10)

    def failed_urlopen(_request: object, timeout: int) -> None:
        """Raise a transport failure fixture."""
        raise URLError("offline")

    monkeypatch.setattr("e3app.alphafold_hog_bundle.urlopen", failed_urlopen)
    with pytest.raises(AppError, match="Could not retrieve"):
        _read_https("https://alphafold.ebi.ac.uk/model.cif", 10)
