"""Targeted tests for defensive error handling and less common branches."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from e3ligandability.alphafold import (
    DownloadValidationError,
    copy_atomic,
    download_atomic,
    materialise_model_assets,
    normalise_prediction_metadata,
    query_prediction_metadata,
    select_prediction,
    validate_a3m_file,
    validate_cif_file,
    validate_json_file,
)
from e3ligandability.cli import main
from e3ligandability.config import DEFAULT_CONFIG, deep_merge, validate_config
from e3ligandability.fpocket import (
    discover_fpocket_info_files,
    discover_pocket_atom_files,
    parse_all_pocket_residues,
    parse_fpocket_info,
)
from e3ligandability.io_utils import (
    read_accession_records,
    sha256_file,
    write_parquet_records,
)
from e3ligandability.mapping import (
    build_model_residue_indexes,
    compute_pocket_quality,
    join_fpocket_and_p2rank,
    map_one_pocket_residue,
)
from e3ligandability.models import PocketResidueRecord, ResidueRecord
from e3ligandability.outputs import (
    build_duckdb_from_parquet,
    inspect_duckdb_tables,
)
from e3ligandability.p2rank import (
    infer_fpocket_pocket_number,
    parse_all_prediction_files,
    parse_prediction_csv,
)
from e3ligandability.pipeline import (
    process_accession,
    resolve_alphafold_metadata,
    run_pipeline,
)
from e3ligandability.provenance import capture_git_state
from e3ligandability.qc import (
    check_mapping_rows_match_quality_totals,
    check_model_threshold_flag,
    check_no_duplicate_mapping_rows,
    check_pocket_mapping_accounting,
    check_success_has_model_quality,
    check_unique_accessions,
)
from e3ligandability.regression import (
    compare_legacy_metadata_row,
    find_legacy_model,
    read_legacy_metadata,
)
from e3ligandability.structure import (
    collapse_atoms_to_residues,
    compute_model_quality,
    read_atom_site_rows,
)
from e3ligandability.tools import (
    ExternalToolError,
    capture_tool_version,
    resolve_executable,
    run_command,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


class FakeResponse:
    """Minimal response for uncommon HTTP test cases."""

    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self._content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=1):
        del chunk_size
        yield b""
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False


class FakeSession:
    """Sequential fake HTTP session."""

    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, *args, **kwargs):
        del args, kwargs
        return self.responses.pop(0)

    def close(self):
        return None


class AlphaFoldDefensiveTests(unittest.TestCase):
    """Cover metadata, validation and materialisation error branches."""

    def test_invalid_payload_item_and_nonmatching_selection(self) -> None:
        with self.assertRaises(ValueError):
            query_prediction_metadata(
                FakeSession([FakeResponse(payload=["bad"])]),
                "https://x",
                "Q1",
                1,
            )
        selected = select_prediction(
            [
                {"uniprotAccession": "OTHER", "cifUrl": "https://x/a.cif"},
                {
                    "uniprotAccession": "OTHER2",
                    "cifUrl": "https://x/model_vbad.cif",
                },
            ],
            "Q1",
        )
        self.assertEqual(selected["selection_exact_accession_count"], 0)
        self.assertEqual(selected["selection_canonical_monomer_count"], 0)
        self.assertEqual(selected["selection_rule"], "fallback_highest_model_version")
        normalised = normalise_prediction_metadata("Q1", {})
        self.assertIsNone(normalised["api_fraction_residues_ge_70"])

    def test_all_validator_failure_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tiny = root / "tiny.cif"
            tiny.write_text("data_x", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_cif_file(tiny)
            no_data = root / "no_data.cif"
            no_data.write_text("x" * 200, encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_cif_file(no_data)
            no_atoms = root / "no_atoms.cif"
            no_atoms.write_text("data_x\n" + "x" * 200, encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_cif_file(no_atoms)
            missing_json = root / "missing.json"
            with self.assertRaises(DownloadValidationError):
                validate_json_file(missing_json)
            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_json_file(invalid_json)
            empty_a3m = root / "empty.a3m"
            empty_a3m.write_text("", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                validate_a3m_file(empty_a3m)

    def test_download_and_copy_failures_remove_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                download_atomic(
                    FakeSession([]),
                    "ftp://x/model.cif",
                    root / "x.cif",
                    1,
                    validate_cif_file,
                )
            with self.assertRaises(DownloadValidationError):
                download_atomic(
                    FakeSession([FakeResponse(content=b"bad")]),
                    "https://x/model.cif",
                    root / "bad.cif",
                    1,
                    validate_cif_file,
                )
            self.assertFalse((root / "bad.cif").exists())
            with self.assertRaises(FileNotFoundError):
                copy_atomic(root / "missing", root / "x", validate_cif_file)
            source = root / "source"
            source.write_text("bad", encoding="utf-8")
            with self.assertRaises(DownloadValidationError):
                copy_atomic(source, root / "copy", validate_cif_file)

    def test_materialise_url_optional_assets_and_no_model(self) -> None:
        cif = (FIXTURE_ROOT / "model.cif").read_bytes()
        json_bytes = b'{"x": 1}'
        a3m = b">Q1\nAAAA\n"
        session = FakeSession(
            [
                FakeResponse(content=cif),
                FakeResponse(content=json_bytes),
                FakeResponse(content=a3m),
                FakeResponse(content=json_bytes),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            model, manifests = materialise_model_assets(
                "Q1",
                {},
                {
                    "cif_url": "https://x/model.cif",
                    "pae_url": "https://x/pae.json",
                    "msa_url": "https://x/msa.a3m",
                    "plddt_url": "https://x/plddt.json",
                },
                Path(tmp),
                session,
                2,
                False,
                True,
                True,
                True,
            )
            self.assertTrue(model.is_file())
            self.assertEqual(len(manifests), 4)
            with self.assertRaises(ValueError):
                materialise_model_assets(
                    "Q2",
                    {},
                    {},
                    Path(tmp),
                    FakeSession([]),
                    1,
                    True,
                    False,
                    False,
                    False,
                )


class ParserDefensiveTests(unittest.TestCase):
    """Cover malformed and absent structural output branches."""

    def test_fpocket_missing_and_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(discover_fpocket_info_files(root), [])
            self.assertEqual(discover_pocket_atom_files(root), [])
            info = root / "x_info.txt"
            info.write_text("no pockets", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_fpocket_info(info, "Q1")
            with self.assertRaises(ValueError):
                parse_all_pocket_residues(root, "Q1")
            with self.assertRaises(FileNotFoundError):
                discover_fpocket_info_files(root / "missing")

    def test_p2rank_missing_empty_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                parse_all_prediction_files(root, "Q1")
            no_header = root / "x_predictions.csv"
            no_header.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_prediction_csv(no_header, "Q1")
            no_rows = root / "y_predictions.csv"
            no_rows.write_text("name,score\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_prediction_csv(no_rows, "Q1")
            self.assertEqual(
                infer_fpocket_pocket_number(
                    {"old_rank": "bad", "fpocket_rank": 4}
                ),
                4,
            )

    def test_structure_invalid_rows_and_no_polymer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                read_atom_site_rows(root / "missing.cif")
            hetero = [
                {
                    "group_pdb": "HETATM",
                    "atom_name": "C",
                    "residue_name": "LIG",
                    "label_chain": "A",
                    "label_seq_id": 1,
                    "auth_chain": "A",
                    "auth_seq_id": 1,
                    "insertion_code": "",
                    "plddt": 1.0,
                }
            ]
            with self.assertRaises(ValueError):
                collapse_atoms_to_residues(hetero)


class MappingAndQcDefensiveTests(unittest.TestCase):
    """Cover ambiguity, duplicates and failing QC records."""

    def test_duplicate_indexes_and_ambiguous_mapping(self) -> None:
        residue = ResidueRecord("A", 1, "A", 1, "", "ALA", 80, 1, 0)
        with self.assertRaises(ValueError):
            build_model_residue_indexes([residue, residue])
        label = {("A", 1): residue}
        other = ResidueRecord("B", 2, "A", 1, "", "GLY", 60, 1, 0)
        auth = {("A", 1, ""): other}
        pocket = PocketResidueRecord("Q1", 1, "A", 1, "A", 1, "", "ALA", "x")
        mapped = map_one_pocket_residue(pocket, label, auth)
        self.assertEqual(mapped["mapping_status"], "AMBIGUOUS")

    def test_empty_and_invalid_pocket_quality(self) -> None:
        self.assertEqual(compute_pocket_quality([]), [])
        with self.assertRaises(ValueError):
            compute_pocket_quality([], confident_threshold=95, very_high_threshold=90)
        with self.assertRaises(ValueError):
            compute_pocket_quality([], minimum_mapping_fraction=2)
        unmatched = join_fpocket_and_p2rank(
            [{"accession": "Q1", "pocket_number": 1}],
            [],
        )
        self.assertEqual(unmatched[0]["p2rank_match_status"], "UNMATCHED")

    def test_qc_failure_branches(self) -> None:
        self.assertEqual(check_unique_accessions([])["status"], "FAIL")
        duplicate = [{"accession": "Q1"}, {"accession": "Q1"}]
        self.assertEqual(check_unique_accessions(duplicate)["status"], "FAIL")
        self.assertEqual(
            check_success_has_model_quality(
                [{"accession": "Q1", "status": "SUCCESS"}],
                [],
            )["status"],
            "FAIL",
        )
        self.assertEqual(
            check_model_threshold_flag(
                [
                    {
                        "accession": "Q1",
                        "fraction_residues_ge_70": 0.9,
                        "passes_model_confidence_threshold": False,
                    }
                ],
                0.5,
            )["status"],
            "FAIL",
        )
        bad_quality = [
            {
                "accession": "Q1",
                "pocket_number": 1,
                "predicted_pocket_residue_count": 2,
                "mapped_pocket_residue_count": 1,
                "ambiguous_pocket_residue_count": 0,
                "unmapped_pocket_residue_count": 0,
            }
        ]
        self.assertEqual(check_pocket_mapping_accounting(bad_quality)["status"], "FAIL")
        self.assertEqual(
            check_mapping_rows_match_quality_totals([], bad_quality)["status"],
            "FAIL",
        )
        duplicate_mapping = [
            {
                "accession": "Q1",
                "pocket_number": 1,
                "label_chain": "A",
                "label_seq_id": 1,
                "auth_chain": "A",
                "auth_seq_id": 1,
                "insertion_code": "",
            }
        ] * 2
        self.assertEqual(
            check_no_duplicate_mapping_rows(duplicate_mapping)["status"],
            "FAIL",
        )


class IoToolProvenanceDefensiveTests(unittest.TestCase):
    """Cover less common I/O, tool and Git branches."""

    def test_input_and_output_errors(self) -> None:
        with self.assertRaises(FileNotFoundError):
            read_accession_records(Path("/missing/input.tsv"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = root / "empty.txt"
            empty.write_text("# no accessions\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_accession_records(empty)
            with self.assertRaises(FileNotFoundError):
                sha256_file(root / "missing")
            with self.assertRaises(FileNotFoundError):
                inspect_duckdb_tables(root / "missing.duckdb")
            bad_manifest = [
                {
                    "format": "parquet",
                    "dataset": "unknown",
                    "path": str(root / "x.parquet"),
                }
            ]
            with self.assertRaises(ValueError):
                build_duckdb_from_parquet(bad_manifest, root / "x.duckdb")
            write_parquet_records(root / "empty.parquet", [])
            self.assertTrue((root / "empty.parquet").is_file())

    def test_tool_errors_timeout_and_path_lookup(self) -> None:
        self.assertTrue(resolve_executable("bash").is_file())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nonexec = root / "nonexec"
            nonexec.write_text("x", encoding="utf-8")
            with self.assertRaises(ExternalToolError):
                resolve_executable(str(nonexec))
            with self.assertRaises(ExternalToolError):
                run_command(
                    ["bash", "-c", "echo x"],
                    root / "missing",
                    root / "out",
                    root / "err",
                    1,
                )
            sleeper = root / "sleep.sh"
            sleeper.write_text("#!/usr/bin/env bash\nsleep 2\n", encoding="utf-8")
            sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR)
            with self.assertRaises(ExternalToolError):
                run_command(
                    [str(sleeper)],
                    root,
                    root / "out",
                    root / "err",
                    0.01,
                )
            version = capture_tool_version(Path("/bin/false"))
            self.assertNotEqual(version["return_code"], 0)

    def test_capture_git_success_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.org"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"],
                check=True,
            )
            (root / "x").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "x"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "test"],
                check=True,
                capture_output=True,
            )
            state = capture_git_state(root)
            self.assertIsNotNone(state["commit"])
            self.assertFalse(state["dirty"])
            (root / "x").write_text("changed", encoding="utf-8")
            self.assertTrue(capture_git_state(root)["dirty"])


class PipelineDefensiveTests(unittest.TestCase):
    """Cover accession failures and CLI error handling."""

    def test_missing_model_result_and_failed_run(self) -> None:
        config = deep_merge(
            DEFAULT_CONFIG,
            {
                "alphafold": {
                    "query_api_for_local_models": False,
                    "download_pae": False,
                    "download_msa": False,
                    "download_plddt_json": False,
                },
                "external_tools": {"run_fpocket_p2rank": False},
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.tsv"
            input_path.write_text(
                "accession\tmodel_path\nQ1\t/missing/model.cif\n",
                encoding="utf-8",
            )
            records = read_accession_records(input_path)
            result = process_accession(
                records[0],
                "accession",
                root / "direct",
                config,
                FakeSession([]),
                None,
                None,
            )
            self.assertEqual(result.status, "FAILED")
            outcome = run_pipeline(
                input_path,
                records,
                root / "run",
                config,
            )
            self.assertFalse(outcome["success"])
            self.assertEqual(outcome["failed_accessions"], ["Q1"])

    def test_resolve_metadata_api_and_cli_error(self) -> None:
        config = deep_merge(
            DEFAULT_CONFIG,
            {
                "external_tools": {"run_fpocket_p2rank": False},
            },
        )
        metadata = resolve_alphafold_metadata(
            "Q1",
            {},
            config,
            FakeSession(
                [
                    FakeResponse(
                        payload=[
                            {
                                "uniprotAccession": "Q1",
                                "cifUrl": "https://x/model_v6.cif",
                            }
                        ]
                    )
                ]
            ),
        )
        self.assertEqual(metadata["accession"], "Q1")
        self.assertEqual(
            main(["run", "--input", "/missing", "--output-dir", "/tmp/x"]),
            1,
        )

    def test_invalid_config_boolean_and_legacy_csv(self) -> None:
        config = deep_merge(DEFAULT_CONFIG, {})
        config["alphafold"]["request_timeout_seconds"] = True
        with self.assertRaises(ValueError):
            validate_config(config)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "legacy.csv"
            bad.write_text("id,value\nQ1,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_legacy_metadata(bad)
            with self.assertRaises(FileNotFoundError):
                find_legacy_model(root / "missing", "Q1")
            result = compare_legacy_metadata_row(
                {
                    "accession": "Q1",
                    "globalMetricValue": "80",
                    "fractionModToHigh": "0.8",
                },
                None,
                0.1,
                0.1,
            )
            self.assertEqual(result["status"], "MISSING_MODEL")


if __name__ == "__main__":
    unittest.main()
