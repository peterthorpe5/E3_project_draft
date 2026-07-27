"""Tests for resumable InterPro/Pfam annotation caching and tri-state evidence."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from e3workflow.domain_annotations import (
    InterProClient,
    InterProSettings,
    _atomic_json,
    _load_cache,
    cache_path,
    flatten_interpro_results,
    retrieve_annotations,
)
from e3workflow.errors import StageError
from e3workflow.production import _downloaded_domain_records
from e3workflow.resources import build_domain_cache_manifest, read_resource_manifest


class FakeResponse:
    """Minimal context-managed urllib response used by the client tests."""

    def __init__(
        self,
        payload: dict[str, Any] | None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialise one deterministic response."""
        self.status = status
        self.headers = headers or {}
        self._raw = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        """Return this response from a context manager."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close the fake response without side effects."""

    def getcode(self) -> int:
        """Return the configured HTTP status."""
        return self.status

    def read(self) -> bytes:
        """Return the serialised JSON body."""
        return self._raw


def settings(tmp_path: Path, *, allow_network: bool = True) -> InterProSettings:
    """Return fast deterministic client settings."""
    return InterProSettings(
        api_base_url="https://www.ebi.ac.uk/interpro/api",
        cache_root=tmp_path / "cache",
        allow_network=allow_network,
        workers=2,
        request_timeout_seconds=2.0,
        max_retries=1,
        retry_delay_seconds=0.0,
    )


def pfam_result() -> dict[str, Any]:
    """Return one realistic bounded Pfam API result."""
    return {
        "metadata": {
            "accession": "PF00646",
            "name": "F-box domain",
            "source_database": "pfam",
            "type": "domain",
            "integrated": "IPR001810",
        },
        "proteins": [
            {
                "accession": "q9sa03",
                "protein_length": 311,
                "source_database": "reviewed",
                "organism": "3702",
                "in_alphafold": True,
                "entry_protein_locations": [
                    {
                        "fragments": [
                            {"start": 9, "end": 47, "dc-status": "CONTINUOUS"}
                        ],
                        "representative": False,
                        "model": "PF00646",
                        "score": 4.4e-5,
                    }
                ],
            }
        ],
    }


def test_interpro_cache_download_pagination_and_reuse(tmp_path: Path) -> None:
    """Terminal API results are paginated, cached atomically and then reused offline."""
    calls: list[str] = []
    page_two = "https://www.ebi.ac.uk/interpro/api/page-two"

    def opener(request: Any, timeout: float) -> FakeResponse:
        calls.append(request.full_url)
        assert timeout == 2.0
        payload = (
            {"results": [pfam_result()], "next": page_two}
            if "entry/all" in request.full_url
            else {"results": [], "next": None}
        )
        return FakeResponse(
            payload,
            headers={"InterPro-Version": "109.0", "InterPro-Version-Minor": "0"},
        )

    client = InterProClient(settings=settings(tmp_path), opener=opener)
    payload, path, network_used = client.retrieve("q9sa03")
    assert payload["retrieval_status"] == "ANNOTATED"
    assert payload["release"]["interpro_version"] == "109.0"
    assert path is not None and path.is_file()
    assert network_used is True
    assert calls == [
        "https://www.ebi.ac.uk/interpro/api/entry/all/protein/uniprot/Q9SA03/?page_size=200",
        page_two,
    ]
    cached, same_path, second_network = InterProClient(
        settings=settings(tmp_path, allow_network=False),
        opener=lambda *_args, **_kwargs: pytest.fail("cache reuse made a network request"),
    ).retrieve("Q9SA03")
    assert cached == payload
    assert same_path == path
    assert second_network is False
    assert cache_path(cache_root=tmp_path / "cache", accession="Q9SA03") == path


def test_interpro_no_entries_missing_cache_and_transient_error(tmp_path: Path) -> None:
    """Protein-without-entries is negative-capable; no cache and errors remain unavailable."""
    responses = iter(
        [
            FakeResponse(None, status=204),
            FakeResponse({"metadata": {"accession": "Q00001"}}),
        ]
    )
    payload, path, _ = InterProClient(
        settings=settings(tmp_path), opener=lambda *_args, **_kwargs: next(responses)
    ).retrieve("Q00001")
    assert payload["retrieval_status"] == "PROTEIN_WITHOUT_ENTRIES"
    assert path is not None and path.is_file()
    missing, missing_path, _ = InterProClient(
        settings=settings(tmp_path / "offline", allow_network=False)
    ).retrieve("Q00002")
    assert missing["retrieval_status"] == "CACHE_UNAVAILABLE"
    assert missing_path is None

    def failing(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("temporary outage")

    failed, failed_path, network_used = InterProClient(
        settings=settings(tmp_path / "failure"), opener=failing
    ).retrieve("Q00003")
    assert failed["retrieval_status"] == "DOWNLOAD_ERROR"
    assert failed_path is None
    assert network_used is True


def test_flatten_tri_state_and_offline_manifest(tmp_path: Path) -> None:
    """Flattened coordinates and all three domain evidence states remain distinguishable."""
    annotated = {
        "schema_version": 1,
        "requested_accession": "Q9SA03",
        "retrieval_status": "ANNOTATED",
        "retrieved_at_utc": "2026-07-22T00:00:00Z",
        "api_base_url": "https://www.ebi.ac.uk/interpro/api",
        "release": {"interpro_version": "109.0"},
        "protein_metadata": None,
        "results": [pfam_result()],
        "error": "",
    }
    flattened = flatten_interpro_results(annotated)
    assert flattened[0]["entry_accession"] == "PF00646"
    assert flattened[0]["location_start"] == 9
    members = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
            "primary_group_id": "N0.HOG0001",
            "member_accession": accession,
            "species_column": species,
            "raw_identifier": accession or "custom_gene_1",
            "identifier_mapping_status": "PARSED" if accession else "UNPARSED",
        }
        for accession, species in (
            ("Q9SA03", "Arabidopsis_thaliana"),
            ("Q00002", "Oryza_sativa"),
            ("", "Zea_mays"),
        )
    ]
    hits, summaries = _downloaded_domain_records(
        members=members,
        payloads={
            "Q9SA03": annotated,
            "Q00002": {
                "retrieval_status": "PROTEIN_WITHOUT_ENTRIES",
                "release": {"interpro_version": "109.0"},
                "results": [],
            },
        },
        catalogue={
            "PF00646": {
                "e3_family": "SCF/F-box",
                "evidence_role": "substrate receptor",
                "interpretation": "family support",
            }
        },
    )
    assert len(hits) == 1
    assert [row["domain_support_status"] for row in summaries] == [
        "SUPPORTED",
        "ANNOTATED_NO_CATALOGUED_E3_DOMAIN",
        "ANNOTATION_UNAVAILABLE",
    ]

    cache = tmp_path / "cache"
    cache.mkdir()
    cache_file = cache_path(cache_root=cache, accession="Q9SA03")
    cache_file.write_text(json.dumps(annotated), encoding="utf-8")
    manifest = build_domain_cache_manifest(
        cache_root=cache, output_path=tmp_path / "domain_manifest.tsv"
    )
    records = read_resource_manifest(
        path=manifest,
        allowed_resource_types={"interpro_annotation_cache"},
        verify_checksums=True,
    )
    assert records[0]["dataset"] == "ANNOTATED"


def test_retrieve_annotations_deduplicates_accessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent retrieval resolves each unique accession exactly once."""
    observed: list[str] = []

    def retrieve(self: InterProClient, accession: str) -> tuple[dict[str, Any], None, bool]:
        observed.append(accession)
        return (
            {
                "retrieval_status": "CACHE_UNAVAILABLE",
                "retrieved_at_utc": "",
                "release": {},
                "results": [],
                "error": "offline",
            },
            None,
            False,
        )

    monkeypatch.setattr(InterProClient, "retrieve", retrieve)
    payloads, inventory = retrieve_annotations(
        accessions=["q1", "Q1", "Q2"], settings=settings(tmp_path)
    )
    assert sorted(observed) == ["Q1", "Q2"]
    assert sorted(payloads) == ["Q1", "Q2"]
    assert len(inventory) == 2


def test_cache_api_and_flatten_defensive_branches(tmp_path: Path) -> None:
    """Incompatible caches and malformed remote shapes never masquerade as annotations."""
    path = tmp_path / "cache.json"
    assert _load_cache(path, "Q1") is None
    for payload in (
        "[",
        "[]",
        json.dumps({"schema_version": 99}),
        json.dumps(
            {
                "schema_version": 1,
                "requested_accession": "OTHER",
                "retrieval_status": "ANNOTATED",
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "requested_accession": "Q1",
                "retrieval_status": "DOWNLOAD_ERROR",
            }
        ),
    ):
        path.write_text(payload, encoding="utf-8")
        assert _load_cache(path, "Q1") is None
    valid = {
        "schema_version": 1,
        "requested_accession": "Q1",
        "retrieval_status": "NOT_FOUND",
    }
    _atomic_json(path, valid)
    assert _load_cache(path, "Q1") == valid

    with pytest.raises(StageError, match="absolute HTTPS"):
        InterProClient(
            settings=InterProSettings(
                api_base_url="http://example.org",
                cache_root=tmp_path,
                allow_network=True,
                workers=1,
                request_timeout_seconds=1,
                max_retries=0,
                retry_delay_seconds=0,
            )
        )
    client = InterProClient(settings=settings(tmp_path))
    with pytest.raises(StageError, match="unsafe pagination"):
        client._validated_url("https://example.org/page")

    responses = iter(
        [
            (200, {"results": [], "next": "loop"}, {}),
            (200, {"results": [], "next": "loop"}, {}),
        ]
    )
    client._request_json = lambda _url: next(responses)  # type: ignore[method-assign]
    with pytest.raises(StageError, match="pagination loop"):
        client._entry_results("Q1")
    client._request_json = lambda _url: (200, {"metadata": []}, {})  # type: ignore[method-assign]
    with pytest.raises(StageError, match="malformed protein metadata"):
        client._protein_metadata("Q1")

    flattened = flatten_interpro_results(
        {
            "results": [
                "bad",
                {"metadata": "bad"},
                {"metadata": {"source_database": "other"}},
                {
                    "metadata": {
                        "source_database": "pfam",
                        "accession": "PF1",
                    },
                    "proteins": "bad",
                },
            ]
        }
    )
    assert flattened[0]["entry_accession"] == "PF1"
    assert flattened[0]["location_start"] == ""
