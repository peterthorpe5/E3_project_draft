"""Reusable miniature production-shaped fixtures."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from e3orthology.config import load_config
from e3orthology.pipeline import RuntimePaths, build_runtime_paths


def write_text(path: Path, text: str) -> Path:
    """Write fixture text and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def create_sqlite(path: Path) -> Path:
    """Create the inherited orthology subset used by regression tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE orthogroups(
            id INTEGER PRIMARY KEY,
            accession TEXT,
            organism TEXT,
            orthogroup TEXT
        );
        CREATE TABLE hogs(
            id INTEGER PRIMARY KEY,
            accession TEXT,
            organism TEXT,
            hog TEXT
        );
        INSERT INTO orthogroups(accession, organism, orthogroup)
        VALUES ('Q9SA03', 'Arabidopsis thaliana', 'OG0001686');
        INSERT INTO hogs(accession, organism, hog)
        VALUES ('Q9SA03', 'Arabidopsis_thaliana', 'N0.HOG0002084');
        """
    )
    connection.commit()
    connection.close()
    return path


def create_candidate_parquet(path: Path) -> Path:
    """Create a candidate resource containing one mapped and one unmatched seed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "representative_id": ["cluster_1", "cluster_2"],
            "matched_seed_ids_calculated": ["Q9SA03", "NOPE01"],
            "representative_original_id": ["rep one", "rep two"],
            "representative_entry": ["REP1", "REP2"],
        }
    )
    pq.write_table(table, path)
    return path


def create_fixture(root: Path) -> tuple[RuntimePaths, dict]:
    """Create a complete two-species OrthoFinder and inherited-data fixture."""

    source_root = root / "source"
    results = source_root / "nested" / "Results_Feb26"
    write_text(
        results / "WorkingDirectory" / "SpeciesIDs.txt",
        "0: Arabidopsis_thaliana.fasta\n1: Homo_sapiens.fasta\n",
    )
    write_text(
        results / "WorkingDirectory" / "SequenceIDs.txt",
        (
            "0_0: sp|Q9SA03|FB27_ARATH Putative F-box protein\n"
            "1_0: sp|P12345|TEST_HUMAN Test protein\n"
        ),
    )
    write_text(
        results / "Orthogroups" / "Orthogroups.tsv",
        (
            "Orthogroup\tArabidopsis_thaliana\tHomo_sapiens\n"
            "OG0001686\tsp|Q9SA03|FB27_ARATH\tsp|P12345|TEST_HUMAN\n"
        ),
    )
    write_text(
        results / "Phylogenetic_Hierarchical_Orthogroups" / "N0.tsv",
        (
            "HOG\tOG\tGene Tree Parent Clade\tArabidopsis_thaliana\tHomo_sapiens\n"
            "N0.HOG0002084\tOG0001686\tn0\tsp|Q9SA03|FB27_ARATH\t"
            "sp|P12345|TEST_HUMAN\n"
        ),
    )
    manifest = write_text(
        root / "species.tsv",
        (
            "canonical_species_name\tsource_species_name\ttaxon_id\trequired\trole\taliases\n"
            "Arabidopsis thaliana\tArabidopsis_thaliana\t3702\ttrue\ttarget\t\n"
            "Homo sapiens\tHomo_sapiens\t9606\ttrue\treference\t\n"
        ),
    )
    candidates = create_candidate_parquet(root / "candidates.parquet")
    database = create_sqlite(root / "inherited.db")
    config = load_config(path=None)
    config["input"]["expected_species_count"] = 2
    config["execution"]["parquet_block_size_bytes"] = 1_024
    paths = build_runtime_paths(
        project_root=root,
        orthofinder_source_root=source_root,
        results_directory_name="Results_Feb26",
        candidate_evidence=candidates,
        sqlite_database=database,
        species_manifest=manifest,
        output_root=root / "output",
        run_name="fixture_run",
        config_path=None,
    )
    return paths, config
