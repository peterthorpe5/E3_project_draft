"""End-to-end tests for all scientific and publication stages."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pyarrow.parquet as pq

from e3orthology.errors import InputValidationError, ScientificValidationError
from e3orthology.pipeline import (
    _mapping_tier,
    _read_tsv,
    build_stage_specs,
    provide_paths,
    run_pipeline,
    serialisable_runtime,
    stage_output_path,
    validation_check,
)
from e3orthology.stages import stage_directory
from tests.helpers import create_fixture


class PipelineEndToEndTests(unittest.TestCase):
    """Run the complete miniature workflow and validate formal products."""

    def test_complete_pipeline_publication_and_resume(self) -> None:
        """All six stages publish expected Q9SA03 and unmatched evidence."""

        with tempfile.TemporaryDirectory() as temporary:
            paths, config = create_fixture(Path(temporary))
            decisions = run_pipeline(
                paths=paths,
                config=config,
                resume=False,
                start_at=None,
                stop_after=None,
                force_stages=set(),
                dry_run=False,
            )
            self.assertEqual(len(decisions), 6)
            self.assertTrue(all(row["decision"] == "RUN" for row in decisions))
            publish = stage_directory(
                run_root=paths.run_root,
                stage_name="05_publish_portable_outputs",
            )
            mapping_tsv = publish / "tables" / "candidate_membership_mapping.tsv"
            rows = _read_tsv(path=mapping_tsv)
            q9_rows = [row for row in rows if row["candidate_accession"] == "Q9SA03"]
            self.assertEqual(
                {row["group_id"] for row in q9_rows},
                {"OG0001686", "N0.HOG0002084"},
            )
            self.assertEqual(
                pq.read_table(publish / "tables" / "candidate_membership_mapping.parquet").num_rows,
                len(rows),
            )
            validation = json.loads(
                (publish / "qc" / "validation_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(validation["fail_count"], 0)
            unmatched = _read_tsv(path=publish / "qc" / "unmatched_candidate_accessions.tsv")
            self.assertEqual(unmatched[0]["candidate_accession"], "NOPE01")
            resumed = run_pipeline(
                paths=paths,
                config=config,
                resume=True,
                start_at=None,
                stop_after=None,
                force_stages=set(),
                dry_run=False,
            )
            self.assertTrue(all(row["decision"] == "SKIPPED_VALIDATED" for row in resumed))
            forced = run_pipeline(
                paths=paths,
                config=config,
                resume=True,
                start_at=None,
                stop_after=None,
                force_stages={"03_map_candidates"},
                dry_run=False,
            )
            self.assertEqual(forced[2]["decision"], "SKIPPED_VALIDATED")
            self.assertEqual(forced[3]["reason"], "forced")
            self.assertEqual(forced[4]["reason"], "upstream_changed")

    def test_dry_run_and_bounded_plan(self) -> None:
        """Dry-run writes nothing and stop-after executes a reusable prefix."""

        with tempfile.TemporaryDirectory() as temporary:
            paths, config = create_fixture(Path(temporary))
            planned = run_pipeline(
                paths=paths,
                config=config,
                resume=False,
                start_at=None,
                stop_after=None,
                force_stages=set(),
                dry_run=True,
            )
            self.assertEqual(len(planned), 6)
            self.assertFalse(paths.run_root.exists())
            bounded = run_pipeline(
                paths=paths,
                config=config,
                resume=False,
                start_at=None,
                stop_after="01_build_identifier_map",
                force_stages=set(),
                dry_run=False,
            )
            self.assertEqual(len(bounded), 2)
            continued = run_pipeline(
                paths=paths,
                config=config,
                resume=True,
                start_at="02_build_membership",
                stop_after=None,
                force_stages=set(),
                dry_run=False,
            )
            self.assertEqual(continued[0]["decision"], "UPSTREAM_VALIDATED")

    def test_scientific_and_structural_failures(self) -> None:
        """Species mismatch and wrong regression identifiers block publication."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, config = create_fixture(root)
            wrong_species = {**config, "input": {**config["input"], "expected_species_count": 3}}
            with self.assertRaises(InputValidationError):
                run_pipeline(
                    paths=paths,
                    config=wrong_species,
                    resume=False,
                    start_at=None,
                    stop_after="00_preflight",
                    force_stages=set(),
                    dry_run=False,
                )
            paths, config = create_fixture(root / "regression")
            config["regression"]["expected_orthogroup"] = "WRONG"
            with self.assertRaises(ScientificValidationError):
                run_pipeline(
                    paths=paths,
                    config=config,
                    resume=False,
                    start_at=None,
                    stop_after="04_validate_integration",
                    force_stages=set(),
                    dry_run=False,
                )

    def test_small_pipeline_helpers_and_contract(self) -> None:
        """Helper records, tiers, stage paths and specs remain stable."""

        with tempfile.TemporaryDirectory() as temporary:
            paths, config = create_fixture(Path(temporary))
            runtime = serialisable_runtime(paths=paths, config=config)
            self.assertEqual(runtime["paths"]["run_name"], "fixture_run")
            self.assertEqual(provide_paths(paths=(Path("a"), Path("b"))), (Path("a"), Path("b")))
            self.assertEqual(
                stage_output_path(
                    run_root=paths.run_root,
                    stage_name="x",
                    filename="y",
                ),
                paths.run_root.resolve() / "stages" / "x" / "y",
            )
            self.assertEqual(len(build_stage_specs(paths=paths, config=config)), 6)
            self.assertEqual(
                validation_check(name="x", passed=True, observed=1, expected=1, details="ok")[
                    "status"
                ],
                "PASS",
            )
            base = {
                "raw_identifier": "Q9SA03",
                "identifier_format": "BARE_TOKEN",
                "parsed_entry": "",
            }
            self.assertEqual(
                _mapping_tier(candidate_accession="Q9SA03", membership=base),
                "TIER_1_RAW_EXACT",
            )
            base["raw_identifier"] = "sp|Q9SA03|ENTRY"
            base["identifier_format"] = "UNIPROT_PIPE"
            self.assertEqual(
                _mapping_tier(candidate_accession="Q9SA03", membership=base),
                "TIER_2_EXACT_PARSED_UNIPROT",
            )
