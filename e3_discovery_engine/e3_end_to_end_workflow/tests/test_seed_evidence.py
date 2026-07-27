"""Tests for deterministic known-E3 evidence derivation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e3workflow.cli import main
from e3workflow.errors import ManifestError
from e3workflow.io_utils import read_tsv
from e3workflow.seed_evidence import (
    EVIDENCE_COLUMNS,
    build_seed_evidence,
    default_provenance_path,
    derive_seed_evidence,
)


def _write_source(path: Path, metadata: object | None = None) -> None:
    """Write one representative discovery-engine seed record."""
    payload = {
        "category": "U-box",
        "ubiquitin_go_term": "Ubiquitin GO term",
        "exclusion_go_term": "",
        "organism": "Homo sapiens (Human)",
        "organism_id": "9606",
        "sequence_md5": "ca98cf7acb34842688df891e2dc1988b",
    }
    if metadata is not None:
        payload = metadata
    columns = (
        "seed_id",
        "source_value",
        "source_column",
        "source_row",
        "source_path",
        "seed_metadata_json",
    )
    values = (
        "A0A024R0Y4",
        "A0A024R0Y4",
        "entry",
        "42417",
        "/project/files/e3_ligases.tsv",
        json.dumps(payload, separators=(",", ":")),
    )
    path.write_text(
        "\t".join(columns) + "\n" + "\t".join(values) + "\n",
        encoding="utf-8",
    )


def test_build_seed_evidence_and_provenance(tmp_path: Path) -> None:
    """The derived gzip retains selected evidence and checksum provenance."""
    source = tmp_path / "known_e3_seeds.tsv"
    output = tmp_path / "data" / "known_e3_seed_evidence.tsv.gz"
    _write_source(source)
    summary = build_seed_evidence(source=source, output=output)
    fields, rows = read_tsv(output)
    assert fields == list(EVIDENCE_COLUMNS)
    assert rows[0]["accession"] == "A0A024R0Y4"
    assert rows[0]["e3_category"] == "U-box"
    assert rows[0]["taxon_id"] == "9606"
    assert summary["rows"] == 1
    provenance = default_provenance_path(output)
    assert read_tsv(provenance)[1][0]["evidence_sha256"] == summary["sha256"]
    with pytest.raises(ManifestError, match="already exists"):
        build_seed_evidence(source=source, output=output)
    assert build_seed_evidence(source=source, output=output, force=True)["rows"] == 1


def test_seed_evidence_cli(tmp_path: Path) -> None:
    """The named-option CLI builds an explicitly located evidence archive."""
    source = tmp_path / "source.tsv"
    output = tmp_path / "evidence.tsv.gz"
    provenance = tmp_path / "custom.provenance.tsv"
    _write_source(source)
    assert (
        main(
            [
                "build-seed-evidence",
                "--source",
                str(source),
                "--output",
                str(output),
                "--provenance-output",
                str(provenance),
            ]
        )
        == 0
    )
    assert output.is_file()
    assert provenance.is_file()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("seed_id\nQ\n", "Missing source seed columns"),
        (
            "seed_id\tsource_value\tsource_column\tsource_row\tsource_path\t"
            "seed_metadata_json\nQ\tQ\tentry\t1\t/source\tnot-json\n",
            "Invalid seed_metadata_json",
        ),
        (
            "seed_id\tsource_value\tsource_column\tsource_row\tsource_path\t"
            "seed_metadata_json\nQ\tQ\tentry\t1\t/source\t[]\n",
            "not an object",
        ),
    ],
)
def test_invalid_seed_sources(tmp_path: Path, content: str, message: str) -> None:
    """Malformed source schemas and metadata fail with actionable context."""
    source = tmp_path / "bad.tsv"
    source.write_text(content, encoding="utf-8")
    with pytest.raises(ManifestError, match=message):
        derive_seed_evidence(source)


def test_empty_duplicate_and_output_suffix_errors(tmp_path: Path) -> None:
    """Empty sources, duplicate accessions and unsafe output names fail closed."""
    source = tmp_path / "source.tsv"
    _write_source(source)
    header, row = source.read_text(encoding="utf-8").splitlines()
    source.write_text(header + "\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="contains no rows"):
        derive_seed_evidence(source)
    source.write_text(header + "\n" + row + "\n" + row + "\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="duplicate seed_id"):
        derive_seed_evidence(source)
    with pytest.raises(ManifestError, match="must end"):
        default_provenance_path(tmp_path / "evidence.tsv")
