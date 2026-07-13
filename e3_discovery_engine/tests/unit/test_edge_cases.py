import tempfile
import unittest
from pathlib import Path
from unittest import mock

from e3_discovery.benchmarks import (
    _population_sd,
    aggregate_benchmark_directory,
    parse_snakemake_benchmark,
    summarise_benchmarks,
)
from e3_discovery.clusters import (
    Thresholds,
    _normalise_cluster_header,
    _parse_float,
    _parse_int,
    _required_realign_fields,
    cluster_tsv_to_parquet,
    compute_coverage,
    realign_tsv_to_parquet,
)
from e3_discovery.config import (
    _require_mapping,
    load_yaml,
    validate_config,
)
from e3_discovery.diamond import (
    SemanticVersion,
    build_deepclust_command,
    build_makedb_command,
    build_realign_command,
    get_diamond_version,
    require_diamond_features,
    run_external_command,
    validate_expected_outputs,
)
from e3_discovery.exceptions import (
    ConfigurationError,
    DataValidationError,
    ExternalToolError,
)
from e3_discovery.fasta import iter_fasta, prepare_combined_fasta
from e3_discovery.io_utils import (
    detect_delimiter,
    open_text_auto,
    read_delimited,
    require_nonempty_file,
    write_tsv,
)
from e3_discovery.manifest import SampleRecord, read_sample_manifest
from e3_discovery.provenance import capture_command_version
from e3_discovery.seeds import choose_seed_column, prepare_seed_table


def valid_config():
    return {
        "project": {"name": "test"},
        "inputs": {
            "samples_tsv": "samples.tsv",
            "e3_seed_table": "seeds.csv",
            "identifier_mode": "prefix_sample",
        },
        "outputs": {"root": "results"},
        "diamond": {
            "executable": "diamond",
            "identity_mode": "approximate",
            "identity_percent": 50,
            "mutual_cover_percent": 50,
            "clustering_evalue": 0.1,
            "memory_limit": "8G",
            "cluster_steps": [],
            "extra_args": [],
        },
        "thresholds": {
            "minimum_percent_identity": 50,
            "minimum_representative_coverage": 50,
            "minimum_member_coverage": 50,
            "minimum_bitscore": 20,
            "maximum_evalue": 1e-10,
        },
        "resources": {"threads": 2, "parquet_batch_size": 100},
        "benchmarking": {"repeats": 1},
    }


class BenchmarkEdgeCaseTests(unittest.TestCase):
    def test_parse_missing_file_invalid_value_and_empty_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                parse_snakemake_benchmark(root / "missing.tsv")
            invalid = root / "invalid.tsv"
            invalid.write_text("s\nnot-a-number\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                parse_snakemake_benchmark(invalid)
            empty = root / "empty.tsv"
            empty.write_text("s\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                parse_snakemake_benchmark(empty)

    def test_aggregate_missing_or_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                aggregate_benchmark_directory(root / "missing")
            with self.assertRaises(DataValidationError):
                aggregate_benchmark_directory(root)

    def test_summary_rejects_missing_rule_and_times(self):
        with self.assertRaises(DataValidationError):
            summarise_benchmarks([{"s": 1.0}])
        with self.assertRaises(DataValidationError):
            summarise_benchmarks([{"rule_name": "x", "s": None}])
        with self.assertRaises(ValueError):
            _population_sd([])


class ClusterEdgeCaseTests(unittest.TestCase):
    def thresholds(self):
        return Thresholds(50, 50, 50, 20, 1e-10)

    def test_threshold_validation_and_negative_coverage(self):
        with self.assertRaises(ValueError):
            Thresholds(50, 50, 50, 0, 1e-10).validate()
        with self.assertRaises(ValueError):
            Thresholds(50, 50, 50, 20, 0).validate()
        with self.assertRaises(ValueError):
            compute_coverage(-1, 10)

    def test_private_header_and_number_parsers(self):
        with self.assertRaises(DataValidationError):
            _normalise_cluster_header(None)
        self.assertEqual(_normalise_cluster_header(["cseqid", "mseqid"]),
                         ("cseqid", "mseqid"))
        with self.assertRaises(DataValidationError):
            _required_realign_fields(None)
        with self.assertRaises(DataValidationError):
            _parse_int("x", "length", 2)
        with self.assertRaises(DataValidationError):
            _parse_float("x", "bitscore", 2)

    def test_cluster_conversion_rejects_batch_blank_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "valid.tsv"
            valid.write_text("representative\tmember\nr\tm\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cluster_tsv_to_parquet(valid, root / "x.parquet", batch_size=0)
            blank = root / "blank.tsv"
            blank.write_text("representative\tmember\nr\t\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                cluster_tsv_to_parquet(blank, root / "blank.parquet")
            empty = root / "empty.tsv"
            empty.write_text("representative\tmember\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                cluster_tsv_to_parquet(empty, root / "empty.parquet")

    def test_realign_conversion_rejects_batch_blank_and_empty(self):
        header = (
            "qseqid\tsseqid\tpident\tqlen\tslen\tqstart\tqend\t"
            "sstart\tsend\tlength\tevalue\tbitscore\n"
        )
        row = "r\tm\t60\t100\t100\t1\t60\t1\t60\t60\t1e-20\t30\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "valid.tsv"
            valid.write_text(header + row, encoding="utf-8")
            with self.assertRaises(ValueError):
                realign_tsv_to_parquet(
                    valid,
                    root / "x.parquet",
                    self.thresholds(),
                    batch_size=0,
                )
            blank = root / "blank.tsv"
            blank.write_text(header + row.replace("r\tm", "\tm"), encoding="utf-8")
            with self.assertRaises(DataValidationError):
                realign_tsv_to_parquet(
                    blank,
                    root / "blank.parquet",
                    self.thresholds(),
                )
            empty = root / "empty.tsv"
            empty.write_text(header, encoding="utf-8")
            with self.assertRaises(DataValidationError):
                realign_tsv_to_parquet(
                    empty,
                    root / "empty.parquet",
                    self.thresholds(),
                )


class ConfigEdgeCaseTests(unittest.TestCase):
    def test_load_missing_and_private_mapping(self):
        with self.assertRaises(FileNotFoundError):
            load_yaml(Path("missing-config.yaml"))
        with self.assertRaises(ConfigurationError):
            _require_mapping({"x": []}, "x")

    def test_config_rejects_invalid_required_values(self):
        changes = [
            ("project", "name", ""),
            ("inputs", "samples_tsv", ""),
            ("outputs", "root", ""),
            ("diamond", "identity_percent", 101),
            ("diamond", "mutual_cover_percent", 101),
            ("diamond", "memory_limit", ""),
            ("diamond", "executable", ""),
            ("diamond", "extra_args", "bad"),
            ("thresholds", "minimum_percent_identity", 101),
            ("resources", "parquet_batch_size", 0),
        ]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                config = valid_config()
                config[section][key] = value
                with self.assertRaises(ConfigurationError):
                    validate_config(config)
        config = valid_config()
        config["benchmarking"] = []
        with self.assertRaises(ConfigurationError):
            validate_config(config)


class DiamondEdgeCaseTests(unittest.TestCase):
    @mock.patch("e3_discovery.diamond.subprocess.run")
    def test_get_version_failure(self, mocked_run):
        mocked_run.return_value.returncode = 1
        mocked_run.return_value.stdout = ""
        mocked_run.return_value.stderr = "failed"
        with self.assertRaises(ExternalToolError):
            get_diamond_version()

    def test_feature_and_command_validation(self):
        with self.assertRaises(ConfigurationError):
            require_diamond_features(SemanticVersion(2, 1, 23), "exact")
        with self.assertRaises(ConfigurationError):
            require_diamond_features(SemanticVersion(2, 2, 3), "bad")
        with self.assertRaises(ValueError):
            build_makedb_command("diamond", Path("a"), Path("b"), 0)
        for kwargs in (
            {"threads": 0},
            {"identity_percent": 0},
            {"mutual_cover_percent": 0},
            {"clustering_evalue": 0},
        ):
            values = {
                "executable": "diamond",
                "database": Path("a"),
                "output_tsv": Path("b"),
                "threads": 1,
                "memory_limit": "8G",
                "identity_mode": "approximate",
                "identity_percent": 50,
                "mutual_cover_percent": 50,
                "clustering_evalue": 0.1,
            }
            values.update(kwargs)
            with self.assertRaises(ValueError):
                build_deepclust_command(**values)
        with self.assertRaises(ValueError):
            build_realign_command(
                "diamond", Path("db"), Path("c"), Path("o"), 0, "8G"
            )
        with self.assertRaises(ValueError):
            build_deepclust_command(
                "diamond",
                Path("db"),
                Path("out"),
                1,
                "8G",
                "exact",
                50,
                50,
                0.1,
                comp_based_stats=6,
            )

    def test_external_and_output_validation(self):
        with self.assertRaises(ValueError):
            run_external_command([], Path("log"))
        with self.assertRaises(ValueError):
            validate_expected_outputs([])


class FileAndManifestEdgeCaseTests(unittest.TestCase):
    def test_missing_empty_and_headerless_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                open_text_auto(root / "missing")
            empty = root / "empty.tsv"
            empty.write_text("", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                detect_delimiter(empty)
            headerless = root / "headerless.tsv"
            headerless.write_text("\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                read_delimited(headerless)
            with self.assertRaises(DataValidationError):
                require_nonempty_file(root / "missing")
            output = root / "out.tsv"
            self.assertEqual(write_tsv([], output), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "")

    def test_fasta_empty_header_and_empty_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.fasta"
            bad.write_text(">\nAAA\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                list(iter_fasta(bad))
            empty = root / "empty.fasta"
            empty.write_text("", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                prepare_combined_fasta(
                    [SampleRecord("s", empty)],
                    root / "combined.fasta",
                    root / "sequences.parquet",
                    root / "summary.tsv",
                )

    def test_manifest_missing_empty_duplicate_path_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                read_sample_manifest(root / "missing.tsv")
            empty = root / "empty.tsv"
            empty.write_text("sample_id\tfasta_path\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                read_sample_manifest(empty)
            fasta = root / "a.fasta"
            fasta.write_text(">a\nAAA\n", encoding="utf-8")
            duplicate = root / "duplicate.tsv"
            duplicate.write_text(
                "sample_id\tfasta_path\n"
                f"a\t{fasta}\n"
                f"b\t{fasta}\n",
                encoding="utf-8",
            )
            with self.assertRaises(DataValidationError):
                read_sample_manifest(duplicate)
            sidecar = root / "._a.fasta"
            sidecar.write_text("x", encoding="utf-8")
            sidecar_manifest = root / "sidecar.tsv"
            sidecar_manifest.write_text(
                "sample_id\tfasta_path\n" f"a\t{sidecar}\n",
                encoding="utf-8",
            )
            with self.assertRaises(DataValidationError):
                read_sample_manifest(sidecar_manifest)

    @mock.patch("e3_discovery.provenance.subprocess.run", side_effect=OSError("x"))
    def test_capture_command_version_oserror(self, _mocked):
        self.assertIn("unavailable", capture_command_version(["tool", "--version"]))

    def test_seed_column_and_no_valid_seeds(self):
        with self.assertRaises(DataValidationError):
            choose_seed_column(["Entry"], "missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seeds = root / "seeds.csv"
            seeds.write_text("Entry\n\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                prepare_seed_table(
                    seeds,
                    root / "seeds.tsv",
                    root / "seeds.parquet",
                )


if __name__ == "__main__":
    unittest.main()
