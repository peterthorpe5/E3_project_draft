"""Unit tests for AlphaFold metadata and file materialisation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import requests

from e3ligandability.alphafold import (
    AlphaFoldNotFoundError,
    DownloadValidationError,
    _url_filename,
    build_retry_session,
    copy_atomic,
    download_atomic,
    materialise_model_assets,
    normalise_prediction_metadata,
    query_prediction_metadata,
    reuse_valid_file,
    select_prediction,
    validate_a3m_file,
    validate_cif_file,
    validate_json_file,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


class FakeResponse:
    """Minimal requests response used by unit tests."""

    def __init__(self, status: int, payload=None, content: bytes = b"") -> None:
        self.status_code = status
        self._payload = payload
        self._content = content

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"status={self.status_code}")
            error.response = self
            raise error

    def iter_content(self, chunk_size: int = 1):
        del chunk_size
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False


class FakeSession:
    """Session returning a predetermined sequence of responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("No fake response remains")
        return self.responses.pop(0)


class AlphaFoldTests(unittest.TestCase):
    """Test metadata selection and validated asset handling."""

    def test_build_retry_session(self) -> None:
        session = build_retry_session(2, 0.1)
        self.assertIn("User-Agent", session.headers)
        self.assertIn("https://", session.adapters)
        session.close()

    def test_query_prediction_metadata_success_and_not_found(self) -> None:
        session = FakeSession([FakeResponse(200, payload=[{"x": 1}])])
        payload = query_prediction_metadata(
            session,
            "https://example.org/api",
            "Q1",
            10,
        )
        self.assertEqual(payload, [{"x": 1}])
        self.assertTrue(session.calls[0][0].endswith("/Q1"))

        missing = FakeSession([FakeResponse(404, payload=[])])
        with self.assertRaises(AlphaFoldNotFoundError):
            query_prediction_metadata(missing, "https://example.org", "Q1", 10)

        empty = FakeSession([FakeResponse(200, payload=[])])
        with self.assertRaises(AlphaFoldNotFoundError):
            query_prediction_metadata(empty, "https://example.org", "Q1", 10)

        invalid = FakeSession([FakeResponse(200, payload={"x": 1})])
        with self.assertRaises(ValueError):
            query_prediction_metadata(invalid, "https://example.org", "Q1", 10)

    def test_select_and_normalise_prediction(self) -> None:
        predictions = [
            {
                "uniprotAccession": "Q1",
                "cifUrl": "https://x/AF-Q1-F1-model_v5.cif",
                "fractionPlddtConfident": 0.2,
                "fractionPlddtVeryHigh": 0.5,
            },
            {
                "uniprotAccession": "Q1",
                "cifUrl": "https://x/AF-Q1-F1-model_v6.cif",
                "fractionPlddtConfident": 0.3,
                "fractionPlddtVeryHigh": 0.6,
                "globalMetricValue": 88.0,
            },
        ]
        selected = select_prediction(predictions, "Q1")
        self.assertTrue(selected["cifUrl"].endswith("v6.cif"))
        self.assertEqual(selected["selection_prediction_count"], 2)
        normalised = normalise_prediction_metadata("Q1", selected)
        self.assertAlmostEqual(normalised["api_fraction_residues_ge_70"], 0.9)
        self.assertEqual(normalised["global_metric_value"], 88.0)
        with self.assertRaises(ValueError):
            select_prediction([], "Q1")

    def test_validators(self) -> None:
        validate_cif_file(FIXTURE_ROOT / "model.cif")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "x.json"
            json_path.write_text(json.dumps({"x": 1}), encoding="utf-8")
            validate_json_file(json_path)
            a3m = root / "x.a3m"
            a3m.write_text(">Q1\nAAAA\n", encoding="utf-8")
            validate_a3m_file(a3m)
            bad = root / "bad.cif"
            bad.write_text("not a cif", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_cif_file(bad)
            empty_json = root / "empty.json"
            empty_json.write_text("[]", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_json_file(empty_json)
            bad_a3m = root / "bad.a3m"
            bad_a3m.write_text("AAAA", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_a3m_file(bad_a3m)

    def test_url_filename(self) -> None:
        self.assertEqual(_url_filename("https://x/y.cif", "fallback"), "y.cif")
        self.assertEqual(_url_filename("https://x/", "fallback"), "fallback")

    def test_download_copy_and_reuse(self) -> None:
        content = (FIXTURE_ROOT / "model.cif").read_bytes()
        session = FakeSession([FakeResponse(200, content=content)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloaded = root / "downloaded.cif"
            record = download_atomic(
                session,
                "https://example.org/model.cif",
                downloaded,
                10,
                validate_cif_file,
            )
            self.assertEqual(record["action"], "downloaded")
            self.assertTrue(downloaded.is_file())
            reused = reuse_valid_file(downloaded, validate_cif_file)
            self.assertEqual(reused["action"], "reused")

            copied = root / "copied.cif"
            copy_record = copy_atomic(
                FIXTURE_ROOT / "model.cif",
                copied,
                validate_cif_file,
            )
            self.assertEqual(copy_record["action"], "copied")
            self.assertIsNone(reuse_valid_file(root / "missing", validate_cif_file))

    def test_materialise_local_model_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path, manifests = materialise_model_assets(
                accession="TEST",
                input_record={"model_path": str(FIXTURE_ROOT / "model.cif")},
                metadata={},
                output_directory=root,
                session=FakeSession([]),
                timeout_seconds=10,
                reuse_existing=True,
                download_pae=False,
                download_msa=False,
                download_plddt_json=False,
            )
            self.assertTrue(model_path.is_file())
            self.assertEqual(manifests[0]["action"], "copied")
            _, manifests2 = materialise_model_assets(
                accession="TEST",
                input_record={"model_path": str(FIXTURE_ROOT / "model.cif")},
                metadata={},
                output_directory=root,
                session=FakeSession([]),
                timeout_seconds=10,
                reuse_existing=True,
                download_pae=False,
                download_msa=False,
                download_plddt_json=False,
            )
            self.assertEqual(manifests2[0]["action"], "reused")


if __name__ == "__main__":
    unittest.main()
