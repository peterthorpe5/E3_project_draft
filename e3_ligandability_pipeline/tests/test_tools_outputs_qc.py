"""Tests for external tools, output publication, QC and provenance."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from e3ligandability.models import AccessionResult
from e3ligandability.outputs import (
    build_duckdb_from_parquet,
    inspect_duckdb_tables,
    publish_all_datasets,
    publish_dataset,
)
from e3ligandability.provenance import (
    build_run_manifest,
    capture_git_state,
    package_versions,
    utc_now_iso,
    write_run_manifest,
)
from e3ligandability.qc import (
    check_mapping_rows_match_quality_totals,
    check_model_threshold_flag,
    check_no_duplicate_mapping_rows,
    check_pocket_mapping_accounting,
    check_success_has_model_quality,
    check_unique_accessions,
    make_check,
    run_validation_checks,
)
from e3ligandability.tools import (
    ExternalToolError,
    capture_tool_version,
    check_required_version,
    resolve_executable,
    run_command,
    run_fpocket_rescore,
    write_single_model_dataset,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def make_executable(path: Path, text: str) -> Path:
    """Write a small executable used by tool-wrapper tests."""

    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class ToolTests(unittest.TestCase):
    """Test external executable resolution and command logging."""

    def test_resolve_capture_and_version_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = make_executable(
                Path(tmp) / "tool",
                "#!/usr/bin/env bash\necho 'tool 2.5.1'\n",
            )
            resolved = resolve_executable(str(tool))
            record = capture_tool_version(resolved)
            self.assertEqual(record["return_code"], 0)
            check_required_version(record, "2.5.1", "tool")
            with self.assertRaises(ExternalToolError):
                check_required_version(record, "9.9", "tool")
            with self.assertRaises(ExternalToolError):
                resolve_executable(str(Path(tmp) / "missing"))

    def test_run_command_success_failure_and_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            success = make_executable(
                root / "success",
                "#!/usr/bin/env bash\necho ok\necho err >&2\n",
            )
            record = run_command(
                [str(success)],
                root,
                root / "out.log",
                root / "err.log",
                10,
            )
            self.assertEqual(record["return_code"], 0)
            self.assertIn("ok", (root / "out.log").read_text())

            failure = make_executable(
                root / "failure",
                "#!/usr/bin/env bash\nexit 3\n",
            )
            with self.assertRaises(ExternalToolError):
                run_command(
                    [str(failure)],
                    root,
                    root / "fout.log",
                    root / "ferr.log",
                    10,
                )

            dataset = root / "model.ds"
            write_single_model_dataset(dataset, FIXTURE_ROOT / "model.cif")
            self.assertIn("model.cif", dataset.read_text())

    def test_run_fpocket_rescore_builds_expected_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fpocket = make_executable(
                root / "fpocket",
                "#!/usr/bin/env bash\nexit 0\n",
            )
            prank = make_executable(
                root / "prank",
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "OUT=''\n"
                "for ((i=1; i<=$#; i++)); do\n"
                "  if [[ \"${!i}\" == '-o' ]]; then\n"
                "    j=$((i+1)); OUT=\"${!j}\"\n"
                "  fi\n"
                "done\n"
                "mkdir -p \"${OUT}/fpocket/model_out\"\n"
                "touch \"${OUT}/fpocket/model_out/model_info.txt\"\n"
                "echo 'name,score' > \"${OUT}/model_predictions.csv\"\n",
            )
            record = run_fpocket_rescore(
                accession="TEST",
                model_path=FIXTURE_ROOT / "model.cif",
                output_directory=root / "out",
                fpocket_executable=fpocket,
                p2rank_executable=prank,
                p2rank_model="rescore_2024",
                threads=2,
                keep_fpocket_output=True,
                timeout_seconds=10,
            )
            self.assertIn("fpocket-rescore", record["command"])
            self.assertTrue(Path(record["dataset_path"]).is_file())


class OutputAndQcTests(unittest.TestCase):
    """Test publication, DuckDB materialisation and validation checks."""

    def setUp(self) -> None:
        self.status = [{"accession": "Q1", "status": "SUCCESS"}]
        self.quality = [
            {
                "accession": "Q1",
                "fraction_residues_ge_70": 0.8,
                "passes_model_confidence_threshold": True,
            }
        ]
        self.mapping = [
            {
                "accession": "Q1",
                "pocket_number": 1,
                "label_chain": "A",
                "label_seq_id": 1,
                "auth_chain": "A",
                "auth_seq_id": 1,
                "insertion_code": "",
            }
        ]
        self.pocket_quality = [
            {
                "accession": "Q1",
                "pocket_number": 1,
                "predicted_pocket_residue_count": 1,
                "mapped_pocket_residue_count": 1,
                "ambiguous_pocket_residue_count": 0,
                "unmapped_pocket_residue_count": 0,
            }
        ]

    def test_individual_qc_functions(self) -> None:
        self.assertEqual(make_check("x", True, 1, 1, "m")["status"], "PASS")
        self.assertEqual(check_unique_accessions(self.status)["status"], "PASS")
        self.assertEqual(
            check_success_has_model_quality(self.status, self.quality)["status"],
            "PASS",
        )
        self.assertEqual(
            check_model_threshold_flag(self.quality, 0.5)["status"],
            "PASS",
        )
        self.assertEqual(
            check_pocket_mapping_accounting(self.pocket_quality)["status"],
            "PASS",
        )
        self.assertEqual(
            check_mapping_rows_match_quality_totals(
                self.mapping,
                self.pocket_quality,
            )["status"],
            "PASS",
        )
        self.assertEqual(
            check_no_duplicate_mapping_rows(self.mapping)["status"],
            "PASS",
        )

    def test_complete_validation_contract(self) -> None:
        datasets = {
            "accession_status": self.status,
            "model_quality": self.quality,
            "pocket_residue_mappings": self.mapping,
            "pocket_quality": self.pocket_quality,
        }
        checks = run_validation_checks(datasets, 0.5)
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(check["status"] == "PASS" for check in checks))

    def test_publish_and_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = publish_all_datasets(
                {
                    "accession_status": self.status,
                    "validation": [make_check("x", True, 1, 1, "m")],
                },
                root,
                write_tsv=True,
                write_parquet=True,
            )
            parquet = [record for record in manifests if record["format"] == "parquet"]
            database = build_duckdb_from_parquet(
                parquet,
                root / "duckdb" / "resource.duckdb",
            )
            self.assertTrue(Path(database["path"]).is_file())
            counts = inspect_duckdb_tables(Path(database["path"]))
            self.assertEqual(counts["accession_status"], 1)
            self.assertEqual(counts["validation"], 1)
            self.assertEqual(publish_dataset("empty", [], root, True, True), [])
            with self.assertRaises(ValueError):
                publish_all_datasets({"unknown": []}, root, True, True)

    def test_accession_result_status_record(self) -> None:
        result = AccessionResult(accession="Q1", status="FAILED", message="x")
        self.assertEqual(result.status_record()["status"], "FAILED")


class ProvenanceTests(unittest.TestCase):
    """Test environment and run manifest capture."""

    def test_time_packages_and_git_state(self) -> None:
        self.assertIn("+00:00", utc_now_iso())
        versions = package_versions(["requests", "not-a-real-package-xyz"])
        self.assertIsNotNone(versions["requests"])
        self.assertIsNone(versions["not-a-real-package-xyz"])
        self.assertEqual(capture_git_state(None)["error"], "repository_not_supplied")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                capture_git_state(Path(tmp))["error"],
                "not_a_git_repository",
            )

    def test_build_and_write_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.txt"
            input_path.write_text("Q1\n", encoding="utf-8")
            manifest = build_run_manifest(
                input_path=input_path,
                output_root=root,
                config={"x": 1},
                started_at="start",
                finished_at="finish",
                datasets={"validation": [{"status": "PASS"}]},
                file_manifests=[],
                tool_versions=[],
                git_repository=None,
            )
            self.assertEqual(manifest["validation_pass_count"], 1)
            output = root / "manifest.json"
            write_run_manifest(output, manifest)
            self.assertEqual(
                json.loads(output.read_text())["resource_version"],
                "0.1.0",
            )


if __name__ == "__main__":
    unittest.main()
