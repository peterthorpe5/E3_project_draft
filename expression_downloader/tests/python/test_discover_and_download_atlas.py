#!/usr/bin/env python3
"""Unit tests for Python-first Expression Atlas downloader."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "inst" / "python" / "discover_and_download_atlas.py"
)
SPEC = importlib.util.spec_from_file_location("discover_and_download_atlas", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["discover_and_download_atlas"] = MODULE
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TestDiscoverAndDownloadAtlas(unittest.TestCase):
    """Tests for the Python-first Expression Atlas helper."""

    def test_parse_bool_values(self):
        """Boolean CLI values should be parsed robustly."""

        self.assertTrue(MODULE.parse_bool("true"))
        self.assertFalse(MODULE.parse_bool("False"))
        self.assertFalse(MODULE.parse_bool("0"))
        self.assertTrue(MODULE.parse_bool("1"))
        self.assertTrue(MODULE.parse_bool(None, default=True))
        self.assertTrue(MODULE.parse_bool(True))
        self.assertFalse(MODULE.parse_bool("", default=False))
        with self.assertRaisesRegex(ValueError, "Cannot parse boolean"):
            MODULE.parse_bool("perhaps")

    def test_extract_accessions_from_mixed_text(self):
        """Accession extraction should work for XML, JSON or HTML-like text."""

        text = "<accession>E-MTAB-5915</accession> {'accession': 'E-GEOD-12345'} E-MTAB-5915"
        self.assertEqual(
            MODULE.extract_accessions_from_text(text),
            ["E-MTAB-5915", "E-GEOD-12345"],
        )

    def test_build_remote_files_uses_expected_names(self):
        """FTP manifest construction should produce expected Atlas filenames."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = MODULE.CandidateExperiment(
                species_column="Zea_mays",
                atlas_species_query="Zea mays",
                search_term="RNA-seq",
                accession="E-MTAB-5915",
                search_url="test",
                source="unit_test",
            )
            files = MODULE.build_remote_files(
                candidate=candidate,
                output_dir=Path(temporary_dir),
                download_file_types=(
                    "tpms",
                    "fpkms",
                    "sample_metadata",
                    "configuration_xml",
                ),
            )
            names = {item.file_name for item in files}

        self.assertIn("E-MTAB-5915-tpms.tsv", names)
        self.assertIn("E-MTAB-5915-fpkms.tsv", names)
        self.assertIn("E-MTAB-5915.condensed-sdrf.tsv", names)
        self.assertIn("E-MTAB-5915-configuration.xml", names)

    def test_species_file_parsing(self):
        """Species files should ignore blank lines and comments."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            species_file = Path(temporary_dir) / "species.txt"
            species_file.write_text(
                "# comment\nArabidopsis_thaliana\n\nZea_mays\n",
                encoding="utf-8",
            )
            records = MODULE.read_species_file(species_file)

        self.assertEqual(
            [record.species_column for record in records],
            ["Arabidopsis_thaliana", "Zea_mays"],
        )
        self.assertEqual(records[0].atlas_species_query, "Arabidopsis thaliana")

    def test_species_matching_allows_subspecies(self):
        """Species matching should accept conservative subspecies labels."""

        record = MODULE.SpeciesRecord(
            species_column="Zea_mays",
            scientific_name="Zea mays",
            atlas_species_query="Zea mays",
        )

        self.assertTrue(
            MODULE.species_matches_record(
                observed_species="Zea mays subsp. mays",
                species_record=record,
            )
        )
        self.assertFalse(
            MODULE.species_matches_record(
                observed_species="Oryza sativa",
                species_record=record,
            )
        )

    def test_extract_species_from_sdrf_text(self):
        """SDRF parsing should extract organism metadata."""

        text = (
            "Source Name\tCharacteristics[organism]\tAssay Name\n"
            "sample1\tArabidopsis thaliana\tassay1\n"
            "sample2\tArabidopsis thaliana\tassay2\n"
        )

        self.assertEqual(
            MODULE.extract_species_from_sdrf_text(metadata_text=text),
            ["Arabidopsis thaliana"],
        )

    def test_list_ftp_accessions_from_text_regex_helper(self):
        """FTP-style index text should yield accessions via the shared regex."""

        text = '<a href="E-MTAB-4342/">E-MTAB-4342/</a> <a href="E-GEOD-1/">x</a>'
        self.assertEqual(
            MODULE.extract_accessions_from_text(text),
            ["E-MTAB-4342", "E-GEOD-1"],
        )

    def test_overrides_and_manifest_helpers_are_lossless(self):
        """Species overrides and resumable manifests should preserve intent."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            override = root / "override.tsv"
            override.write_text(
                "species_column\tscientific_name\tatlas_species_query\t"
                "include\tpriority\n"
                "Zea_mays\tZea mays\tmaize\tfalse\tmanual\n",
                encoding="utf-8",
            )
            records = [
                MODULE.SpeciesRecord("Zea_mays", "Zea mays", "Zea mays"),
                MODULE.SpeciesRecord("Oryza_sativa", "Oryza sativa", "Oryza sativa"),
            ]
            updated = MODULE.apply_species_overrides(records, override)
            self.assertFalse(updated[0].include)
            self.assertEqual(updated[0].atlas_species_query, "maize")
            self.assertTrue(updated[1].include)
            self.assertEqual(MODULE.apply_species_overrides(records, None), records)

            manifest = root / "downloads.tsv"
            fields = ["url", "local_path", "success"]
            MODULE.write_tsv(
                manifest,
                [{"url": "u1", "local_path": "p1", "success": "true"}],
                fields,
            )
            MODULE.append_tsv(
                manifest,
                {"url": "u2", "local_path": "p2", "success": "false"},
                fields,
            )
            self.assertEqual(
                MODULE.read_existing_download_manifest(manifest),
                {("u1", "p1")},
            )
            self.assertEqual(
                MODULE.read_existing_download_manifest(root / "missing.tsv"),
                set(),
            )

    def test_remote_filename_codec_and_listing(self):
        """FTP listings should retain only recognised, de-duplicated files."""
        mapping = {
            "tpms": ["E-TEST-1-query-results.tpms.tsv"],
            "sample_metadata": ["E-TEST-1.condensed-sdrf.tsv"],
        }
        encoded = MODULE.encode_remote_file_names(mapping)
        self.assertEqual(MODULE.decode_remote_file_names(encoded), mapping)
        self.assertEqual(MODULE.encode_remote_file_names({}), "")
        self.assertEqual(MODULE.decode_remote_file_names("not-json"), {})
        self.assertEqual(MODULE.decode_remote_file_names("[]"), {})
        self.assertEqual(
            MODULE.decode_remote_file_names('{"tpms":"one.tsv"}'),
            {"tpms": ["one.tsv"]},
        )

        listing = (
            '<a href="../">parent</a>'
            '<a href="subdir/">dir</a>'
            '<a href="E-TEST-1-query-results.tpms.tsv">TPM</a>'
            '<a href="E-TEST-1-query-results.tpms.tsv">duplicate</a>'
            '<a href="notes.txt">ignored</a>'
        )
        with mock.patch.object(MODULE, "fetch_optional_text", return_value=listing):
            files = MODULE.list_experiment_ftp_files(
                "E-TEST-1",
                "https://example.test/experiments",
                1,
                0,
            )
        self.assertEqual(files, {"tpms": ["E-TEST-1-query-results.tpms.tsv"]})

    def test_search_and_ftp_retry_behaviour(self):
        """Discovery should de-duplicate successes and fail closed after retries."""
        species = MODULE.SpeciesRecord("Zea_mays", "Zea mays", "Zea mays")
        responses = [RuntimeError("temporary"), "E-MTAB-1 E-MTAB-1", "E-MTAB-1"]
        with (
            mock.patch.object(MODULE, "request_text", side_effect=responses),
            mock.patch.object(
                MODULE.time,
                "sleep",
            ),
        ):
            results = MODULE.search_species_accessions(
                species,
                ("RNA-seq",),
                timeout_seconds=1,
                retries=1,
                log_file=None,
            )
        self.assertEqual([record.accession for record in results], ["E-MTAB-1"])

        with (
            mock.patch.object(
                MODULE,
                "request_text",
                side_effect=[RuntimeError("temporary"), "E-MTAB-1 E-GEOD-2"],
            ),
            mock.patch.object(MODULE.time, "sleep"),
        ):
            self.assertEqual(
                MODULE.list_ftp_accessions("https://example.test", 1, 1),
                ["E-MTAB-1", "E-GEOD-2"],
            )
        with (
            mock.patch.object(
                MODULE,
                "request_text",
                side_effect=RuntimeError("offline"),
            ),
            mock.patch.object(MODULE.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not read FTP index"):
                MODULE.list_ftp_accessions("https://example.test", 1, 1)
            self.assertEqual(
                MODULE.fetch_optional_text("https://example.test", 1, 1),
                "",
            )

    def test_ftp_scan_uses_metadata_and_enforces_per_species_limit(self):
        """FTP discovery should require expression files and verified species."""
        species = [MODULE.SpeciesRecord("Zea_mays", "Zea mays", "Zea mays")]
        files = {
            "tpms": ["matrix.tpms.tsv"],
            "sample_metadata": ["metadata.tsv"],
        }
        metadata = "Source\tCharacteristics[organism]\nsample\tZea mays subsp. mays\n"
        with (
            mock.patch.object(
                MODULE,
                "list_ftp_accessions",
                return_value=["E-TEST-1", "E-TEST-2", "E-TEST-3"],
            ),
            mock.patch.object(
                MODULE,
                "list_experiment_ftp_files",
                side_effect=[{}, files, files],
            ),
            mock.patch.object(
                MODULE,
                "fetch_optional_text",
                return_value=metadata,
            ),
        ):
            records = MODULE.discover_candidates_by_ftp_scan(
                species_records=species,
                output_dir=Path("unused"),
                ftp_index_url="https://example.test",
                expression_file_types=("tpms",),
                timeout_seconds=1,
                retries=0,
                max_experiments_per_species=1,
                ftp_scan_max_accessions=0,
                log_file=None,
            )
        self.assertEqual([record.accession for record in records], ["E-TEST-2"])
        self.assertEqual(
            MODULE.decode_remote_file_names(records[0].remote_file_names),
            files,
        )

    def test_species_extractors_and_page_fallback(self):
        """Missing SDRF organism columns should fall back to the experiment page."""
        self.assertEqual(MODULE.extract_species_from_sdrf_text(""), [])
        self.assertEqual(MODULE.extract_species_from_sdrf_text("Sample\nA\n"), [])
        self.assertEqual(MODULE.extract_species_from_experiment_page(""), [])
        self.assertEqual(
            MODULE.extract_species_from_experiment_page(
                "Organism: Zea   mays<br>\nOrganism: Zea mays<"
            ),
            ["Zea mays"],
        )
        species = [MODULE.SpeciesRecord("Zea_mays", "Zea mays", "Zea mays")]
        self.assertEqual(
            MODULE.match_species_records(["Zea mays", "Zea mays"], species),
            species,
        )

    def test_remote_check_covers_head_range_and_http_failures(self):
        """Remote validation should use HEAD first and a bounded range fallback."""
        head = mock.MagicMock()
        head.status = 200
        head.headers = {"Content-Length": "10"}
        head.__enter__.return_value = head
        with mock.patch.object(MODULE.urllib.request, "urlopen", return_value=head):
            self.assertEqual(
                MODULE.check_remote_file("https://example.test/file", 1),
                (True, True, 200, 10, "HEAD"),
            )

        empty_head = mock.MagicMock()
        empty_head.status = 200
        empty_head.headers = {}
        empty_head.__enter__.return_value = empty_head
        range_response = mock.MagicMock()
        range_response.status = 206
        range_response.read.return_value = b"x"
        range_response.__enter__.return_value = range_response
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[empty_head, range_response],
        ):
            self.assertEqual(
                MODULE.check_remote_file("https://example.test/file", 1),
                (True, True, 206, None, "GET_RANGE"),
            )

        error = MODULE.urllib.error.HTTPError(
            "https://example.test/file",
            404,
            "not found",
            {},
            None,
        )
        with mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=error):
            self.assertEqual(
                MODULE.check_remote_file("https://example.test/file", 1),
                (False, False, 404, None, "HEAD"),
            )

    def test_download_is_atomic_reusable_and_removes_failed_partial(self):
        """Downloads should publish atomically and never retain a partial file."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            destination = root / "downloads" / "matrix.tsv"
            remote = MODULE.RemoteFile(
                "Zea_mays",
                "Zea mays",
                "E-TEST-1",
                "tpms",
                "matrix.tsv",
                "https://example.test/matrix.tsv",
                destination,
            )
            response = mock.MagicMock()
            response.read.side_effect = [b"matrix", b""]
            response.__enter__.return_value = response
            with mock.patch.object(
                MODULE.urllib.request,
                "urlopen",
                return_value=response,
            ):
                success = MODULE.download_file(remote, False, 1, 0, 1)
            self.assertEqual(success, (True, "downloaded", 6))
            self.assertEqual(destination.read_bytes(), b"matrix")
            self.assertEqual(
                MODULE.download_file(remote, False, 1, 0, 1),
                (True, "skipped_existing_local_file", 6),
            )

            destination.unlink()
            with (
                mock.patch.object(
                    MODULE.urllib.request,
                    "urlopen",
                    side_effect=RuntimeError("offline"),
                ),
                mock.patch.object(MODULE.time, "sleep"),
            ):
                failed = MODULE.download_file(remote, True, 1, 1, 1)
            self.assertFalse(failed[0])
            self.assertIn("offline", failed[1])
            self.assertEqual(list(destination.parent.glob("*.partial")), [])

    def test_request_text_csv_options_and_search_urls(self):
        """Low-level request and option helpers should preserve exact text."""
        response = mock.MagicMock()
        response.read.return_value = "Zea mays".encode()
        response.__enter__.return_value = response
        with mock.patch.object(MODULE.urllib.request, "urlopen", return_value=response):
            self.assertEqual(
                MODULE.request_text("https://example.test", 1),
                "Zea mays",
            )
        urls = MODULE.build_arrayexpress_search_urls("Zea mays", "RNA-seq")
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("Zea+mays" in url for url in urls))
        self.assertEqual(MODULE.parse_csv_option(" a, b ,,", ("x",)), ("a", "b"))
        self.assertEqual(MODULE.parse_csv_option("", ("x",)), ("x",))


class TestFtpFilenameDiscovery(unittest.TestCase):
    """Tests for variable Expression Atlas FTP filename handling."""

    def test_detect_query_result_tpm_filename(self):
        """Baseline query-result TPM filenames should be detected as TPMs."""

        self.assertEqual(
            MODULE.detect_atlas_file_type("E-MTAB-4342-query-results.tpms.tsv"),
            "tpms",
        )
        self.assertEqual(
            MODULE.detect_atlas_file_type("E-MTAB-4342-query-results.fpkms.tsv"),
            "fpkms",
        )

    def test_detect_configuration_xml(self):
        """Authoritative assay-group XML should be selected for download."""

        self.assertEqual(
            MODULE.detect_atlas_file_type("E-MTAB-4342-configuration.xml"),
            "configuration_xml",
        )

    def test_file_sha256_matches_known_answer(self):
        """Downloaded-source provenance should use a verified SHA-256 digest."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "source.tsv"
            path.write_bytes(b"abc")

            digest = MODULE.file_sha256(path, chunk_bytes=2)

        self.assertEqual(
            digest,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_extract_href_values_from_ftp_listing(self):
        """FTP directory listings should expose href filenames."""

        html = (
            '<a href="E-MTAB-4342-query-results.tpms.tsv">TPM</a> '
            '<a href="E-MTAB-4342.condensed-sdrf.tsv">SDRF</a>'
        )
        self.assertEqual(
            MODULE.extract_href_values(html),
            [
                "E-MTAB-4342-query-results.tpms.tsv",
                "E-MTAB-4342.condensed-sdrf.tsv",
            ],
        )

    def test_build_remote_files_uses_actual_ftp_names_when_available(self):
        """Actual FTP filenames should override older fallback templates."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = MODULE.CandidateExperiment(
                species_column="Zea_mays",
                atlas_species_query="Zea mays",
                search_term="ftp_scan",
                accession="E-MTAB-4342",
                search_url="test",
                source="unit_test",
                remote_file_names=MODULE.encode_remote_file_names(
                    {
                        "tpms": ["E-MTAB-4342-query-results.tpms.tsv"],
                        "sample_metadata": ["E-MTAB-4342.condensed-sdrf.tsv"],
                    }
                ),
            )
            files = MODULE.build_remote_files(
                candidate=candidate,
                output_dir=Path(temporary_dir),
                download_file_types=("tpms", "sample_metadata"),
            )
            names = {item.file_name for item in files}

        self.assertIn("E-MTAB-4342-query-results.tpms.tsv", names)
        self.assertNotIn("E-MTAB-4342-tpms.tsv", names)

    def test_optional_files_are_not_misclassified_as_expression_matrices(self):
        """Marker/coexpression/bedGraph extras should not be imported as TPM/FPKM matrices."""

        self.assertEqual(
            MODULE.detect_atlas_file_type("E-CURD-31-fpkms-markers.tsv"),
            "fpkms_markers",
        )
        self.assertEqual(
            MODULE.detect_atlas_file_type("E-CURD-31-tpms-coexpressions.tsv.gz"),
            "tpms_coexpressions",
        )
        self.assertEqual(
            MODULE.detect_atlas_file_type("E-CURD-31.g1.genes.expressions_fpkms.bedGraph"),
            "fpkms_bedgraph",
        )
        self.assertEqual(
            MODULE.detect_atlas_file_type("E-CURD-31-tpms.tsv"),
            "tpms",
        )

    @staticmethod
    def _candidate() -> object:
        """Return one deterministic discovery candidate."""
        return MODULE.CandidateExperiment(
            species_column="Zea_mays",
            atlas_species_query="Zea mays",
            search_term="ftp_scan",
            accession="E-TEST-1",
            search_url="fixture",
            source="unit_test",
        )

    def test_main_requires_a_complete_download_contract(self):
        """TPM, sample metadata and configuration XML must all download."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            species = root / "species.txt"
            output = root / "output"
            species.write_text("Zea_mays\n", encoding="utf-8")

            def download(remote_file, **_kwargs):
                """Materialise one selected source without network access."""
                remote_file.local_path.parent.mkdir(parents=True, exist_ok=True)
                remote_file.local_path.write_text(
                    f"fixture for {remote_file.file_type}\n",
                    encoding="utf-8",
                )
                return True, "downloaded", remote_file.local_path.stat().st_size

            with (
                mock.patch.object(
                    MODULE,
                    "discover_candidates_by_ftp_scan",
                    return_value=[self._candidate()],
                ),
                mock.patch.object(
                    MODULE,
                    "check_remote_file",
                    return_value=(True, True, 200, 100, "HEAD"),
                ),
                mock.patch.object(MODULE, "download_file", side_effect=download),
            ):
                status = MODULE.main(
                    [
                        "--species_file",
                        str(species),
                        "--output_dir",
                        str(output),
                        "--expression_file_types",
                        "tpms,fpkms",
                        "--download_file_types",
                        "tpms,sample_metadata,configuration_xml",
                    ]
                )

            self.assertEqual(status, 0)
            downloaded = (output / "manifests" / "atlas_downloaded_files.tsv").read_text(
                encoding="utf-8"
            )
            self.assertIn("configuration_xml", downloaded)
            self.assertIn("sample_metadata", downloaded)
            self.assertEqual(downloaded.count("\ttrue\t"), 3)

    def test_main_fails_when_required_metadata_is_unavailable(self):
        """An expression matrix alone must not be published as complete."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            species = root / "species.txt"
            output = root / "output"
            species.write_text("Zea_mays\n", encoding="utf-8")

            def remote_status(url, **_kwargs):
                """Report the configuration XML as unavailable."""
                if url.endswith("configuration.xml"):
                    return False, False, 404, 0, "HEAD"
                return True, True, 200, 100, "HEAD"

            def download(remote_file, **_kwargs):
                """Materialise remotely available files."""
                remote_file.local_path.parent.mkdir(parents=True, exist_ok=True)
                remote_file.local_path.write_text("fixture\n", encoding="utf-8")
                return True, "downloaded", remote_file.local_path.stat().st_size

            with (
                mock.patch.object(
                    MODULE,
                    "discover_candidates_by_ftp_scan",
                    return_value=[self._candidate()],
                ),
                mock.patch.object(
                    MODULE,
                    "check_remote_file",
                    side_effect=remote_status,
                ),
                mock.patch.object(MODULE, "download_file", side_effect=download),
            ):
                status = MODULE.main(
                    [
                        "--species_file",
                        str(species),
                        "--output_dir",
                        str(output),
                        "--expression_file_types",
                        "tpms",
                        "--download_file_types",
                        "tpms,sample_metadata,configuration_xml",
                    ]
                )

            self.assertEqual(status, 1)
            summary = (output / "manifests" / "atlas_python_summary.tsv").read_text(
                encoding="utf-8"
            )
            self.assertIn("incomplete_expression_experiments\t1", summary)

    def test_main_fails_when_one_selected_download_fails(self):
        """A failed selected file must dominate otherwise successful work."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            species = root / "species.txt"
            output = root / "output"
            species.write_text("Zea_mays\n", encoding="utf-8")

            def download(remote_file, **_kwargs):
                """Fail only the authoritative XML download."""
                if remote_file.file_type == "configuration_xml":
                    return False, "download_failed", None
                remote_file.local_path.parent.mkdir(parents=True, exist_ok=True)
                remote_file.local_path.write_text("fixture\n", encoding="utf-8")
                return True, "downloaded", remote_file.local_path.stat().st_size

            with (
                mock.patch.object(
                    MODULE,
                    "discover_candidates_by_ftp_scan",
                    return_value=[self._candidate()],
                ),
                mock.patch.object(
                    MODULE,
                    "check_remote_file",
                    return_value=(True, True, 200, 100, "HEAD"),
                ),
                mock.patch.object(MODULE, "download_file", side_effect=download),
            ):
                status = MODULE.main(
                    [
                        "--species_file",
                        str(species),
                        "--output_dir",
                        str(output),
                        "--expression_file_types",
                        "tpms",
                        "--download_file_types",
                        "tpms,sample_metadata,configuration_xml",
                    ]
                )

            self.assertEqual(status, 1)

    def test_arrayexpress_manual_override_and_optional_main_branches(self):
        """Alternative discovery and explicit manual inputs should remain complete."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            species = root / "species.txt"
            override = root / "override.tsv"
            manual = root / "manual.tsv"
            output = root / "output"
            species.write_text("Zea_mays\nOryza_sativa\n", encoding="utf-8")
            override.write_text(
                "species_column\tinclude\nOryza_sativa\tfalse\n",
                encoding="utf-8",
            )
            manual.write_text(
                "species_column\texperiment_accession\nZea_mays\tE-MANUAL-1\n",
                encoding="utf-8",
            )
            searched = MODULE.CandidateExperiment(
                "Zea_mays",
                "Zea mays",
                "RNA-seq",
                "E-SEARCH-1",
                "fixture",
                "unit_test",
            )

            def download(remote_file, **_kwargs):
                """Materialise every selected primary or optional source."""
                remote_file.local_path.parent.mkdir(parents=True, exist_ok=True)
                remote_file.local_path.write_text("fixture\n", encoding="utf-8")
                return True, "downloaded", remote_file.local_path.stat().st_size

            with (
                mock.patch.object(
                    MODULE,
                    "search_species_accessions",
                    return_value=[searched],
                ),
                mock.patch.object(
                    MODULE,
                    "check_remote_file",
                    return_value=(True, True, 200, 100, "HEAD"),
                ),
                mock.patch.object(MODULE, "download_file", side_effect=download),
            ):
                status = MODULE.main(
                    [
                        "--species_file",
                        str(species),
                        "--override_tsv",
                        str(override),
                        "--manual_experiment_tsv",
                        str(manual),
                        "--output_dir",
                        str(output),
                        "--discovery_backend",
                        "arrayexpress_api",
                        "--expression_file_types",
                        "tpms",
                        "--download_file_types",
                        "tpms,sample_metadata,configuration_xml",
                        "--include_optional_extras",
                        "true",
                        "--max_experiments_per_species",
                        "1",
                    ]
                )

            self.assertEqual(status, 0)
            candidates = (output / "manifests" / "atlas_candidate_experiments.tsv").read_text(
                encoding="utf-8"
            )
            self.assertIn("E-SEARCH-1", candidates)
            self.assertIn("E-MANUAL-1", candidates)
            registry = (output / "manifests" / "species_registry.tsv").read_text(encoding="utf-8")
            self.assertNotIn("Oryza_sativa", registry)

    def test_main_with_no_expression_experiment_returns_failure(self):
        """An empty discovery must still write manifests and return non-zero."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            species = root / "species.txt"
            output = root / "output"
            species.write_text("Zea_mays\n", encoding="utf-8")
            with mock.patch.object(
                MODULE,
                "discover_candidates_by_ftp_scan",
                return_value=[],
            ):
                status = MODULE.main(
                    [
                        "--species_file",
                        str(species),
                        "--output_dir",
                        str(output),
                    ]
                )
            self.assertEqual(status, 1)
            self.assertTrue((output / "manifests" / "atlas_downloaded_files.tsv").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
