"""Offline unit tests for UniProt mapping and AlphaFold model retrieval."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from typing import Self
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import fetch_alphafold_models as downloader

MODEL = b"data_AF-P12345-F1\nloop_\n_atom_site.group_PDB\nATOM\n"
PDB_MODEL = b"HEADER    TEST\nATOM      1  CA  ALA A   1  0.000 0.000 0.000\n"


def model_metadata(
    *,
    accession: str = "P12345",
    model_url: str = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.cif",
    sequence: str = "MAKT",
    pae_url: str | None = None,
) -> bytes:
    """Build representative AlphaFold API metadata as UTF-8 JSON."""
    return json.dumps(
        [
            {
                "uniprotAccession": accession,
                "entryId": f"AF-{accession}-F1",
                "cifUrl": model_url,
                "pdbUrl": model_url.replace(".cif", ".pdb"),
                "paeDocUrl": pae_url,
                "uniprotSequence": sequence,
            }
        ]
    ).encode("utf-8")


class StubClient:
    """Return controlled service responses without network access."""

    def __init__(self, *, responses: dict[str, bytes | Exception]) -> None:
        """Store endpoint responses and calls for exact assertions."""
        self.responses = responses
        self.calls: list[str] = []

    def read(
        self,
        *,
        url: str,
        host: str,
        limit: int,
        form: dict[str, str] | None = None,
    ) -> bytes:
        """Return a fixture or raise a configured service error."""
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class FakeResponse:
    """Implement a minimal context manager for bounded HTTP client tests."""

    def __init__(self, *, data: bytes) -> None:
        """Keep the fake response payload."""
        self.data = data

    def __enter__(self) -> Self:
        """Return this fake as a response stream."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit without suppressing errors."""

    def read(self, length: int) -> bytes:
        """Honour the byte ceiling requested by the client."""
        return self.data[:length]


class FakeOpener:
    """Record a request and return one fake response."""

    def __init__(self, *, response: bytes) -> None:
        """Keep fake bytes for the next request."""
        self.response = response
        self.request: Request | None = None

    def open(self, request: Request, timeout: float) -> FakeResponse:
        """Store the request for assertions and respond without I/O."""
        self.request = request
        return FakeResponse(data=self.response)


class SequenceOpener:
    """Produce transient HTTP responses in a predictable order."""

    def __init__(self, *, responses: list[bytes | Exception]) -> None:
        """Keep the response sequence and a count of network attempts."""
        self.responses = responses
        self.calls = 0

    def open(self, request: Request, timeout: float) -> FakeResponse:
        """Return the next controlled response or raise its HTTP error."""
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return FakeResponse(data=response)


class IdentifierTests(unittest.TestCase):
    """Check typed input validation and sequence matching inputs."""

    def test_types_and_invalid_values(self) -> None:
        """Accept explicit protein IDs and reject a nucleotide or URL."""
        self.assertEqual(
            downloader.validate_identifier(
                value="xp_001234.2", identifier_type="refseq-protein"
            ),
            "XP_001234.2",
        )
        self.assertEqual(
            downloader.validate_identifier(value="7157", identifier_type="gene-id"),
            "7157",
        )
        for value in ("NM_00123.1", "https://example.org/a", "../bad"):
            with self.subTest(value=value), self.assertRaises(downloader.DownloadError):
                downloader.validate_identifier(
                    value=value, identifier_type="refseq-protein"
                )

    def test_input_file_and_fasta(self) -> None:
        """Deduplicate IDs and read exact FASTA records by original ID."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "ids.txt").write_text(
                "# comment\nNP_001.1\nNP_001.1\nXP_002.2\n", encoding="utf-8"
            )
            identifiers = downloader.read_identifiers(
                identifier_type="refseq-protein",
                ids=(),
                ids_file=path / "ids.txt",
            )
            self.assertEqual(identifiers, ("NP_001.1", "XP_002.2"))
            (path / "sequences.faa").write_text(
                ">NP_001.1 some description\nMAK\nT*\n>XP_002.2\nMSS\n",
                encoding="utf-8",
            )
            self.assertEqual(
                downloader.read_fasta(
                    path=path / "sequences.faa", identifiers=identifiers
                ),
                {"NP_001.1": "MAKT", "XP_002.2": "MSS"},
            )

    def test_empty_fasta_header_is_rejected(self) -> None:
        """Do not propagate IndexError from malformed user FASTA input."""
        with tempfile.TemporaryDirectory() as directory:
            fasta = Path(directory) / "bad.faa"
            fasta.write_text(">\nMAKT\n", encoding="utf-8")
            with self.assertRaisesRegex(downloader.DownloadError, "Empty"):
                downloader.read_fasta(path=fasta, identifiers=("NP_001.1",))


class MappingTests(unittest.TestCase):
    """Check asynchronous UniProt ID mapping and all-result retention."""

    def test_gene_mapping_preserves_many_accessions_and_unmapped(self) -> None:
        """Retain all mappings while reporting a gene with no UniProt entry."""
        base = downloader.ID_MAPPING_URL
        client = StubClient(
            responses={
                f"{base}/run": b'{"jobId":"ABC123"}',
                f"{base}/status/ABC123": b'{"jobStatus":"FINISHED"}',
                f"{base}/stream/ABC123": json.dumps(
                    {
                        "results": [
                            {"from": "7157", "to": {"primaryAccession": "P12345"}},
                            {"from": "7157", "to": {"primaryAccession": "Q12345"}},
                            {"from": "7157", "to": {"primaryAccession": "P12345"}},
                        ],
                        "failedIds": ["999"],
                    }
                ).encode("utf-8"),
            }
        )
        self.assertEqual(
            downloader.map_identifiers(
                identifiers=("7157", "999"), identifier_type="gene-id", client=client
            ),
            {"7157": ("P12345", "Q12345"), "999": ()},
        )
        self.assertEqual(client.calls[-1], f"{base}/stream/ABC123")

    def test_failed_mapping_job_is_an_error(self) -> None:
        """Never classify a service failure as a biological no-model result."""
        base = downloader.ID_MAPPING_URL
        client = StubClient(
            responses={
                f"{base}/run": b'{"jobId":"ABC123"}',
                f"{base}/status/ABC123": b'{"jobStatus":"FAILED"}',
            }
        )
        with self.assertRaisesRegex(downloader.DownloadError, "failed"):
            downloader.map_identifiers(
                identifiers=("NP_001.1",),
                identifier_type="refseq-protein",
                client=client,
            )

    def test_direct_uniprot_requires_no_mapping_service(self) -> None:
        """A canonical UniProt accession passes straight to AlphaFold DB."""
        client = StubClient(responses={})
        self.assertEqual(
            downloader.map_identifiers(
                identifiers=("P12345",), identifier_type="uniprot", client=client
            ),
            {"P12345": ("P12345",)},
        )
        self.assertEqual(client.calls, [])


class ModelTests(unittest.TestCase):
    """Check canonical model selection and file safety."""

    def test_select_latest_canonical_without_guessing_fragment(self) -> None:
        """Prefer the latest F1 version and ignore unrelated fragments."""
        old = json.loads(
            model_metadata(
                model_url="https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v4.cif"
            )
        )[0]
        new = json.loads(model_metadata())[0]
        other = dict(new, entryId="AF-P12345-F2")
        reference = downloader.select_model(
            payload=json.dumps([other, old, new]).encode("utf-8"),
            accession="P12345",
            model_format="cif",
        )
        self.assertEqual(reference.version, 6)
        self.assertEqual(reference.sequence, "MAKT")

    def test_reject_untrusted_file_url(self) -> None:
        """A service response cannot redirect model bytes to a different host."""
        with self.assertRaisesRegex(downloader.DownloadError, "Unapproved"):
            downloader.select_model(
                payload=model_metadata(
                    model_url="https://other.example/files/AF-P12345-F1-model_v6.cif"
                ),
                accession="P12345",
                model_format="cif",
            )
        handler = downloader._BoundedRedirects()
        request = Request("https://alphafold.ebi.ac.uk/api/prediction/P12345")
        with self.assertRaisesRegex(downloader.DownloadError, "Unapproved"):
            handler.redirect_request(
                request, None, 302, "Redirect", {}, "https://other.example/a"
            )

    def test_coordinate_validation(self) -> None:
        """Accept a model-like response and reject an HTML error page."""
        downloader.validate_model_bytes(payload=MODEL, model_format="cif")
        downloader.validate_model_bytes(payload=PDB_MODEL, model_format="pdb")
        with self.assertRaises(downloader.DownloadError):
            downloader.validate_model_bytes(
                payload=b"<html>not a model</html>", model_format="cif"
            )

    def test_http_client_enforces_byte_limit(self) -> None:
        """A download larger than the configured ceiling is rejected."""
        client = downloader.HttpClient(timeout_seconds=2, retries=0)
        opener = FakeOpener(response=b"abcde")
        client._opener = opener
        with self.assertRaisesRegex(downloader.DownloadError, "exceeds"):
            client.read(
                url="https://alphafold.ebi.ac.uk/files/file.cif",
                host=downloader.AFDB_HOST,
                limit=3,
            )
        self.assertEqual(opener.request.get_method(), "GET")

    def test_http_client_retries_temporary_503(self) -> None:
        """Retry a temporary service error and retain the model response."""
        url = "https://alphafold.ebi.ac.uk/files/model.cif"
        opener = SequenceOpener(
            responses=[HTTPError(url, 503, "Unavailable", {}, None), MODEL]
        )
        client = downloader.HttpClient(timeout_seconds=2, retries=1)
        client._opener = opener
        with patch("fetch_alphafold_models.time.sleep") as sleeper:
            result = client.read(url=url, host=downloader.AFDB_HOST, limit=1000)
        self.assertEqual(result, MODEL)
        self.assertEqual(opener.calls, 2)
        sleeper.assert_called_once_with(1)

    def test_conflicting_latest_records_are_rejected(self) -> None:
        """Avoid selecting an arbitrary model among conflicting same-version rows."""
        record = json.loads(model_metadata())[0]
        altered = dict(record, uniprotSequence="OTHER")
        with self.assertRaisesRegex(downloader.DownloadError, "Conflicting"):
            downloader.select_model(
                payload=json.dumps([record, altered]).encode("utf-8"),
                accession="P12345",
                model_format="cif",
            )


class EndToEndTests(unittest.TestCase):
    """Check manifest, cached assets, explicit failure outcomes, and CLI."""

    def test_two_ids_reuse_one_verified_model_and_pae(self) -> None:
        """Write one model and PAE with separate auditable ID rows."""
        api = f"{downloader.AFDB_API_URL}/P12345"
        model_url = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.cif"
        pae_url = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-predicted_aligned_error_v6.json"
        client = StubClient(
            responses={
                api: model_metadata(pae_url=pae_url),
                model_url: MODEL,
                pae_url: b'[{"predicted_aligned_error":[[0.0]]}]',
            }
        )

        def mapper(**kwargs: object) -> dict[str, tuple[str, ...]]:
            """Map two input IDs to one UniProt model for cache checking."""
            return {"NP_001.1": ("P12345",), "NP_002.1": ("P12345",)}

        with tempfile.TemporaryDirectory() as directory:
            output = downloader.prepare_output(directory=Path(directory) / "result")
            rows = downloader.download_models(
                identifiers=("NP_001.1", "NP_002.1"),
                identifier_type="refseq-protein",
                output_dir=output,
                model_format="cif",
                include_pae=True,
                expected_sequences={"NP_001.1": "MAKT", "NP_002.1": "MAKT"},
                client=client,
                mapper=mapper,
            )
            self.assertEqual([row["status"] for row in rows], ["DOWNLOADED"] * 2)
            self.assertEqual(rows[0]["metadata_sequence_check"], "MATCH")
            self.assertEqual(rows[0]["model_path"], rows[1]["model_path"])
            self.assertEqual(rows[0]["pae_status"], "DOWNLOADED")
            self.assertEqual(client.calls.count(model_url), 1)
            self.assertEqual((output / rows[0]["model_path"]).read_bytes(), MODEL)
            with (output / "manifest.tsv").open(encoding="utf-8") as stream:
                manifest = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(manifest), 2)
            self.assertEqual(manifest[1]["input_id"], "NP_002.1")

    def test_sequence_mismatch_does_not_download_coordinates(self) -> None:
        """Fail closed when an expected input sequence differs from metadata."""
        api = f"{downloader.AFDB_API_URL}/P12345"
        client = StubClient(responses={api: model_metadata()})

        def mapper(**kwargs: object) -> dict[str, tuple[str, ...]]:
            """Return one controlled RefSeq-to-UniProt mapping."""
            return {"NP_001.1": ("P12345",)}

        with tempfile.TemporaryDirectory() as directory:
            output = downloader.prepare_output(directory=Path(directory) / "result")
            rows = downloader.download_models(
                identifiers=("NP_001.1",),
                identifier_type="refseq-protein",
                output_dir=output,
                model_format="cif",
                include_pae=False,
                expected_sequences={"NP_001.1": "OTHER"},
                client=client,
                mapper=mapper,
            )
            self.assertEqual(rows[0]["status"], "SEQUENCE_MISMATCH")
            self.assertEqual(list((output / "models").iterdir()), [])

    def test_missing_model_and_unmapped_are_distinct(self) -> None:
        """Preserve unavailable and unmapped as separate non-failure outcomes."""
        api = f"{downloader.AFDB_API_URL}/P12345"
        client = StubClient(responses={api: downloader.ModelUnavailable("HTTP 404")})

        def mapper(**kwargs: object) -> dict[str, tuple[str, ...]]:
            """Return one model accession and one missing ID mapping."""
            return {"7157": ("P12345",), "999": ()}

        with tempfile.TemporaryDirectory() as directory:
            output = downloader.prepare_output(directory=Path(directory) / "result")
            rows = downloader.download_models(
                identifiers=("7157", "999"),
                identifier_type="gene-id",
                output_dir=output,
                model_format="cif",
                include_pae=False,
                expected_sequences={},
                client=client,
                mapper=mapper,
            )
            self.assertEqual(
                [row["status"] for row in rows],
                ["MODEL_NOT_AVAILABLE", "UNMAPPED"],
            )

    def test_mapping_failure_is_written_for_every_input(self) -> None:
        """Preserve service failure evidence even when mapping cannot start."""
        client = StubClient(responses={})

        def mapper(**kwargs: object) -> dict[str, tuple[str, ...]]:
            """Simulate UniProt being temporarily unavailable."""
            raise downloader.DownloadError("service temporarily unavailable")

        with tempfile.TemporaryDirectory() as directory:
            output = downloader.prepare_output(directory=Path(directory) / "result")
            rows = downloader.download_models(
                identifiers=("7157", "999"),
                identifier_type="gene-id",
                output_dir=output,
                model_format="cif",
                include_pae=False,
                expected_sequences={},
                client=client,
                mapper=mapper,
            )
            self.assertEqual([row["status"] for row in rows], ["FAILED"] * 2)
            self.assertIn(
                "service temporarily unavailable",
                (output / "manifest.tsv").read_text(encoding="utf-8"),
            )

    def test_many_gene_mappings_require_an_explicit_limit(self) -> None:
        """Avoid an unexpectedly large Gene ID download before any model GET."""
        client = StubClient(responses={})

        def mapper(**kwargs: object) -> dict[str, tuple[str, ...]]:
            """Return two candidate proteins for a single NCBI Gene ID."""
            return {"7157": ("P12345", "Q12345")}

        with tempfile.TemporaryDirectory() as directory:
            output = downloader.prepare_output(directory=Path(directory) / "result")
            rows = downloader.download_models(
                identifiers=("7157",),
                identifier_type="gene-id",
                output_dir=output,
                model_format="cif",
                include_pae=False,
                expected_sequences={},
                client=client,
                max_models=1,
                mapper=mapper,
            )
            self.assertEqual(rows[0]["status"], "FAILED")
            self.assertIn("above the --max-models", rows[0]["detail"])
            self.assertEqual(client.calls, [])

    def test_existing_output_is_not_overwritten(self) -> None:
        """Keep an existing user's files untouched when a path is reused."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "result"
            root.mkdir()
            (root / "important.txt").write_text("keep me", encoding="utf-8")
            with self.assertRaisesRegex(downloader.DownloadError, "new or empty"):
                downloader.prepare_output(directory=root)
            self.assertEqual(
                (root / "important.txt").read_text(encoding="utf-8"), "keep me"
            )

    def test_cli_validation_is_not_a_traceback(self) -> None:
        """Return a clear exit status for a wrongly typed identifier."""
        with tempfile.TemporaryDirectory() as directory:
            result = downloader.main(
                argv=[
                    "--id-type",
                    "refseq-protein",
                    "--id",
                    "NM_001.1",
                    "--output-dir",
                    str(Path(directory) / "unused"),
                ]
            )
            self.assertEqual(result, 2)
            self.assertFalse((Path(directory) / "unused").exists())

    def test_cli_success_writes_model_and_manifest(self) -> None:
        """Run a whole UniProt CLI request using stubbed service responses."""
        api = f"{downloader.AFDB_API_URL}/P12345"
        model_url = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.pdb"
        client = StubClient(responses={api: model_metadata(), model_url: PDB_MODEL})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with patch("fetch_alphafold_models.HttpClient", return_value=client):
                result = downloader.main(
                    argv=[
                        "--id-type",
                        "uniprot",
                        "--id",
                        "P12345",
                        "--format",
                        "pdb",
                        "--output-dir",
                        str(output),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertTrue((output / "models" / Path(model_url).name).exists())
            self.assertIn("DOWNLOADED", (output / "manifest.tsv").read_text())

    def test_requested_pae_failure_is_visible(self) -> None:
        """Keep a valid model when optional PAE fails, marking the PAE error."""
        api = f"{downloader.AFDB_API_URL}/P12345"
        model_url = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.cif"
        pae_url = "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-pae_v6.json"
        client = StubClient(
            responses={
                api: model_metadata(pae_url=pae_url),
                model_url: MODEL,
                pae_url: downloader.ModelUnavailable("PAE HTTP 404"),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with patch("fetch_alphafold_models.HttpClient", return_value=client):
                result = downloader.main(
                    argv=[
                        "--id-type",
                        "uniprot",
                        "--id",
                        "P12345",
                        "--include-pae",
                        "--output-dir",
                        str(output),
                    ]
                )
            self.assertEqual(result, 1)
            with (output / "manifest.tsv").open(encoding="utf-8") as stream:
                row = next(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(row["status"], "DOWNLOADED")
            self.assertEqual(row["pae_status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
