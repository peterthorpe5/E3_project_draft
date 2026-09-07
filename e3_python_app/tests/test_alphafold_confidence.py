"""Tests for bounded AlphaFold Database confidence retrieval."""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from e3app.alphafold_confidence import (
    ALPHAFOLD_API_BASE_URL,
    MAX_METADATA_BYTES,
    MAX_MODEL_BYTES,
    _read_https,
    parse_alphafold_pdb_confidence,
    retrieve_alphafold_confidence,
)
from e3app.errors import AppError


def _pdb_ca(*, serial: int, residue: int, score: float) -> str:
    """Return one fixed-column PDB C-alpha record."""
    return (
        f"ATOM  {serial:5d}  CA  ALA A{residue:4d}    "
        f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}{1.0:6.2f}{score:6.2f}          C"
    )


def test_retrieve_uses_exact_metadata_model_and_bounded_reads() -> None:
    """The API-selected PDB is parsed without constructing a model version URL."""
    model_url = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.pdb"
    metadata = json.dumps(
        [{"uniprotAccession": "P12345", "pdbUrl": model_url}]
    ).encode("utf-8")
    model = ("\n".join([
        _pdb_ca(serial=1, residue=1, score=42.5),
        _pdb_ca(serial=2, residue=2, score=91.0),
    ]) + "\n").encode("utf-8")
    calls: list[tuple[str, int]] = []

    def reader(url: str, maximum_bytes: int) -> bytes:
        """Return deterministic metadata and PDB fixtures."""
        calls.append((url, maximum_bytes))
        return metadata if url.startswith(ALPHAFOLD_API_BASE_URL) else model

    record = retrieve_alphafold_confidence(accession="p12345", reader=reader)
    assert record.accession == "P12345"
    assert record.model_url == model_url
    assert record.quality_by_residue == (("1", 42.5), ("2", 91.0))
    assert calls == [
        (f"{ALPHAFOLD_API_BASE_URL}P12345", MAX_METADATA_BYTES),
        (model_url, MAX_MODEL_BYTES),
    ]


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (b"{bad", "UTF-8 JSON"),
        (b"{}", "prediction list"),
        (b"[]", "no unique model"),
        (
            b'[{"uniprotAccession":"P12345","pdbUrl":"http://example.org/a"}]',
            "unapproved",
        ),
    ],
)
def test_retrieve_rejects_bad_metadata(metadata: bytes, message: str) -> None:
    """Malformed, missing and unapproved metadata fails explicitly."""
    with pytest.raises(AppError, match=message):
        retrieve_alphafold_confidence(
            accession="P12345",
            reader=lambda _url, _limit: metadata,
        )


def test_pdb_parser_ignores_other_atoms_and_rejects_conflicts() -> None:
    """Only unique, valid C-alpha pLDDT values are retained."""
    first = _pdb_ca(serial=1, residue=1, score=42.0)
    conflicting = _pdb_ca(serial=2, residue=1, score=43.0)
    retained = _pdb_ca(serial=3, residue=2, score=90.0)
    assert parse_alphafold_pdb_confidence(
        (first + "\n" + conflicting + "\n" + retained).encode("utf-8")
    ) == (("2", 90.0),)
    with pytest.raises(AppError, match="no usable"):
        parse_alphafold_pdb_confidence(b"HEADER empty\n")
    with pytest.raises(AppError, match="UTF-8"):
        parse_alphafold_pdb_confidence(b"\xff")


def test_retrieve_requires_a_canonical_uniprot_accession() -> None:
    """Local identifiers are never sent to AlphaFold Database."""
    with pytest.raises(AppError, match="canonical UniProt"):
        retrieve_alphafold_confidence(
            accession="local_scaffold",
            reader=lambda _url, _limit: b"",
        )


def test_https_reader_restricts_host_size_and_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default network boundary accepts only bounded AlphaFold HTTPS data."""
    with pytest.raises(AppError, match="unapproved"):
        _read_https("https://example.org/model.pdb", 10)

    class Response:
        """Minimal context-managed HTTP response fixture."""

        def __enter__(self) -> "Response":
            """Return this fixture."""
            return self

        def __exit__(self, *_args: object) -> None:
            """Close the fixture without suppressing exceptions."""

        def read(self, _maximum: int) -> bytes:
            """Return an intentionally oversized response."""
            return b"1234"

    monkeypatch.setattr(
        "e3app.alphafold_confidence.urlopen",
        lambda _request, timeout: Response(),
    )
    with pytest.raises(AppError, match="size limit"):
        _read_https("https://alphafold.ebi.ac.uk/model.pdb", 3)

    def failed_urlopen(_request: object, timeout: int) -> None:
        """Raise a deterministic transport failure."""
        raise URLError("offline")

    monkeypatch.setattr("e3app.alphafold_confidence.urlopen", failed_urlopen)
    with pytest.raises(AppError, match="Could not retrieve"):
        _read_https("https://alphafold.ebi.ac.uk/model.pdb", 3)
