"""Tiny official-schema data and deterministic provider fixtures."""

from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from e3app.research.common import ResearchConfig


@pytest.fixture
def research_config(tmp_path: Path) -> ResearchConfig:
    """Create a row-group-spanning DeepClust release with an unrelated cluster."""
    sequences = tmp_path / "sequences.parquet"
    pq.write_table(
        pa.table(
            {
                "f0": ["UNIPROT_P1", "B", "UNIPROT_P2", "C", "D", "E"],
                "f1": ["ACDE*", "ACDF", "ACDE", "AAAA", "AAAT", "GGGG"],
                "f2": ["GLOBAL_A", "GLOBAL_A", "GLOBAL_A", "GLOBAL_B", "GLOBAL_B", "GLOBAL_C"],
                "f3": list(range(6)),
            }
        ),
        sequences,
        row_group_size=2,
    )
    index = tmp_path / "index.parquet"
    pq.write_table(
        pa.table(
            {
                "CLUSTER": ["GLOBAL_A", "GLOBAL_B", "GLOBAL_C"],
                "NMEMBER": [3, 2, 1],
                "RowStart": [0, 3, 5],
                "RowGroup": ["0,1", "1,2", "2"],
            }
        ),
        index,
    )
    sequence_map = tmp_path / "map.parquet"
    pq.write_table(
        pa.table(
            {
                "f0": ["UNIPROT_P1", "B", "UNIPROT_P2", "C", "D", "E", "multi", "multi", "small"],
                "f1": [
                    "GLOBAL_A",
                    "GLOBAL_A",
                    "GLOBAL_A",
                    "GLOBAL_B",
                    "GLOBAL_B",
                    "GLOBAL_C",
                    "GLOBAL_A",
                    "GLOBAL_B",
                    "UNINDEXED",
                ],
            }
        ),
        sequence_map,
    )
    taxonomy = tmp_path / "taxonomy.tsv"
    taxonomy.write_text(
        "sequence_id\tspecies\ttaxon_id\tmapping_status\n"
        "UNIPROT_P1\tHuman\t9606\tREVIEWED\nB\tPlant\t3702\tREVIEWED\n"
        "C\tHuman\t9606\tREVIEWED\nD\tPlant\t3702\tUNREVIEWED\n"
    )
    bridge = tmp_path / "bridge.tsv"
    bridge.write_text("input_id\tsequence_id\nlocal-A\tB\n")
    return ResearchConfig(
        workspace=tmp_path / "work",
        index=str(index),
        sequences=str(sequences),
        sequence_map=str(sequence_map),
        taxonomy=str(taxonomy),
        identifier_bridge=str(bridge),
        threads=1,
        memory_gb=1,
    )


@pytest.fixture
def protein_fasta(tmp_path: Path) -> Path:
    """Create three similar proteins with exact stable identifiers."""
    path = tmp_path / "source.fasta"
    path.write_text(
        ">a\nACDEFGHIKLMNPQRSTVWY\n>b\nACDEFGHIKLMNPQRSTVWY\n>c\nACDEFGHIKLMNPQRSTVWF\n"
    )
    return path


@pytest.fixture
def model_pdb() -> str:
    """Return a valid two-residue CA-only model with confidence values."""
    return (
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 80.00           C  \n"
        "ATOM      2  CA  CYS A   2       4.000   5.000   6.000  1.00 90.00           C  \nEND\n"
    )
