"""Integration, command-line and inherited regression tests."""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from e3ligandability.cli import build_parser, main
from e3ligandability.config import deep_merge, DEFAULT_CONFIG
from e3ligandability.io_utils import read_accession_records
from e3ligandability.models import AccessionResult
from e3ligandability.pipeline import (
    _optional_float,
    metadata_from_input,
    parse_tool_outputs,
    preflight_external_tools,
    process_accession,
    resolve_alphafold_metadata,
    results_to_datasets,
    run_pipeline,
)
from e3ligandability.regression import (
    compare_legacy_metadata_row,
    find_legacy_model,
    parse_legacy_number,
    read_legacy_metadata,
    run_legacy_model_regression,
)
from e3ligandability.structure import parse_model_residues


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def make_executable(path: Path, text: str) -> Path:
    """Create an executable helper script."""

    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def make_fake_tools(root: Path) -> tuple[Path, Path]:
    """Create fake FPocket and P2Rank executables with deterministic output."""

    fpocket = make_executable(
        root / "fpocket",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"--version\" ]]; then\n"
        "  echo 'fpocket 4.2.2'\n"
        "fi\n"
        "exit 0\n",
    )
    pocket_fixture = FIXTURE_ROOT / "pocket1_atm.cif"
    prank = make_executable(
        root / "prank",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"-v\" ]]; then\n"
        "  echo 'P2Rank 2.5.1'\n"
        "  exit 0\n"
        "fi\n"
        "OUT=''\n"
        "for ((i=1; i<=$#; i++)); do\n"
        "  if [[ \"${!i}\" == '-o' ]]; then\n"
        "    j=$((i+1)); OUT=\"${!j}\"\n"
        "  fi\n"
        "done\n"
        "mkdir -p \"${OUT}/fpocket/model_out/pockets\"\n"
        "cat > \"${OUT}/fpocket/model_out/model_info.txt\" <<'INFO'\n"
        "Pocket 1 :\n"
        "Score : 5.2\n"
        "Druggability Score : 0.8\n"
        "INFO\n"
        f"cp {pocket_fixture} \"${{OUT}}/fpocket/model_out/pockets/pocket1_atm.cif\"\n"
        "cat > \"${OUT}/model_predictions.csv\" <<'CSV'\n"
        "name,score,rank,old_rank,probability\n"
        "pocket1,9.1,1,1,0.95\n"
        "CSV\n",
    )
    return fpocket, prank


def local_config(fpocket: Path, prank: Path, run_tools: bool = True):
    """Return a network-free effective test configuration."""

    return deep_merge(
        DEFAULT_CONFIG,
        {
            "alphafold": {
                "query_api_for_local_models": False,
                "download_pae": False,
                "download_msa": False,
                "download_plddt_json": False,
            },
            "external_tools": {
                "run_fpocket_p2rank": run_tools,
                "fpocket_executable": str(fpocket),
                "p2rank_executable": str(prank),
                "required_fpocket_version_prefix": "4.2.2",
                "required_p2rank_version_prefix": "2.5.1",
                "p2rank_threads": 1,
            },
        },
    )


class RegressionTests(unittest.TestCase):
    """Test inherited metadata regression functions."""

    def test_legacy_read_parse_find_compare_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "Q1"
            model_dir.mkdir()
            model = model_dir / "AF-Q1-F1-model_v6.cif"
            shutil.copy2(FIXTURE_ROOT / "model.cif", model)
            metadata = root / "legacy.csv"
            metadata.write_text(
                "accession,globalMetricValue,fractionModToHigh\n"
                "Q1,78.3333333333,0.6666666667\n"
                "Q2,NA,NA\n",
                encoding="utf-8",
            )
            rows = read_legacy_metadata(metadata)
            self.assertEqual(len(rows), 2)
            self.assertIsNone(parse_legacy_number("NA"))
            self.assertEqual(parse_legacy_number("1.5"), 1.5)
            self.assertEqual(find_legacy_model(root, "Q1"), model.resolve())
            comparison = compare_legacy_metadata_row(
                rows[0],
                model,
                0.01,
                0.01,
            )
            self.assertEqual(comparison["status"], "PASS")
            results = run_legacy_model_regression(root, metadata, 0.01, 0.01)
            self.assertEqual([record["status"] for record in results], ["PASS", "PASS"])


class PipelineHelperTests(unittest.TestCase):
    """Test orchestration helper functions."""

    def test_optional_float_and_input_metadata(self) -> None:
        self.assertIsNone(_optional_float("NA"))
        self.assertEqual(_optional_float("1.2"), 1.2)
        metadata = metadata_from_input(
            "Q1",
            {
                "global_metric_value": "80",
                "fraction_plddt_confident": "0.2",
                "fraction_plddt_very_high": "0.5",
                "cif_url": "https://example.org/x.cif",
            },
        )
        self.assertEqual(metadata["global_metric_value"], 80.0)
        self.assertAlmostEqual(metadata["api_fraction_residues_ge_70"], 0.7)

    def test_resolve_metadata_local_and_preflight_disabled(self) -> None:
        fpocket = Path("/not/used")
        config = local_config(fpocket, fpocket, run_tools=False)
        metadata = resolve_alphafold_metadata(
            "Q1",
            {"model_path": str(FIXTURE_ROOT / "model.cif")},
            config,
            session=None,
        )
        self.assertEqual(metadata["selection_rule"], "input_record")
        resolved = preflight_external_tools(config)
        self.assertEqual(resolved, (None, None, []))

    def test_results_to_datasets(self) -> None:
        result = AccessionResult(accession="Q1", status="SUCCESS")
        result.metadata = {
            "accession": "Q1",
            "asset_manifest": [{"path": "x"}],
            "joined_pockets": [{"pocket_number": 1}],
        }
        result.model_quality = {"accession": "Q1"}
        datasets = results_to_datasets([result])
        self.assertEqual(len(datasets["asset_manifest"]), 1)
        self.assertEqual(len(datasets["joined_pockets"]), 1)
        self.assertEqual(datasets["accession_status"][0]["status"], "SUCCESS")

    def test_parse_tool_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "tool"
            pockets = output / "fpocket" / "model_out" / "pockets"
            pockets.mkdir(parents=True)
            shutil.copy2(FIXTURE_ROOT / "pocket1_atm.cif", pockets / "pocket1_atm.cif")
            (output / "fpocket" / "model_out" / "model_info.txt").write_text(
                "Pocket 1 :\nScore : 5.2\n",
                encoding="utf-8",
            )
            (output / "model_predictions.csv").write_text(
                "name,score,rank,old_rank\npocket1,9.1,1,1\n",
                encoding="utf-8",
            )
            config = local_config(Path("x"), Path("y"), run_tools=False)
            parsed = parse_tool_outputs(
                "TEST",
                output,
                parse_model_residues(FIXTURE_ROOT / "model.cif"),
                config,
            )
            self.assertEqual([len(part) for part in parsed], [1, 1, 1, 2, 1])


class EndToEndTests(unittest.TestCase):
    """Run the complete pipeline and CLI with synthetic external tools."""

    def test_process_accession_and_run_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fpocket, prank = make_fake_tools(root)
            config = local_config(fpocket, prank)
            input_path = root / "input.tsv"
            input_path.write_text(
                "accession\tmodel_path\n"
                f"TEST\t{FIXTURE_ROOT / 'model.cif'}\n",
                encoding="utf-8",
            )
            records = read_accession_records(input_path)
            output = root / "output"
            outcome = run_pipeline(
                input_path=input_path,
                accession_records=records,
                output_root=output,
                config=config,
            )
            self.assertTrue(outcome["success"])
            self.assertEqual(outcome["failed_accessions"], [])
            self.assertTrue((output / "duckdb" / "e3_ligandability.duckdb").is_file())
            self.assertEqual(
                outcome["datasets"]["pocket_quality"][0]["mapped_pocket_residue_count"],
                2,
            )

            direct = process_accession(
                input_record=records[0],
                accession_column="accession",
                output_root=root / "direct",
                config=config,
                session=type("Session", (), {"close": lambda self: None})(),
                fpocket_executable=fpocket,
                p2rank_executable=prank,
            )
            self.assertEqual(direct.status, "SUCCESS")

    def test_cli_run_and_validate_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fpocket, prank = make_fake_tools(root)
            config_path = root / "config.yaml"
            config_path.write_text(
                "alphafold:\n"
                "  query_api_for_local_models: false\n"
                "  download_pae: false\n"
                "  download_msa: false\n"
                "  download_plddt_json: false\n"
                "external_tools:\n"
                "  run_fpocket_p2rank: true\n"
                f"  fpocket_executable: {fpocket}\n"
                f"  p2rank_executable: {prank}\n"
                "  required_fpocket_version_prefix: '4.2.2'\n"
                "  required_p2rank_version_prefix: '2.5.1'\n"
                "  p2rank_threads: 1\n",
                encoding="utf-8",
            )
            input_path = root / "input.tsv"
            input_path.write_text(
                "accession\tmodel_path\n"
                f"TEST\t{FIXTURE_ROOT / 'model.cif'}\n",
                encoding="utf-8",
            )
            output = root / "cli_output"
            self.assertEqual(
                main(
                    [
                        "run",
                        "--input",
                        str(input_path),
                        "--output-dir",
                        str(output),
                        "--config",
                        str(config_path),
                    ]
                ),
                0,
            )
            self.assertTrue((output / "provenance" / "run_manifest.json").is_file())

            legacy_root = root / "legacy"
            model_dir = legacy_root / "TEST"
            model_dir.mkdir(parents=True)
            shutil.copy2(
                FIXTURE_ROOT / "model.cif",
                model_dir / "AF-TEST-F1-model_v6.cif",
            )
            metadata = root / "legacy.csv"
            metadata.write_text(
                "accession,globalMetricValue,fractionModToHigh\n"
                "TEST,78.3333333333,0.6666666667\n",
                encoding="utf-8",
            )
            regression_output = root / "regression"
            self.assertEqual(
                main(
                    [
                        "validate-legacy",
                        "--testing-root",
                        str(legacy_root),
                        "--metadata-csv",
                        str(metadata),
                        "--output-dir",
                        str(regression_output),
                    ]
                ),
                0,
            )
            self.assertTrue(
                (regression_output / "legacy_model_regression.tsv").is_file()
            )

    def test_parser_has_commands(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("validate-legacy", help_text)
        self.assertIn("inspect-tools", help_text)


if __name__ == "__main__":
    unittest.main()
