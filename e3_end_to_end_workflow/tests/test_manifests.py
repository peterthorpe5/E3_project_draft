"""Tests for species, accession and shortlist manifests."""

from __future__ import annotations

from pathlib import Path

import pytest

from e3workflow.errors import ManifestError
from e3workflow.manifests import (
    parse_boolean,
    validate_accessions,
    validate_proteomes,
    validate_seed_evidence,
    validate_shortlist,
)


def test_boolean_parser() -> None:
    """Documented Boolean spellings parse and other text fails."""

    assert parse_boolean(" YES ", "flag") is True
    assert parse_boolean("0", "flag") is False
    with pytest.raises(ManifestError):
        parse_boolean("perhaps", "flag")


def test_committed_manifests_are_valid(package_root: Path) -> None:
    """The synthetic manifests exercise all three positive validators."""

    config = package_root / "config"
    assert len(validate_proteomes(config / "synthetic_proteomes.tsv", True)) == 2
    assert len(
        validate_accessions(config / "synthetic_seeds.tsv", {"evidence_type", "source"})
    ) == 2
    assert len(validate_seed_evidence(config / "synthetic_seeds.tsv")) == 2
    assert validate_shortlist(config / "synthetic_shortlist.tsv")[0]["accession"] == "Q9SA03"


def test_proteome_manifest_defensive_paths(tmp_path: Path) -> None:
    """Duplicate, empty, excluded and checksum-failing proteomes are detected."""

    fasta = tmp_path / "one.faa"
    fasta.write_text(">x\nM\n", encoding="utf-8")
    header = "species_id\tscientific_name\tfasta_path\tfasta_sha256\tinclude\n"
    manifest = tmp_path / "proteomes.tsv"
    manifest.write_text(header, encoding="utf-8")
    with pytest.raises(ManifestError, match="no rows"):
        validate_proteomes(manifest, False)
    manifest.write_text(header + "x\tSpecies x\tone.faa\tbad\tfalse\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="zero included"):
        validate_proteomes(manifest, False)
    manifest.write_text(header + "x\t\tone.faa\tbad\ttrue\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="scientific_name"):
        validate_proteomes(manifest, False)
    manifest.write_text(header + "x\tSpecies x\tmissing.faa\tbad\ttrue\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="does not exist"):
        validate_proteomes(manifest, False)
    manifest.write_text(header + "x\tSpecies x\tone.faa\tbad\ttrue\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="Invalid fasta_sha256"):
        validate_proteomes(manifest, True)
    manifest.write_text(
        header
        + "x\tSpecies x\tone.faa\t"
        + "0" * 64
        + "\ttrue\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="checksum mismatch"):
        validate_proteomes(manifest, True)
    manifest.write_text(
        header
        + "x\tSpecies x\tone.faa\tbad\ttrue\n"
        + "x\tSpecies y\tone.faa\tbad\ttrue\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="duplicate species_id"):
        validate_proteomes(manifest, False)
    manifest.write_text(header + "bad/id\tSpecies x\tone.faa\tbad\ttrue\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="Unsafe species_id"):
        validate_proteomes(manifest, False)


def test_accession_and_shortlist_errors(tmp_path: Path) -> None:
    """Headers, duplicates, decisions and approvals are mandatory."""

    seeds = tmp_path / "seeds.tsv"
    seeds.write_text("accession\tsource\nQ\tx\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="Missing columns"):
        validate_accessions(seeds, {"source", "evidence_type"})
    seeds.write_text("accession\tsource\nQ\tx\nQ\ty\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="duplicate"):
        validate_accessions(seeds, {"source"})
    seeds.write_text("accession\tsource\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="no rows"):
        validate_accessions(seeds, {"source"})
    seeds.write_text("accession\tsource\nQ\t\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="Missing source"):
        validate_accessions(seeds, {"source"})
    with pytest.raises(ManifestError, match="Missing columns"):
        validate_seed_evidence(seeds)
    shortlist = tmp_path / "shortlist.tsv"
    header = "accession\tdecision\tapproved_by\tapproved_at_utc\trationale\n"
    shortlist.write_text(header + "Q\tmaybe\tme\tnow\tbecause\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="Unsupported"):
        validate_shortlist(shortlist)
    shortlist.write_text(header + "Q\treject\tme\tnow\tbecause\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="no approved"):
        validate_shortlist(shortlist)
