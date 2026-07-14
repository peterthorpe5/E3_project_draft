import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from e3_discovery.cli import (
    _print_json,
    _run_diamond_stage,
    build_parser,
    main,
    run_command,
)
from e3_discovery.diamond import SemanticVersion
from e3_discovery.pipeline import WorkflowPaths


def workflow_paths(root: Path) -> WorkflowPaths:
    return WorkflowPaths(
        root=root,
        combined_fasta=root / "combined.fasta",
        sequence_parquet=root / "sequences.parquet",
        sample_summary_tsv=root / "samples.tsv",
        seed_tsv=root / "seeds.tsv",
        seed_parquet=root / "seeds.parquet",
        diamond_database=root / "database.dmnd",
        clusters_tsv=root / "clusters.tsv",
        clusters_parquet=root / "clusters.parquet",
        realignments_tsv=root / "realign.tsv",
        realignments_parquet=root / "realign.parquet",
        resource_duckdb=root / "resource.duckdb",
        curated_parquet_dir=root / "curated",
        fasta_output_dir=root / "fastas",
        validation_tsv=root / "validation.tsv",
        summary_dir=root / "summaries",
        resource_metrics_dir=root / "resource_metrics",
        logs_dir=root / "logs",
        benchmarks_dir=root / "benchmarks",
        provenance_dir=root / "provenance",
    )


def diamond_config():
    return {
        "diamond": {
            "executable": "diamond",
            "identity_mode": "approximate",
            "identity_percent": 50,
            "mutual_cover_percent": 50,
            "clustering_evalue": 0.1,
            "memory_limit": "8G",
            "cluster_steps": [],
            "masking": "tantan",
            "extra_args": [],
        },
        "resources": {"threads": 2},
    }


class CliTests(unittest.TestCase):
    def test_build_parser_requires_command_and_reads_log_file(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])
        args = parser.parse_args(
            ["--log-file", "run.log", "prepare", "--config", "config.yaml"]
        )
        self.assertEqual(args.log_file, Path("run.log"))
        monitored = parser.parse_args(
            [
                "--resource-metrics",
                "ram.tsv",
                "prepare",
                "--config",
                "config.yaml",
            ]
        )
        self.assertEqual(monitored.resource_metrics, Path("ram.tsv"))

    @mock.patch("builtins.print")
    def test_print_json(self, mocked_print):
        _print_json({"b": 2, "a": 1})
        rendered = mocked_print.call_args.args[0]
        self.assertLess(rendered.find('"a"'), rendered.find('"b"'))

    @mock.patch("e3_discovery.cli.prepare_inputs_from_config")
    def test_run_command_prepare(self, mocked):
        mocked.return_value = {"prepared": True}
        result = run_command(Namespace(command="prepare", config=Path("c")))
        self.assertTrue(result["prepared"])

    @mock.patch("e3_discovery.cli.cluster_tsv_to_parquet")
    def test_run_command_convert_clusters(self, mocked):
        mocked.return_value = {"membership_rows": 1}
        result = run_command(
            Namespace(
                command="convert-clusters",
                input=Path("in"),
                output=Path("out"),
                batch_size=10,
            )
        )
        self.assertEqual(result["membership_rows"], 1)

    @mock.patch("e3_discovery.cli.realign_tsv_to_parquet")
    @mock.patch("e3_discovery.cli.thresholds_from_config")
    @mock.patch("e3_discovery.cli.load_config")
    def test_run_command_convert_realignments(
        self,
        mocked_load,
        mocked_thresholds,
        mocked_convert,
    ):
        mocked_load.return_value = {"thresholds": {}}
        mocked_thresholds.return_value = object()
        mocked_convert.return_value = {"realignment_rows": 2}
        result = run_command(
            Namespace(
                command="convert-realignments",
                config=Path("c"),
                input=Path("in"),
                output=Path("out"),
                batch_size=10,
            )
        )
        self.assertEqual(result["realignment_rows"], 2)

    @mock.patch("e3_discovery.cli.build_resource_from_config")
    def test_run_command_build_resource(self, mocked):
        mocked.return_value = {"built": True}
        result = run_command(Namespace(command="build-resource", config=Path("c")))
        self.assertTrue(result["built"])

    @mock.patch("e3_discovery.cli._run_diamond_stage")
    def test_run_command_routes_all_diamond_stages(self, mocked):
        mocked.return_value = {"ok": True}
        for command in (
            "diamond-makedb",
            "diamond-deepclust",
            "diamond-realign",
        ):
            with self.subTest(command=command):
                result = run_command(Namespace(command=command, config=Path("c")))
                self.assertTrue(result["ok"])

    @mock.patch("e3_discovery.cli.plot_runtime_by_rule")
    @mock.patch("e3_discovery.cli.write_benchmark_outputs")
    @mock.patch("e3_discovery.cli.summarise_benchmarks")
    @mock.patch("e3_discovery.cli.aggregate_benchmark_directory")
    def test_run_command_aggregate_benchmarks(
        self,
        mocked_aggregate,
        mocked_summarise,
        mocked_write,
        mocked_plot,
    ):
        mocked_aggregate.return_value = [{"rule_name": "x", "s": 1.0}]
        mocked_summarise.return_value = [{"rule_name": "x"}]
        with tempfile.TemporaryDirectory() as tmp:
            result = run_command(
                Namespace(
                    command="aggregate-benchmarks",
                    benchmark_dir=Path(tmp),
                    output_dir=Path(tmp) / "out",
                    resource_metrics_dir=None,
                )
            )
        self.assertEqual(result, {"record_count": 1, "summary_count": 1})
        mocked_write.assert_called_once()
        mocked_plot.assert_called_once()

    @mock.patch("e3_discovery.cli.write_run_manifest")
    @mock.patch("e3_discovery.cli.paths_from_config")
    @mock.patch("e3_discovery.cli.load_config")
    def test_run_command_write_provenance(
        self,
        mocked_load,
        mocked_paths,
        mocked_manifest,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            mocked_load.return_value = {
                "project": {"name": "x"},
                "inputs": {
                    "samples_tsv": str(Path(tmp) / "samples.tsv"),
                    "e3_seed_table": str(Path(tmp) / "seeds.csv"),
                },
            }
            mocked_paths.return_value = workflow_paths(Path(tmp))
            mocked_manifest.return_value = {"manifest": True}
            result = run_command(
                Namespace(command="write-provenance", config=Path("c"))
            )
        self.assertTrue(result["manifest"])

    def test_run_command_rejects_unknown_command(self):
        with self.assertRaises(ValueError):
            run_command(Namespace(command="unknown"))

    @mock.patch("e3_discovery.cli.validate_expected_outputs")
    @mock.patch("e3_discovery.cli.run_external_command")
    @mock.patch("e3_discovery.cli.require_diamond_features")
    @mock.patch("e3_discovery.cli.get_diamond_version")
    @mock.patch("e3_discovery.cli.paths_from_config")
    @mock.patch("e3_discovery.cli.load_config")
    def test_run_diamond_stages(
        self,
        mocked_load,
        mocked_paths,
        mocked_version,
        mocked_require,
        mocked_run,
        mocked_validate,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            mocked_load.return_value = diamond_config()
            mocked_paths.return_value = workflow_paths(Path(tmp))
            mocked_version.return_value = SemanticVersion(2, 2, 3)
            for stage, expected_token in (
                ("diamond-makedb", "makedb"),
                ("diamond-deepclust", "deepclust"),
                ("diamond-realign", "realign"),
            ):
                with self.subTest(stage=stage):
                    result = _run_diamond_stage(stage, Path("config.yaml"))
                    self.assertIn(expected_token, result["command"])
                    self.assertEqual(result["diamond_version"], "2.2.3")
        self.assertEqual(mocked_run.call_count, 3)
        self.assertEqual(mocked_validate.call_count, 3)
        self.assertEqual(mocked_require.call_count, 3)

    @mock.patch("e3_discovery.cli.validate_expected_outputs")
    @mock.patch("e3_discovery.cli.run_external_command")
    @mock.patch("e3_discovery.cli.require_diamond_features")
    @mock.patch("e3_discovery.cli.get_diamond_version")
    @mock.patch("e3_discovery.cli.paths_from_config")
    @mock.patch("e3_discovery.cli.load_config")
    def test_run_diamond_stages_use_alias_for_whitespace_root(
        self,
        mocked_load,
        mocked_paths,
        mocked_version,
        _mocked_require,
        mocked_run,
        _mocked_validate,
    ):
        """Present whitespace-free paths to every DIAMOND workflow stage."""

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "results with space"
            config = diamond_config()
            config["diamond"]["path_alias_root"] = str(base / "aliases")
            mocked_load.return_value = config
            mocked_paths.return_value = workflow_paths(root)
            mocked_version.return_value = SemanticVersion(2, 2, 3)

            for stage in (
                "diamond-makedb",
                "diamond-deepclust",
                "diamond-realign",
            ):
                with self.subTest(stage=stage):
                    result = _run_diamond_stage(
                        stage,
                        base / "repository" / "config" / "config.yaml",
                    )
                    self.assertTrue(result["path_alias_created"])
                    self.assertNotIn(" ", result["external_tool_root"])
                    path_arguments = [
                        token
                        for token in result["command"]
                        if "/" in str(token)
                    ]
                    self.assertTrue(path_arguments)
                    self.assertTrue(
                        all(" " not in str(token) for token in path_arguments)
                    )

        self.assertEqual(mocked_run.call_count, 3)

    @mock.patch("e3_discovery.cli.paths_from_config")
    @mock.patch("e3_discovery.cli.load_config")
    def test_run_diamond_stage_rejects_unknown(self, mocked_load, mocked_paths):
        with tempfile.TemporaryDirectory() as tmp:
            mocked_load.return_value = diamond_config()
            mocked_paths.return_value = workflow_paths(Path(tmp))
            with mock.patch(
                "e3_discovery.cli.get_diamond_version",
                return_value=SemanticVersion(2, 2, 3),
            ):
                with self.assertRaises(ValueError):
                    _run_diamond_stage("unknown", Path("config.yaml"))

    @mock.patch("e3_discovery.cli._print_json")
    @mock.patch("e3_discovery.cli.run_command", return_value={"ok": True})
    def test_main_success(self, _mocked_command, mocked_print):
        code = main(["prepare", "--config", "config.yaml"])
        self.assertEqual(code, 0)
        mocked_print.assert_called_once_with({"ok": True})

    @mock.patch("e3_discovery.cli.write_resource_usage")
    @mock.patch("e3_discovery.cli.ProcessTreeResourceMonitor")
    @mock.patch("e3_discovery.cli._print_json")
    @mock.patch("e3_discovery.cli.run_command", return_value={"ok": True})
    def test_main_writes_resource_metrics(
        self,
        _mocked_command,
        _mocked_print,
        mocked_monitor_class,
        mocked_write,
    ):
        usage = mock.Mock(peak_rss_mb=12.5)
        monitor = mocked_monitor_class.return_value
        monitor.stop.return_value = usage
        code = main(
            [
                "--resource-metrics",
                "ram.tsv",
                "prepare",
                "--config",
                "config.yaml",
            ]
        )
        self.assertEqual(code, 0)
        monitor.start.assert_called_once_with()
        monitor.stop.assert_called_once_with(return_code=0)
        mocked_write.assert_called_once_with(usage, Path("ram.tsv"))

    @mock.patch("e3_discovery.cli.run_command", side_effect=FileNotFoundError("x"))
    def test_main_returns_two_for_expected_error(self, _mocked):
        code = main(["prepare", "--config", "missing.yaml"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
