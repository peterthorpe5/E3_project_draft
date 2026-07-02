"""Unit tests for inherited Parquet copy behaviour."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_converter_module():
    """Load the conversion script as a module for unit testing."""
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "e3_convert_seed_sources.py"
    spec = importlib.util.spec_from_file_location("e3_convert_seed_sources", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load e3_convert_seed_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCopyExistingParquets(unittest.TestCase):
    """Tests for copying inherited Parquet files safely."""

    def test_copy_existing_parquets_skips_sidecars_and_invalid_files(self) -> None:
        """AppleDouble files and invalid Parquet-like files should not be copied."""
        module = load_converter_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "raw"
            parquet_root = Path(tmpdir) / "derived" / "parquet"
            source_dir = root / "Other_things" / "Denbi"
            source_dir.mkdir(parents=True)

            good = source_dir / "realigned_clusters.parquet"
            bad = source_dir / "bad.parquet"
            sidecar = source_dir / "._realigned_clusters.parquet"
            good.write_bytes(b"PAR1payloadPAR1")
            bad.write_bytes(b"not parquet")
            sidecar.write_bytes(b"PAR1payloadPAR1")

            catalog = module.copy_existing_parquets(root, parquet_root)

            statuses = {record["source_file"]: record["status"] for record in catalog}
            self.assertEqual(statuses["Other_things/Denbi/realigned_clusters.parquet"], "copied")
            self.assertEqual(statuses["Other_things/Denbi/bad.parquet"], "skipped_invalid_parquet")
            self.assertEqual(
                statuses["Other_things/Denbi/._realigned_clusters.parquet"],
                "skipped_hidden_sidecar",
            )

            copied_files = list(parquet_root.rglob("*.parquet"))
            self.assertEqual(len(copied_files), 1)
            self.assertIn("misc_inherited_support_files", copied_files[0].as_posix())


if __name__ == "__main__":
    unittest.main()
