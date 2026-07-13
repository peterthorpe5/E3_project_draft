import tempfile
import unittest
from pathlib import Path

import pyarrow.parquet as pq

from e3_discovery.exceptions import DataValidationError
from e3_discovery.seeds import (
    choose_seed_column,
    normalise_seed_identifier,
    prepare_seed_table,
    seed_ids,
    seed_schema,
)


class SeedsTests(unittest.TestCase):
    def test_normalise_seed_identifier(self):
        self.assertEqual(normalise_seed_identifier("sp|P1|NAME"), "P1")
        self.assertEqual(normalise_seed_identifier("P2"), "P2")
        self.assertEqual(normalise_seed_identifier(""), "")

    def test_choose_seed_column_explicit_and_auto(self):
        self.assertEqual(choose_seed_column(["Entry"], None), "Entry")
        self.assertEqual(choose_seed_column(["x"], "x"), "x")
        with self.assertRaises(DataValidationError):
            choose_seed_column(["x"], None)

    def test_seed_schema(self):
        self.assertIn("seed_metadata_json", seed_schema().names)

    def test_prepare_seed_table_deduplicates_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "seeds.csv"
            source.write_text(
                "Entry,Name\nP1,one\nP1,duplicate\n,blank\nP2,two\n",
                encoding="utf-8",
            )
            result = prepare_seed_table(
                source,
                Path(tmp) / "seeds.tsv",
                Path(tmp) / "seeds.parquet",
            )
            table = pq.read_table(Path(tmp) / "seeds.parquet")
            self.assertEqual(result["unique_seeds"], 2)
            self.assertEqual(result["duplicate_rows"], 1)
            self.assertEqual(result["blank_rows"], 1)
            self.assertEqual(table.num_rows, 2)

    def test_prepare_seed_table_rejects_empty_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "seeds.csv"
            source.write_text("Entry\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                prepare_seed_table(
                    source,
                    Path(tmp) / "seeds.tsv",
                    Path(tmp) / "seeds.parquet",
                )

    def test_seed_ids(self):
        self.assertEqual(seed_ids([{"seed_id": "B"}, {"seed_id": "A"}]), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
