"""Tests for per-sequence biological metadata extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3_discovery.exceptions import DataValidationError
from e3_discovery.manifest import SampleRecord
from e3_discovery.sequence_metadata import (
    SequenceBiologicalMetadata,
    metadata_flag_is_true,
    normalise_species_label,
    parse_onekp_scaffold_identifier,
    sequence_biological_metadata,
)


class SequenceMetadataTests(unittest.TestCase):
    """Validate manifest and 1KP sequence-level metadata handling."""

    def make_sample(
        self,
        root: str,
        metadata: dict[str, str] | None = None,
    ) -> SampleRecord:
        """Create a temporary sample record for metadata tests.

        Args:
            root: Temporary directory path.
            metadata: Optional manifest metadata overrides.

        Returns:
            Sample record referencing a small FASTA file.
        """

        fasta = Path(root) / "input.fasta"
        fasta.write_text(">x\nMKT\n", encoding="utf-8")
        return SampleRecord(
            sample_id="onekp_dataset",
            fasta_path=fasta,
            species="1KP combined dataset",
            metadata=metadata or {},
        )

    def test_normalise_species_label(self) -> None:
        """Convert underscore-delimited species labels to readable text."""

        self.assertEqual(
            normalise_species_label("_Meliosma_cuneifolia_"),
            "Meliosma cuneifolia",
        )
        self.assertEqual(normalise_species_label(""), "")

    def test_parse_onekp_scaffold_identifier(self) -> None:
        """Parse the inherited 1KP identifier convention exactly."""

        code, species = parse_onekp_scaffold_identifier(
            "scaffold-AALA-2000001-Meliosma_cuneifolia"
        )
        self.assertEqual(code, "AALA")
        self.assertEqual(species, "Meliosma cuneifolia")
        with self.assertRaises(DataValidationError):
            parse_onekp_scaffold_identifier("not-a-1kp-identifier")

    def test_metadata_flag_is_true(self) -> None:
        """Recognise supported affirmative manifest values."""

        for value in ("true", "YES", "1", "on"):
            self.assertTrue(metadata_flag_is_true(value))
        self.assertFalse(metadata_flag_is_true("false"))

    def test_manifest_metadata_is_retained_by_default(self) -> None:
        """Use manifest sample and species when no parser is requested."""

        with tempfile.TemporaryDirectory() as tmp:
            sample = self.make_sample(tmp)
            observed = sequence_biological_metadata(sample, "x")
        self.assertIsInstance(observed, SequenceBiologicalMetadata)
        self.assertEqual(observed.biological_sample_id, "onekp_dataset")
        self.assertEqual(observed.header_parse_status, "not_requested")

    def test_onekp_metadata_is_parsed_per_sequence(self) -> None:
        """Replace combined-file labels with 1KP sample and species values."""

        with tempfile.TemporaryDirectory() as tmp:
            sample = self.make_sample(
                tmp,
                {
                    "header_parser": "onekp_scaffold",
                    "header_parser_strict": "true",
                },
            )
            observed = sequence_biological_metadata(
                sample,
                "scaffold-AALA-2000001-Meliosma_cuneifolia",
            )
        self.assertEqual(observed.source_file_sample_id, "onekp_dataset")
        self.assertEqual(observed.biological_sample_id, "AALA")
        self.assertEqual(observed.biological_species, "Meliosma cuneifolia")
        self.assertEqual(observed.header_parse_status, "parsed")

    def test_strict_and_non_strict_parse_failures(self) -> None:
        """Raise for strict failures and retain a marked fallback otherwise."""

        with tempfile.TemporaryDirectory() as tmp:
            strict = self.make_sample(
                tmp,
                {
                    "header_parser": "onekp_scaffold",
                    "header_parser_strict": "true",
                },
            )
            with self.assertRaises(DataValidationError):
                sequence_biological_metadata(strict, "bad")

        with tempfile.TemporaryDirectory() as tmp:
            relaxed = self.make_sample(
                tmp,
                {"header_parser": "onekp_scaffold"},
            )
            observed = sequence_biological_metadata(relaxed, "bad")
        self.assertEqual(observed.header_parse_status, "unparsed")
        self.assertEqual(observed.biological_sample_id, "onekp_dataset")

    def test_unsupported_parser_is_rejected(self) -> None:
        """Reject unknown parser names before large-scale preparation."""

        with tempfile.TemporaryDirectory() as tmp:
            sample = self.make_sample(tmp, {"header_parser": "unknown"})
            with self.assertRaises(DataValidationError):
                sequence_biological_metadata(sample, "x")


if __name__ == "__main__":
    unittest.main()
