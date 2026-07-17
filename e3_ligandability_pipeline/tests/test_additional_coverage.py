"""Additional defensive branch tests for the production release."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from e3ligandability.alphafold import (
    materialise_model_assets,
    select_prediction,
)
from e3ligandability.fpocket import (
    discover_pocket_atom_files,
    parse_all_pocket_residues,
    parse_fpocket_info,
)
from e3ligandability.mapping import (
    build_model_residue_indexes,
    join_fpocket_and_p2rank,
    map_one_pocket_residue,
)
from e3ligandability.models import PocketResidueRecord, ResidueRecord
from e3ligandability.p2rank import (
    discover_prediction_files,
    parse_prediction_csv,
)
from e3ligandability.structure import read_atom_site_rows
from e3ligandability.tools import (
    ExternalToolError,
    check_required_version,
    resolve_executable,
    run_command,
    run_fpocket_rescore,
    write_single_model_dataset,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def write_executable(path: Path, content: str) -> Path:
    """Write and mark one test executable."""

    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


class FakeBlock:
    """Minimal mmCIF block returning supplied atom-site rows."""

    def __init__(self, rows: list[list[str]]) -> None:
        """Store rows for subsequent ``find`` calls."""

        self.rows = rows

    def find(self, tags: list[str]) -> list[list[str]]:
        """Return rows while ignoring requested tags."""

        del tags
        return self.rows


class FakeDocument:
    """Minimal gemmi document for atom-site branch tests."""

    def __init__(self, rows: list[list[str]]) -> None:
        """Create a document containing one fake block."""

        self.block = FakeBlock(rows)

    def sole_block(self) -> FakeBlock:
        """Return the sole fake block."""

        return self.block


class ToolCoverageTests(unittest.TestCase):
    """Exercise remaining external-tool failure and replacement branches."""

    def test_resolution_version_environment_and_missing_inputs(self) -> None:
        """Reject missing tools and exercise optional environment handling."""

        with patch("e3ligandability.tools.shutil.which", return_value=None):
            with self.assertRaises(ExternalToolError):
                resolve_executable("definitely_missing_e3_tool")

        with self.assertRaises(ExternalToolError):
            check_required_version(
                {
                    "return_code": 2,
                    "command": "tool --version",
                    "version_output": "",
                },
                "",
                "tool",
            )
        check_required_version(
            {"return_code": 0, "command": "tool -v", "version_output": "x"},
            "",
            "tool",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ExternalToolError):
                run_command(
                    ["true"],
                    root / "missing",
                    root / "out",
                    root / "err",
                    1,
                )
            with self.assertRaises(FileNotFoundError):
                write_single_model_dataset(root / "x.ds", root / "missing.cif")

            echo = write_executable(
                root / "echo_env",
                "#!/usr/bin/env bash\nprintf '%s\\n' \"${E3_TEST_VALUE}\"\n",
            )
            run_command(
                [str(echo)],
                root,
                root / "env.out",
                root / "env.err",
                5,
                environment={"E3_TEST_VALUE": "present"},
            )
            self.assertEqual(
                (root / "env.out").read_text(encoding="utf-8").strip(),
                "present",
            )

    def test_fpocket_rescore_requires_outputs_and_replaces_old_result(self) -> None:
        """Require output contracts and replace a prior result atomically."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fpocket = write_executable(root / "fpocket", "#!/bin/bash\nexit 0\n")
            empty_prank = write_executable(
                root / "empty_prank",
                "#!/bin/bash\nexit 0\n",
            )
            with self.assertRaises(ExternalToolError):
                run_fpocket_rescore(
                    "Q1",
                    FIXTURE_ROOT / "model.cif",
                    root / "missing_outputs",
                    fpocket,
                    empty_prank,
                    "rescore_2024",
                    1,
                    True,
                    5,
                )

            prank = write_executable(
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
                "echo info > \"${OUT}/fpocket/model_out/model_info.txt\"\n"
                "echo 'name,score' > \"${OUT}/model_predictions.csv\"\n",
            )
            output = root / "published"
            output.mkdir()
            (output / "old.txt").write_text("old", encoding="utf-8")
            backup = root / ".published.previous"
            backup.mkdir()
            (backup / "stale.txt").write_text("stale", encoding="utf-8")

            record = run_fpocket_rescore(
                "Q1",
                FIXTURE_ROOT / "model.cif",
                output,
                fpocket,
                prank,
                "rescore_2024",
                1,
                False,
                5,
            )
            self.assertTrue(output.is_dir())
            self.assertFalse((output / "old.txt").exists())
            self.assertFalse(backup.exists())
            self.assertEqual(record["accession"], "Q1")


class MappingCoverageTests(unittest.TestCase):
    """Exercise residue-index and mapping alternatives."""

    def test_author_duplicates_and_mapping_methods(self) -> None:
        """Detect author duplicates and expose label/auth/unmapped methods."""

        first = ResidueRecord("A", 1, "A", 5, "", "ALA", 80, 1, 0)
        second = ResidueRecord("B", 2, "A", 5, "", "GLY", 70, 1, 0)
        with self.assertRaises(ValueError):
            build_model_residue_indexes([first, second])

        label_index = {("A", 1): first}
        auth_index = {("A", 5, ""): first}
        label_only = PocketResidueRecord(
            "Q1", 1, "A", 1, "", None, "", "ALA", "x"
        )
        auth_only = PocketResidueRecord(
            "Q1", 1, "", None, "A", 5, "", "ALA", "x"
        )
        unmapped = PocketResidueRecord(
            "Q1", 1, "Z", 99, "Z", 99, "", "ALA", "x"
        )
        self.assertEqual(
            map_one_pocket_residue(label_only, label_index, auth_index)[
                "mapping_method"
            ],
            "label",
        )
        self.assertEqual(
            map_one_pocket_residue(auth_only, label_index, auth_index)[
                "mapping_method"
            ],
            "auth",
        )
        self.assertEqual(
            map_one_pocket_residue(unmapped, label_index, auth_index)[
                "mapping_status"
            ],
            "UNMAPPED",
        )

    def test_join_skips_unresolved_and_rejects_duplicates(self) -> None:
        """Skip unresolved P2Rank rows and reject duplicate pocket matches."""

        fpocket = [{"accession": "Q1", "pocket_number": 1}]
        joined = join_fpocket_and_p2rank(
            fpocket,
            [{"accession": "Q1", "fpocket_pocket_number": None}],
        )
        self.assertEqual(joined[0]["p2rank_match_status"], "UNMATCHED")
        duplicate = {
            "accession": "Q1",
            "fpocket_pocket_number": 1,
        }
        with self.assertRaises(ValueError):
            join_fpocket_and_p2rank(fpocket, [duplicate, duplicate])


class ParserCoverageTests(unittest.TestCase):
    """Exercise parser paths that are uncommon in normal AlphaFold outputs."""

    def test_structure_rejects_missing_invalid_and_nonfinite_values(self) -> None:
        """Reject empty, invalid and non-finite atom-site tables."""

        rows = {
            "empty": [],
            "ignored": [["OTHER", "CA", "ALA", "A", "1", "A", "1", ".", "80"]],
            "invalid": [["ATOM", "CA", "ALA", "A", "1", "A", "1", ".", "bad"]],
            "infinite": [["ATOM", "CA", "ALA", "A", "1", "A", "1", ".", "inf"]],
        }
        for case, table_rows in rows.items():
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "model.cif"
                    path.write_text("data_x\n", encoding="utf-8")
                    with patch(
                        "e3ligandability.structure.gemmi.cif.read_file",
                        return_value=FakeDocument(table_rows),
                    ):
                        with self.assertRaises(ValueError):
                            read_atom_site_rows(path)

    def test_fpocket_and_p2rank_missing_paths_and_pdb_rejection(self) -> None:
        """Reject absent inputs and unsupported PDB pocket atom files."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                parse_fpocket_info(root / "missing_info.txt", "Q1")
            with self.assertRaises(FileNotFoundError):
                discover_pocket_atom_files(root / "missing")
            with self.assertRaises(FileNotFoundError):
                discover_prediction_files(root / "missing")
            with self.assertRaises(FileNotFoundError):
                parse_prediction_csv(root / "missing.csv", "Q1")

            empty = root / "pocket2_atm.cif"
            empty.touch()
            ignored = root / "pocket_bad_atm.cif"
            ignored.write_text("content", encoding="utf-8")
            pdb = root / "pocket1_atm.pdb"
            pdb.write_text("ATOM", encoding="utf-8")
            discovered = discover_pocket_atom_files(root)
            self.assertEqual(discovered, [(1, pdb.resolve())])
            with self.assertRaises(ValueError):
                parse_all_pocket_residues(root, "Q1")


class AlphaFoldCoverageTests(unittest.TestCase):
    """Exercise canonical fallback and missing optional-asset handling."""

    def test_canonical_monomer_fallback_and_missing_optional_urls(self) -> None:
        """Prefer a canonical monomer and tolerate absent optional URLs."""

        prediction = select_prediction(
            [
                {
                    "uniprotAccession": "OTHER",
                    "cifUrl": "https://x/AF-Q1-F1-model_v6.cif",
                }
            ],
            "Q1",
        )
        self.assertEqual(
            prediction["selection_rule"],
            "canonical_monomer_highest_version",
        )

        with tempfile.TemporaryDirectory() as tmp:
            model, manifests = materialise_model_assets(
                "Q1",
                {"model_path": str(FIXTURE_ROOT / "model.cif")},
                {},
                Path(tmp),
                None,
                1,
                True,
                True,
                True,
                True,
            )
            self.assertTrue(model.is_file())
            self.assertEqual(len(manifests), 1)


if __name__ == "__main__":
    unittest.main()
