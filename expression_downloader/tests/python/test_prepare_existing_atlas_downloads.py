#!/usr/bin/env python3
"""Tests for strict preparation of historical Atlas downloads."""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "inst"
    / "python"
    / "prepare_existing_atlas_downloads.py"
)
SPEC = importlib.util.spec_from_file_location("prepare_existing_atlas_downloads", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["prepare_existing_atlas_downloads"] = MODULE
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_legacy_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a representative historical manifest fixture."""
    fieldnames = [
        "species_column",
        "atlas_species_query",
        "experiment_accession",
        "file_type",
        "file_name",
        "url",
        "local_path",
        "action",
        "success",
        "local_bytes",
        "checked_at",
        "sha256",
    ]
    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def legacy_rows() -> list[dict[str, str]]:
    """Return one complete legacy experiment without configuration XML."""
    base_url = (
        "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/"
        "experiments/E-TEST-1/"
    )
    common = {
        "species_column": "Zea_mays",
        "atlas_species_query": "Zea mays",
        "experiment_accession": "E-TEST-1",
        "action": "downloaded",
        "success": "true",
    }
    return [
        {
            **common,
            "file_type": "tpms",
            "file_name": "E-TEST-1-tpms.tsv",
            "url": base_url + "E-TEST-1-tpms.tsv",
            "local_path": "../analysis/downloads/Zea_mays/E-TEST-1/E-TEST-1-tpms.tsv",
        },
        {
            **common,
            "file_type": "sample_metadata",
            "file_name": "E-TEST-1.condensed-sdrf.tsv",
            "url": base_url + "E-TEST-1.condensed-sdrf.tsv",
            "local_path": (
                "../analysis/downloads/Zea_mays/E-TEST-1/"
                "E-TEST-1.condensed-sdrf.tsv"
            ),
        },
    ]


class TestPrepareExistingAtlasDownloads(unittest.TestCase):
    """Known-answer and corruption tests for legacy source preparation."""

    def setUp(self) -> None:
        """Create a representative immutable raw-download tree."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.raw_root = self.root / "raw"
        self.supplement_root = self.root / "supplement"
        self.experiment_root = self.raw_root / "downloads" / "Zea_mays" / "E-TEST-1"
        self.experiment_root.mkdir(parents=True)
        (self.experiment_root / "E-TEST-1-tpms.tsv").write_text(
            "Gene ID\tGene Name\tg1\nZm1\tGENE1\t1,2,3,4,5\n",
            encoding="utf-8",
        )
        (self.experiment_root / "E-TEST-1.condensed-sdrf.tsv").write_text(
            "Assay Group\tCharacteristics[organism part]\ng1\tleaf\n",
            encoding="utf-8",
        )
        self.manifest = self.root / "legacy.tsv"
        write_legacy_manifest(self.manifest, legacy_rows())

    def tearDown(self) -> None:
        """Remove temporary test sources."""
        self.temporary.cleanup()

    @staticmethod
    def write_configuration(**kwargs) -> str:
        """Create the mocked configuration download at its destination."""
        destination = kwargs["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            '<configuration><assay_group id="g1" label="leaf">'
            "<assay>ERR1</assay></assay_group></configuration>",
            encoding="utf-8",
        )
        return "downloaded"

    def test_prepare_rebases_hashes_and_supplements_legacy_sources(self) -> None:
        """Relative legacy paths must become checksum-recorded absolute paths."""
        with mock.patch.object(
            MODULE,
            "download_atomic",
            side_effect=self.write_configuration,
        ) as downloader:
            sources = MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=2,
            )

        self.assertEqual(len(sources), 3)
        self.assertEqual({source.file_type for source in sources}, {
            "tpms",
            "sample_metadata",
            "configuration_xml",
        })
        self.assertTrue(all(source.local_path.is_absolute() for source in sources))
        self.assertTrue(all(len(source.sha256) == 64 for source in sources))
        matrix = next(source for source in sources if source.file_type == "tpms")
        self.assertEqual(matrix.local_path, (self.experiment_root / matrix.file_name).resolve())
        configuration = next(
            source for source in sources if source.file_type == "configuration_xml"
        )
        self.assertTrue(str(configuration.local_path).startswith(str(self.supplement_root)))
        downloader.assert_called_once()

    def test_published_manifest_is_atomic_tab_separated_and_checksum_complete(self) -> None:
        """Prepared publication must preserve the strict manifest contract."""
        with mock.patch.object(
            MODULE,
            "download_atomic",
            side_effect=self.write_configuration,
        ):
            sources = MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=0,
            )
        output = self.root / "manifests" / "prepared.tsv"
        MODULE.write_manifest_atomic(path=output, sources=sources)

        with output.open(mode="r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["success"] == "true" for row in rows))
        self.assertTrue(all(MODULE.SHA256_PATTERN.fullmatch(row["sha256"]) for row in rows))
        self.assertEqual(list(output.parent.glob("*.partial")), [])

    def test_missing_raw_source_fails_closed(self) -> None:
        """A legacy success claim must not hide a missing local file."""
        (self.experiment_root / "E-TEST-1-tpms.tsv").unlink()
        with self.assertRaisesRegex(ValueError, "Raw source is missing or empty"):
            MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=0,
            )

    def test_checksum_mismatch_fails_closed(self) -> None:
        """A stale historical digest must be rejected before publication."""
        rows = legacy_rows()
        rows[0]["sha256"] = "0" * 64
        write_legacy_manifest(self.manifest, rows)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=0,
            )

    def test_missing_configuration_cannot_be_silently_accepted(self) -> None:
        """The strict source contract must require configuration XML."""
        with self.assertRaisesRegex(ValueError, "Configuration XML is absent"):
            MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=False,
                timeout_seconds=30,
                retries=0,
            )

    def test_malformed_manifest_and_unsafe_components_are_rejected(self) -> None:
        """Comma-separated or traversal-like inputs must fail closed."""
        malformed = self.root / "malformed.tsv"
        malformed.write_text("species_column,experiment_accession\nZea_mays,E-TEST-1\n")
        with self.assertRaisesRegex(ValueError, "lacks required tab-separated columns"):
            MODULE.read_manifest(malformed)

        rows = legacy_rows()
        rows[0]["species_column"] = "../Zea_mays"
        write_legacy_manifest(self.manifest, rows)
        with self.assertRaisesRegex(ValueError, "Invalid species_column"):
            MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=0,
            )

    def test_download_atomic_is_https_only_and_reuses_non_empty_file(self) -> None:
        """Configuration acquisition must reject HTTP and preserve valid files."""
        destination = self.root / "config.xml"
        with self.assertRaisesRegex(ValueError, "must be an HTTPS URL"):
            MODULE.download_atomic(
                url="http://example.org/config.xml",
                destination=destination,
                timeout_seconds=1,
                retries=0,
            )
        destination.write_text("<configuration/>", encoding="utf-8")
        self.assertEqual(
            MODULE.download_atomic(
                url="https://example.org/config.xml",
                destination=destination,
                timeout_seconds=1,
                retries=0,
            ),
            "reused_existing_supplement",
        )

    def test_download_atomic_publishes_complete_response(self) -> None:
        """A successful response must be atomically written in full."""
        destination = self.root / "new" / "config.xml"
        response = io.BytesIO(b"<configuration/>")
        with mock.patch.object(MODULE.urllib.request, "urlopen", return_value=response):
            action = MODULE.download_atomic(
                url="https://example.org/config.xml",
                destination=destination,
                timeout_seconds=1,
                retries=0,
            )
        self.assertEqual(action, "downloaded")
        self.assertEqual(destination.read_bytes(), b"<configuration/>")
        self.assertEqual(list(destination.parent.glob("*.partial")), [])

    def test_main_validates_numeric_options(self) -> None:
        """Nonsensical timeout and retry values must fail before I/O."""
        with self.assertRaisesRegex(SystemExit, "timeout_seconds"):
            MODULE.main(
                [
                    "--source_manifest", str(self.manifest),
                    "--raw_root", str(self.raw_root),
                    "--supplement_root", str(self.supplement_root),
                    "--output_manifest", str(self.root / "output.tsv"),
                    "--timeout_seconds", "0",
                ]
            )
        with self.assertRaisesRegex(SystemExit, "retries"):
            MODULE.main(
                [
                    "--source_manifest", str(self.manifest),
                    "--raw_root", str(self.raw_root),
                    "--supplement_root", str(self.supplement_root),
                    "--output_manifest", str(self.root / "output.tsv"),
                    "--retries", "-1",
                ]
            )

    def test_main_publishes_a_complete_prepared_manifest(self) -> None:
        """The public CLI should run the verified preparation contract."""
        output = self.root / "prepared.tsv"
        with mock.patch.object(
            MODULE,
            "download_atomic",
            side_effect=self.write_configuration,
        ):
            status = MODULE.main(
                [
                    "--source_manifest", str(self.manifest),
                    "--raw_root", str(self.raw_root),
                    "--supplement_root", str(self.supplement_root),
                    "--output_manifest", str(output),
                    "--download_missing_configuration", "true",
                    "--timeout_seconds", "5",
                    "--retries", "0",
                ]
            )
        self.assertEqual(status, 0)
        self.assertTrue(output.is_file())
        with output.open(mode="r", encoding="utf-8", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle, delimiter="\t"))), 3)

    def test_helper_boundaries_are_explicit(self) -> None:
        """Boolean, filename, checksum and URL edge cases should be covered."""
        self.assertTrue(MODULE.parse_bool(True))
        self.assertTrue(MODULE.parse_bool("yes"))
        self.assertFalse(MODULE.parse_bool("no"))
        self.assertTrue(MODULE.parse_bool("", default=True))
        with self.assertRaisesRegex(ValueError, "Cannot parse Boolean"):
            MODULE.parse_bool("perhaps")

        fallback_row = {"local_path": "/tmp/file.tsv", "file_name": ""}
        self.assertEqual(MODULE.row_file_name(fallback_row), "file.tsv")
        with self.assertRaisesRegex(ValueError, "Invalid source filename"):
            MODULE.row_file_name({"file_name": "../file.tsv"})

        matrix = self.experiment_root / "E-TEST-1-tpms.tsv"
        with self.assertRaisesRegex(ValueError, "Malformed source SHA-256"):
            MODULE.validate_source(path=matrix, expected_sha256="bad")
        fallback_url = MODULE.configuration_url("E-TEST-1", [{"url": ""}])
        self.assertTrue(fallback_url.endswith("/E-TEST-1-configuration.xml"))

    def test_empty_or_expression_free_manifest_fails_closed(self) -> None:
        """Preparation must require a real raw root and selected matrices."""
        with self.assertRaisesRegex(ValueError, "Raw root does not exist"):
            MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.root / "absent",
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=0,
            )

        rows = legacy_rows()
        rows[0]["success"] = "false"
        write_legacy_manifest(self.manifest, rows)
        with self.assertRaisesRegex(ValueError, "no successful TPM/FPKM"):
            MODULE.prepare_existing_sources(
                source_manifest=self.manifest,
                raw_root=self.raw_root,
                supplement_root=self.supplement_root,
                download_missing_configuration=True,
                timeout_seconds=30,
                retries=0,
            )

        header_only = self.root / "header_only.tsv"
        header_only.write_text(
            "species_column\texperiment_accession\tfile_type\tlocal_path\tsuccess\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "contains no data rows"):
            MODULE.read_manifest(header_only)

    def test_failed_configuration_download_removes_partial_file(self) -> None:
        """Repeated remote errors must not leave a publishable supplement."""
        destination = self.root / "failed" / "config.xml"
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=MODULE.urllib.error.URLError("offline"),
        ), mock.patch.object(MODULE.time, "sleep") as sleeper:
            with self.assertRaisesRegex(ValueError, "Failed to download"):
                MODULE.download_atomic(
                    url="https://example.org/config.xml",
                    destination=destination,
                    timeout_seconds=1,
                    retries=1,
                )
        sleeper.assert_called_once()
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.glob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()
