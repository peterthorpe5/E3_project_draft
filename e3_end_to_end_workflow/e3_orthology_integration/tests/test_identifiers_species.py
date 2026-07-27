"""Unit tests for identifier and species reconciliation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3orthology.errors import InputValidationError
from e3orthology.identifiers import iter_sequence_ids, parse_identifier, parse_species_ids
from e3orthology.species import (
    assess_species_coverage,
    load_species_manifest,
    parse_boolean,
    species_name_from_fasta,
)
from tests.helpers import write_text


class IdentifierTests(unittest.TestCase):
    """Exercise supported, unsupported and malformed identifier sources."""

    def test_parse_uniprot_bare_and_unknown(self) -> None:
        """Controlled parsing retains raw identifiers and explicit status."""

        reviewed = parse_identifier(value="sp|Q9SA03|FB27_ARATH description")
        unreviewed = parse_identifier(value="tr|A0A123|A0A123_ARATH")
        bare = parse_identifier(value="Q9SA03")
        unknown = parse_identifier(value="bad|identifier")
        empty = parse_identifier(value="  ")
        self.assertEqual(reviewed.parsed_accession, "Q9SA03")
        self.assertEqual(reviewed.to_record()["review_status"], "reviewed")
        self.assertEqual(unreviewed.review_status, "unreviewed")
        self.assertEqual(bare.identifier_format, "BARE_TOKEN")
        self.assertEqual(unknown.mapping_status, "NOT_PARSED")
        self.assertEqual(empty.raw_identifier, "")

    def test_parse_species_and_sequence_ids(self) -> None:
        """Species and sequence records preserve source metadata."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            species_path = write_text(root / "SpeciesIDs.txt", "0: Plant.fasta\n")
            sequence_path = write_text(
                root / "SequenceIDs.txt",
                "0_0: sp|Q9SA03|FB27_ARATH description\n",
            )
            species = parse_species_ids(path=species_path)
            records = list(iter_sequence_ids(path=sequence_path, species_by_index=species))
            self.assertEqual(species, {0: "Plant.fasta"})
            self.assertEqual(records[0].internal_id, "0_0")
            self.assertEqual(records[0].to_record()["parsed_accession"], "Q9SA03")
            self.assertEqual(
                parse_species_ids(path=write_text(root / "blank", "\n0: A.fa\n")), {0: "A.fa"}
            )
            self.assertEqual(
                len(
                    list(
                        iter_sequence_ids(
                            path=write_text(root / "blank_sequence", "\n0_0: Q9SA03\n"),
                            species_by_index={0: "A.fa"},
                        )
                    )
                ),
                1,
            )

    def test_reject_malformed_and_duplicate_identifier_mappings(self) -> None:
        """Malformed, duplicated and unknown species mappings fail loudly."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(InputValidationError):
                parse_species_ids(path=write_text(root / "bad_species", "invalid\n"))
            with self.assertRaises(InputValidationError):
                parse_species_ids(path=write_text(root / "empty_species", "\n"))
            with self.assertRaises(InputValidationError):
                parse_species_ids(path=write_text(root / "dup_species", "0: A.fa\n0: B.fa\n"))
            species = {0: "A.fa"}
            for name, content in (
                ("malformed", "broken\n"),
                ("duplicate", "0_0: Q9SA03\n0_0: Q9SA04\n"),
                ("unknown", "1_0: Q9SA03\n"),
            ):
                with self.subTest(name=name), self.assertRaises(InputValidationError):
                    list(
                        iter_sequence_ids(
                            path=write_text(root / name, content),
                            species_by_index=species,
                        )
                    )


class SpeciesTests(unittest.TestCase):
    """Exercise strict manifest parsing and alias-aware coverage."""

    def test_boolean_and_fasta_name_parsers(self) -> None:
        """Accepted Boolean and FASTA forms are deterministic."""

        for value in ("true", "YES", "1"):
            self.assertTrue(parse_boolean(value=value, field_name="required"))
        for value in ("false", "No", "0"):
            self.assertFalse(parse_boolean(value=value, field_name="required"))
        with self.assertRaises(InputValidationError):
            parse_boolean(value="maybe", field_name="required")
        self.assertEqual(species_name_from_fasta(fasta_name="A_species.fasta.gz"), "A_species")
        self.assertEqual(species_name_from_fasta(fasta_name="A_species.txt"), "A_species")
        with self.assertRaises(InputValidationError):
            species_name_from_fasta(fasta_name="")

    def test_manifest_and_coverage_states(self) -> None:
        """Required, optional and ambiguous alias states remain explicit."""

        with tempfile.TemporaryDirectory() as temporary:
            path = write_text(
                Path(temporary) / "species.tsv",
                (
                    "canonical_species_name\tsource_species_name\ttaxon_id\t"
                    "required\trole\taliases\n"
                    "Plant A\tPlant_A\t1\ttrue\ttarget\tAlias_A\n"
                    "Plant B\tPlant_B\t2\tfalse\ttarget\t\n"
                ),
            )
            records = load_species_manifest(path=path)
            coverage = assess_species_coverage(
                discovered_species=("Plant_A", "Alias_A"),
                manifest_records=records,
            )
            self.assertEqual(coverage[0]["status"], "AMBIGUOUS_ALIAS_MATCH")
            self.assertEqual(coverage[1]["status"], "MISSING_OPTIONAL")
            missing = assess_species_coverage(discovered_species=(), manifest_records=records)
            self.assertEqual(missing[0]["status"], "MISSING_REQUIRED")

    def test_manifest_rejects_schema_duplicates_empty_and_no_rows(self) -> None:
        """Invalid manifest structures fail before analysis."""

        header = "canonical_species_name\tsource_species_name\ttaxon_id\trequired\trole\taliases\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = {
                "schema": "wrong\theader\nA\tB\n",
                "duplicate": header + "A\tA\t1\ttrue\tx\t\nA\tB\t2\ttrue\tx\t\n",
                "empty": header + "A\t\t1\ttrue\tx\t\n",
                "rows": header,
            }
            for name, content in cases.items():
                with self.subTest(name=name), self.assertRaises(InputValidationError):
                    load_species_manifest(path=write_text(root / name, content))
