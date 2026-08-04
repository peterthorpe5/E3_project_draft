#!/usr/bin/env python3
"""Unit tests for the bounded Expression Atlas diagnostic snapshot."""

from __future__ import annotations

import csv
import importlib.util
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "inst" / "python" / "snapshot_expression_evidence.py"
)
SPEC = importlib.util.spec_from_file_location(
    "snapshot_expression_evidence",
    SCRIPT_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["snapshot_expression_evidence"] = MODULE
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SnapshotFixture:
    """Small expression and workflow tree for archive tests."""

    def __init__(self, root: Path) -> None:
        """Create deterministic local evidence.

        Args:
            root: Temporary test root.
        """

        self.expression_root = root / "expression"
        self.workflow_root = root / "workflow"
        manifests = self.expression_root / "manifests"
        downloads = self.expression_root / "downloads" / "Zea_mays" / "E-MTAB-5915"
        stage_tables = self.workflow_root / "07_expression" / "tables"
        stage_qc = self.workflow_root / "07_expression" / "qc"
        plan = self.workflow_root / "00_plan"
        for path in (manifests, downloads, stage_tables, stage_qc, plan):
            path.mkdir(parents=True, exist_ok=True)
        (manifests / "atlas_downloaded_files.tsv").write_text(
            "experiment_accession\tlocal_path\nE-MTAB-5915\tfile\n",
            encoding="utf-8",
        )
        (downloads / "E-MTAB-5915.condensed-sdrf.tsv").write_text(
            "Sample Characteristic[organism part]\tleaf\n",
            encoding="utf-8",
        )
        (downloads / "E-MTAB-5915-analysis-methods.tsv").write_text(
            "method\tiRAP\n",
            encoding="utf-8",
        )
        (downloads / "E-MTAB-5915-tpms.tsv").write_text(
            "Gene ID\tGene Name\tleaf\n"
            "Zm00001\tGENE1\t2.0\n"
            "Zm00002\tGENE2\t0.0\n"
            "Zm00003\tGENE3\t4.0\n",
            encoding="utf-8",
        )
        (stage_tables / "candidate_expression_summary.tsv").write_text(
            "member_accession\tmapping_status\nP1\tNOT_MAPPED\n",
            encoding="utf-8",
        )
        (stage_qc / "expression_validation.tsv").write_text(
            "unique_expression_mapping_count\t0\n",
            encoding="utf-8",
        )
        (plan / "resolved_config.yaml").write_text(
            "analysis:\n  expression:\n    minimum_expression_value: 0.0\n",
            encoding="utf-8",
        )


class TestExpressionEvidenceSnapshot(unittest.TestCase):
    """Validate local collection, page retrieval and archive safety."""

    def test_boolean_and_matrix_detection(self) -> None:
        """CLI Booleans and matrix names should be strict."""

        self.assertTrue(MODULE.parse_boolean("true"))
        self.assertFalse(MODULE.parse_boolean("No"))
        with self.assertRaisesRegex(Exception, "Expected true or false"):
            MODULE.parse_boolean("perhaps")
        self.assertTrue(MODULE.is_expression_matrix(Path("E-X-tpms.tsv.gz")))
        self.assertFalse(MODULE.is_expression_matrix(Path("E-X-tpms-markers.tsv")))

    def test_matrix_preview_is_bounded(self) -> None:
        """Preview should retain a header and only the requested data rows."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = SnapshotFixture(Path(temporary_dir))
            source = next(fixture.expression_root.rglob("*-tpms.tsv"))
            destination = Path(temporary_dir) / "preview.tsv"
            MODULE.write_matrix_preview(source, destination, maximum_rows=2)
            lines = destination.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[-1].split("\t")[0], "Zm00002")
            with self.assertRaisesRegex(ValueError, "positive"):
                MODULE.write_matrix_preview(
                    source,
                    destination,
                    maximum_rows=0,
                )

    def test_remote_retrieval_uses_only_bounded_templates(self) -> None:
        """Each accession should request the three explicit official pages."""

        calls: list[str] = []

        def fetcher(url: str, timeout_seconds: int):
            calls.append(url)
            self.assertEqual(timeout_seconds, 4)
            return b"<html>fixture</html>", "text/html"

        with tempfile.TemporaryDirectory() as temporary_dir:
            records, requests = MODULE.retrieve_remote_pages(
                accessions=("E-MTAB-5915",),
                snapshot_root=Path(temporary_dir),
                timeout_seconds=4,
                retries=0,
                delay_seconds=0,
                fetcher=fetcher,
            )
            self.assertEqual(len(records), 3)
            self.assertEqual(len(requests), 3)
            self.assertEqual(len(calls), len(MODULE.REMOTE_PAGE_TEMPLATES))
            self.assertTrue(all(row["success"] == "true" for row in requests))

    def test_offline_archive_contains_diagnostic_contract(self) -> None:
        """Offline build should package metadata, audit tables and previews."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            fixture = SnapshotFixture(root)
            archive_path = root / "snapshot.tar.gz"
            result = MODULE.build_snapshot(
                expression_root=fixture.expression_root,
                workflow_run_root=fixture.workflow_root,
                output_archive=archive_path,
                fetch_pages=False,
                preview_rows=2,
                timeout_seconds=3,
                retries=0,
                delay_seconds=0,
                overwrite=False,
            )
            self.assertEqual(result, archive_path)
            self.assertTrue(archive_path.is_file())
            with tarfile.open(archive_path, "r:gz") as archive:
                names = set(archive.getnames())
                manifest_name = "expression_evidence_snapshot/provenance/snapshot_manifest.tsv"
                self.assertIn(manifest_name, names)
                self.assertIn("expression_evidence_snapshot/README.txt", names)
                self.assertTrue(any("matrix_previews" in name for name in names))
                self.assertTrue(any("candidate_expression_summary.tsv" in name for name in names))
                handle = archive.extractfile(manifest_name)
                assert handle is not None
                manifest_text = handle.read().decode("utf-8")
                rows = list(
                    csv.DictReader(
                        manifest_text.splitlines(),
                        delimiter="\t",
                    )
                )
                self.assertTrue(any(row["category"] == "stage_07_qc" for row in rows))
            with self.assertRaises(FileExistsError):
                MODULE.build_snapshot(
                    expression_root=fixture.expression_root,
                    workflow_run_root=None,
                    output_archive=archive_path,
                    fetch_pages=False,
                    preview_rows=1,
                    timeout_seconds=1,
                    retries=0,
                    delay_seconds=0,
                    overwrite=False,
                )

    def test_cli_builds_an_offline_snapshot(self) -> None:
        """The command-line surface should invoke the same bounded contract."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            fixture = SnapshotFixture(root)
            archive = root / "cli-snapshot.tar.gz"

            status = MODULE.main(
                [
                    "--expression-root",
                    str(fixture.expression_root),
                    "--workflow-run-root",
                    str(fixture.workflow_root),
                    "--output-archive",
                    str(archive),
                    "--fetch-pages",
                    "false",
                    "--preview-rows",
                    "1",
                    "--timeout-seconds",
                    "1",
                    "--retries",
                    "0",
                    "--delay-seconds",
                    "0",
                    "--verbose",
                ]
            )

            self.assertEqual(status, 0)
            self.assertTrue(archive.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
