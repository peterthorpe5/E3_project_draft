#!/usr/bin/env python3
"""Unit tests for Python-first Expression Atlas downloader."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "inst" / "python" / "discover_and_download_atlas.py"
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
                download_file_types=("tpms", "fpkms", "sample_metadata"),
            )
            names = {item.file_name for item in files}

        self.assertIn("E-MTAB-5915-tpms.tsv", names)
        self.assertIn("E-MTAB-5915-fpkms.tsv", names)
        self.assertIn("E-MTAB-5915.condensed-sdrf.tsv", names)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
