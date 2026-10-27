"""Production model selection must require both exact accession and F1 identity."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from e3ligandability.alphafold import AlphaFoldSelectionError, select_prediction
from e3ligandability.config import load_config, validate_config
from e3ligandability.pipeline import process_accession


class StrictSelectionTests(unittest.TestCase):
    """Protect strict automatic downloads and the explicit legacy override."""

    def test_exact_f1_wins_over_newer_isoform_and_fragment(self) -> None:
        """Select the highest numeric version within exact-accession F1 candidates."""
        selected = select_prediction(
            predictions=[
                {"uniprotAccession": "Q1", "cifUrl": "https://x/AF-Q1-F1-model_v9.cif"},
                {
                    "uniprotAccession": "Q1",
                    "cifUrl": "https://x/AF-Q1-F1-model_v10.cif",
                },
                {
                    "uniprotAccession": "Q1-2",
                    "cifUrl": "https://x/AF-Q1-2-F1-model_v99.cif",
                },
                {
                    "uniprotAccession": "Q1",
                    "cifUrl": "https://x/AF-Q1-F2-model_v99.cif",
                },
            ], accession="Q1",
        )
        self.assertTrue(selected["cifUrl"].endswith("model_v10.cif"))
        self.assertEqual(selected["selection_policy"], "require_exact_accession_f1")

    def test_mismatch_fragment_missing_and_malformed_name_are_unresolved(self) -> None:
        """Reject fallbacks whose identifiers cannot establish an exact F1 match."""
        for record in (
            {"uniprotAccession": "OTHER", "cifUrl": "https://x/AF-Q1-F1-model_v6.cif"},
            {"uniprotAccession": "Q1", "cifUrl": "https://x/AF-Q1-F2-model_v6.cif"},
            {"cifUrl": "https://x/AF-Q1-F1-model_v6.cif"},
            {
                "uniprotAccession": "Q1",
                "cifUrl": "https://x/AF-Q1-F1-model_v6.cif.html",
            },
        ):
            with (
                self.subTest(record=record),
                self.assertRaises(AlphaFoldSelectionError),
            ):
                select_prediction(predictions=[record], accession="Q1")

    def test_explicit_legacy_override_records_policy(self) -> None:
        """Retain documented fallback only through an explicit override."""
        result = select_prediction(
            predictions=[
                {"uniprotAccession": "OTHER", "cifUrl": "https://x/model_v6.cif"}
            ],
            accession="Q1", require_exact_accession_f1=False,
        )
        self.assertEqual(result["selection_policy"], "allow_documented_fallback")
        self.assertEqual(result["selection_rule"], "fallback_highest_model_version")

    def test_policy_is_strict_and_boolean(self) -> None:
        """Production defaults are strict and quoted booleans are rejected."""
        config = load_config(path=None)
        self.assertTrue(config["alphafold"]["require_exact_accession_f1"])
        config["alphafold"]["require_exact_accession_f1"] = "false"
        with self.assertRaises(ValueError):
            validate_config(config=config)

    def test_rejected_api_model_is_recorded_without_download(self) -> None:
        """Preserve the rejection reason and stop before model materialisation."""
        config = load_config(path=None)
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = [
            {"uniprotAccession": "OTHER", "cifUrl": "https://x/AF-Q1-F1-model_v6.cif"}
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = process_accession(
                input_record={"accession": "Q1"}, accession_column="accession",
                output_root=Path(directory), config=config, session=session,
                fpocket_executable=None, p2rank_executable=None,
            )
            self.assertEqual(result.status, "MISSING_MODEL")
            self.assertEqual(result.stage, "alphafold_metadata")
            self.assertIn("Selection remains unresolved", result.message)
            self.assertIsNone(result.model_path)
        self.assertEqual(session.get.call_count, 1)

    def test_invalid_direct_selection_parameters(self) -> None:
        """Reject malformed direct API records and non-boolean policies."""
        with self.assertRaises(ValueError):
            select_prediction(predictions=["bad"], accession="Q1")
        with self.assertRaises(ValueError):
            select_prediction(
                predictions=[{}], accession="Q1", require_exact_accession_f1="true"
            )
