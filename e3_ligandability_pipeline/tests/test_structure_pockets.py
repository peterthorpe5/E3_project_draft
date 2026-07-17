"""Unit tests for structure, FPocket, P2Rank and residue mapping logic."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3ligandability.fpocket import (
    discover_fpocket_info_files,
    discover_pocket_atom_files,
    normalise_metric_name,
    parse_all_pocket_residues,
    parse_fpocket_info,
    parse_pocket_cif_residues,
    parse_scalar,
)
from e3ligandability.mapping import (
    build_model_residue_indexes,
    compute_pocket_quality,
    join_fpocket_and_p2rank,
    map_one_pocket_residue,
    map_pocket_residues,
)
from e3ligandability.models import PocketResidueRecord, ResidueRecord
from e3ligandability.p2rank import (
    discover_prediction_files,
    infer_fpocket_pocket_number,
    parse_all_prediction_files,
    parse_prediction_csv,
)
from e3ligandability.structure import (
    _normalise_missing,
    _optional_int,
    collapse_atoms_to_residues,
    compare_api_quality,
    compute_model_quality,
    parse_model_residues,
    read_atom_site_rows,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


class StructureTests(unittest.TestCase):
    """Test mmCIF parsing and model confidence calculations."""

    def test_low_level_mmcif_helpers(self) -> None:
        self.assertIsNone(_optional_int("?"))
        self.assertEqual(_optional_int("2"), 2)
        self.assertEqual(_normalise_missing("."), "")
        self.assertEqual(_normalise_missing(" A "), "A")

    def test_read_collapse_parse_and_quality(self) -> None:
        atom_rows = read_atom_site_rows(FIXTURE_ROOT / "model.cif")
        self.assertEqual(len(atom_rows), 9)
        residues = collapse_atoms_to_residues(atom_rows)
        self.assertEqual(len(residues), 3)
        parsed = parse_model_residues(FIXTURE_ROOT / "model.cif")
        self.assertEqual(parsed, residues)
        quality = compute_model_quality("TEST", residues)
        self.assertAlmostEqual(quality["mean_plddt"], 78.3333333333)
        self.assertAlmostEqual(quality["fraction_residues_ge_70"], 2 / 3)
        with self.assertRaises(ValueError):
            compute_model_quality("TEST", [], 70, 90)
        with self.assertRaises(ValueError):
            compute_model_quality("TEST", residues, 90, 70)

    def test_compare_api_quality(self) -> None:
        comparison = compare_api_quality(
            {"mean_plddt": 80.0, "fraction_residues_ge_70": 0.8},
            {"global_metric_value": 80.1, "api_fraction_residues_ge_70": 0.79},
            mean_tolerance=0.2,
            fraction_tolerance=0.02,
        )
        self.assertTrue(comparison["mean_plddt_matches_api"])
        self.assertTrue(comparison["fraction_ge_70_matches_api"])


class PocketParsingTests(unittest.TestCase):
    """Test FPocket and P2Rank output parsing."""

    def test_scalar_and_metric_normalisation(self) -> None:
        self.assertEqual(
            normalise_metric_name("Druggability Score"),
            "druggability_score",
        )
        self.assertEqual(parse_scalar("12"), 12)
        self.assertEqual(parse_scalar("1.5"), 1.5)
        self.assertIsNone(parse_scalar("NA"))
        self.assertEqual(parse_scalar("abc"), "abc")

    def test_fpocket_discovery_and_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = root / "model_info.txt"
            info.write_text(
                "Pocket 1 :\nScore : 5.2\nDruggability Score : 0.8\n"
                "Pocket 2 :\nScore : 2.0\n",
                encoding="utf-8",
            )
            pockets = root / "pockets"
            pockets.mkdir()
            pocket_path = pockets / "pocket1_atm.cif"
            pocket_path.write_bytes((FIXTURE_ROOT / "pocket1_atm.cif").read_bytes())
            self.assertEqual(discover_fpocket_info_files(root), [info.resolve()])
            parsed = parse_fpocket_info(info, "TEST")
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[0]["druggability_score"], 0.8)
            discovered = discover_pocket_atom_files(root)
            self.assertEqual(discovered[0][0], 1)
            residues = parse_pocket_cif_residues(pocket_path, "TEST", 1)
            self.assertEqual(len(residues), 2)
            all_residues = parse_all_pocket_residues(root, "TEST")
            self.assertEqual(all_residues, residues)

    def test_p2rank_discovery_parsing_and_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "model_predictions.csv"
            csv_path.write_text(
                "name,score,rank,old_rank,probability\n"
                "pocket1,9.1,1,2,0.95\n",
                encoding="utf-8",
            )
            self.assertEqual(discover_prediction_files(root), [csv_path.resolve()])
            parsed = parse_prediction_csv(csv_path, "TEST")
            self.assertEqual(parsed[0]["fpocket_pocket_number"], 2)
            self.assertEqual(parse_all_prediction_files(root, "TEST"), parsed)
            self.assertEqual(infer_fpocket_pocket_number({"name": "pocket12"}), 12)
            self.assertIsNone(infer_fpocket_pocket_number({"name": "unknown"}))


class MappingTests(unittest.TestCase):
    """Test explicit pocket residue mapping and confidence denominators."""

    def setUp(self) -> None:
        self.model_residues = parse_model_residues(FIXTURE_ROOT / "model.cif")
        self.pocket_residues = parse_pocket_cif_residues(
            FIXTURE_ROOT / "pocket1_atm.cif",
            "TEST",
            1,
        )

    def test_indexes_and_one_residue_mapping(self) -> None:
        label, auth = build_model_residue_indexes(self.model_residues)
        record = map_one_pocket_residue(self.pocket_residues[0], label, auth)
        self.assertEqual(record["mapping_status"], "MAPPED")
        self.assertEqual(record["mapping_method"], "label_and_auth_agree")
        self.assertEqual(record["model_plddt"], 80.0)

        missing = PocketResidueRecord(
            accession="TEST",
            pocket_number=1,
            label_chain="A",
            label_seq_id=99,
            auth_chain="A",
            auth_seq_id=99,
            insertion_code="",
            residue_name="XXX",
            source_file="x",
        )
        missing_record = map_one_pocket_residue(missing, label, auth)
        self.assertEqual(missing_record["mapping_status"], "UNMAPPED")

    def test_mapping_and_quality_uses_full_denominator(self) -> None:
        missing = PocketResidueRecord(
            accession="TEST",
            pocket_number=1,
            label_chain="A",
            label_seq_id=99,
            auth_chain="A",
            auth_seq_id=99,
            insertion_code="",
            residue_name="XXX",
            source_file="x",
        )
        mappings = map_pocket_residues(
            [*self.pocket_residues, missing],
            self.model_residues,
        )
        quality = compute_pocket_quality(
            mappings,
            minimum_mapping_fraction=0.9,
        )[0]
        self.assertEqual(quality["predicted_pocket_residue_count"], 3)
        self.assertEqual(quality["mapped_pocket_residue_count"], 2)
        self.assertAlmostEqual(quality["mapped_fraction_plddt_ge_70"], 1.0)
        self.assertAlmostEqual(
            quality["conservative_fraction_plddt_ge_70"],
            2 / 3,
        )
        self.assertFalse(quality["mapping_qc_pass"])

    def test_join_fpocket_and_p2rank(self) -> None:
        joined = join_fpocket_and_p2rank(
            [{"accession": "TEST", "pocket_number": 1, "score": 2.0}],
            [
                {
                    "accession": "TEST",
                    "fpocket_pocket_number": 1,
                    "score": 9.0,
                }
            ],
        )
        self.assertEqual(joined[0]["p2rank_match_status"], "MATCHED")
        self.assertEqual(joined[0]["p2rank_score"], 9.0)
        with self.assertRaises(ValueError):
            join_fpocket_and_p2rank(
                [{"accession": "TEST", "pocket_number": 1}],
                [
                    {"accession": "TEST", "fpocket_pocket_number": 1},
                    {"accession": "TEST", "fpocket_pocket_number": 1},
                ],
            )

    def test_model_dataclass_serialisation(self) -> None:
        self.assertEqual(self.model_residues[0].to_dict()["plddt"], 80.0)
        self.assertEqual(self.pocket_residues[0].to_dict()["pocket_number"], 1)


if __name__ == "__main__":
    unittest.main()
