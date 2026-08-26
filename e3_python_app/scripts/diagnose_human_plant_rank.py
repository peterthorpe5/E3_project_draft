#!/usr/bin/env python3
"""Diagnose why one parent rank did or did not enter the human/plant extension."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Sequence

import duckdb


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse named command-line arguments.

    Args:
        argv: Optional explicit argument sequence.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-run", type=Path, required=True)
    parser.add_argument("--extension-output", type=Path, required=True)
    parser.add_argument("--rank", type=int, default=7)
    return parser.parse_args(argv)


def resolve_first(*, root: Path, candidates: Sequence[str], label: str) -> Path:
    """Return the first existing production authority.

    Args:
        root: Parent run root.
        candidates: Relative candidate paths in priority order.
        label: Human-readable authority name.

    Returns:
        Resolved existing path.

    Raises:
        FileNotFoundError: If none of the candidate paths exists.
    """
    for relative in candidates:
        candidate = (root / relative).resolve()
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Could not find {label} below {root}")


def quote_literal(path: Path) -> str:
    """Return a single-quoted DuckDB path literal."""
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def table_reader(path: Path) -> str:
    """Return a DuckDB reader expression for Parquet or tab-separated input."""
    literal = quote_literal(path)
    if path.suffix.lower() == ".parquet":
        return f"read_parquet({literal})"
    return f"read_csv_auto({literal}, delim='\\t', header=true)"


def published_ranks(groups_path: Path) -> set[int]:
    """Return original review ranks published in the extension group manifest."""
    if not groups_path.is_file():
        return set()
    with groups_path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return {
            int(str(row["review_rank"]).strip())
            for row in rows
            if str(row.get("review_rank", "")).strip()
        }


def diagnose(*, parent_run: Path, extension_output: Path, rank: int) -> None:
    """Print one TSV eligibility diagnosis for an original parent rank.

    Args:
        parent_run: Completed parent workflow root.
        extension_output: Human-and-plant extension output root.
        rank: Original final evolutionary rank to inspect.
    """
    if rank < 1:
        raise ValueError("rank must be at least 1")
    root = parent_run.expanduser().resolve()
    shortlist = resolve_first(
        root=root,
        candidates=(
            "10_integrated_resource/final_results/"
            "top_computational_review_shortlist.parquet",
            "10_integrated_resource/final_results/"
            "top_computational_review_shortlist.tsv",
            "10_integrated_resource/final_results/"
            "top_50_computational_review_shortlist.parquet",
        ),
        label="final evolutionary shortlist",
    )
    structural_accessions = resolve_first(
        root=root,
        candidates=(
            "08_shortlist_gate/tables/structural_analysis_accessions.parquet",
        ),
        label="plant structural-accession authority",
    )
    group_sequences = resolve_first(
        root=root,
        candidates=(
            "05_orthology/orthology/tables/"
            "candidate_group_member_sequences.parquet",
            "05_orthology/tables/candidate_group_member_sequences.parquet",
        ),
        label="candidate-group sequence authority",
    )
    structural_summary = resolve_first(
        root=root,
        candidates=(
            "09b_structural_alignment/structural_alignment/tables/"
            "structural_alignment_summary.parquet",
        ),
        label="plant structural summary",
    )
    query = f"""
        WITH ranked AS (
          SELECT DISTINCT
                 TRY_CAST(final_evolutionary_rank AS BIGINT) AS review_rank,
                 CAST(lead_cluster_id AS VARCHAR) AS cluster_id,
                 CAST(primary_group_type AS VARCHAR) AS primary_group_type,
                 CAST(primary_group_id AS VARCHAR) AS primary_group_id
          FROM {table_reader(shortlist)}
          WHERE TRY_CAST(final_evolutionary_rank AS BIGINT) = ?
        )
        SELECT r.review_rank,
               r.cluster_id,
               r.primary_group_type,
               r.primary_group_id,
               (
                 SELECT count(*)
                 FROM {table_reader(structural_accessions)} a
                 WHERE CAST(a.cluster_id AS VARCHAR) = r.cluster_id
                   AND CAST(a.primary_group_type AS VARCHAR) = r.primary_group_type
                   AND CAST(a.primary_group_id AS VARCHAR) = r.primary_group_id
               ) AS structural_authority_rows,
               (
                 SELECT count(DISTINCT trim(CAST(m.parsed_accession AS VARCHAR)))
                 FROM {table_reader(group_sequences)} m
                 WHERE CAST(m.cluster_id AS VARCHAR) = r.cluster_id
                   AND CAST(m.record_type AS VARCHAR) = r.primary_group_type
                   AND CAST(m.group_id AS VARCHAR) = r.primary_group_id
                   AND CAST(m.species AS VARCHAR) = 'Homo_sapiens'
                   AND trim(coalesce(CAST(m.parsed_accession AS VARCHAR), '')) != ''
               ) AS exact_human_accession_count,
               (
                 SELECT count(DISTINCT trim(CAST(s.reference_accession AS VARCHAR)))
                 FROM {table_reader(structural_summary)} s
                 WHERE CAST(s.cluster_id AS VARCHAR) = r.cluster_id
                   AND CAST(s.primary_group_type AS VARCHAR) = r.primary_group_type
                   AND CAST(s.primary_group_id AS VARCHAR) = r.primary_group_id
                   AND trim(coalesce(CAST(s.reference_accession AS VARCHAR), '')) != ''
               ) AS distinct_plant_reference_count
        FROM ranked r
        ORDER BY r.primary_group_id
    """
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(query, [rank]).fetchall()
        fields = [str(item[0]) for item in connection.description]
    published = published_ranks(
        extension_output.expanduser().resolve() / "manifests" / "groups.tsv"
    )
    output_fields = fields + ["published_in_extension", "diagnosis"]
    print("\t".join(output_fields))
    if not result:
        print(
            "\t".join(
                [str(rank), "", "", "", "0", "0", "0", "false", "NOT_IN_SHORTLIST"]
            )
        )
        return
    for values in result:
        row = dict(zip(fields, values))
        structural_rows = int(row["structural_authority_rows"])
        human_count = int(row["exact_human_accession_count"])
        reference_count = int(row["distinct_plant_reference_count"])
        is_published = rank in published
        if structural_rows == 0:
            diagnosis = "NO_PARENT_STRUCTURAL_AUTHORITY"
        elif human_count == 0:
            diagnosis = "NO_EXACT_HUMAN_GROUP_MEMBER"
        elif reference_count == 0:
            diagnosis = "NO_PRESERVED_PLANT_REFERENCE"
        elif reference_count > 1:
            diagnosis = "AMBIGUOUS_PLANT_REFERENCE"
        elif not is_published:
            diagnosis = "ELIGIBILITY_CHECKS_PASS_BUT_NOT_PUBLISHED"
        else:
            diagnosis = "QUALIFIED_AND_PUBLISHED"
        print(
            "\t".join(
                [
                    *(str(row[field]) for field in fields),
                    str(is_published).lower(),
                    diagnosis,
                ]
            )
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the rank diagnostic and return a process status."""
    arguments = parse_args(argv)
    diagnose(
        parent_run=arguments.parent_run,
        extension_output=arguments.extension_output,
        rank=arguments.rank,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
