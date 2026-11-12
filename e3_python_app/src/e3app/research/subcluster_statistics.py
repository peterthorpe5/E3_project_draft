"""Complete statistics for the input family and its audited subclusters."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping

import duckdb
import pandas as pd

from .common import ResearchError, iter_fasta
from .subcluster_network import ID_COLUMNS, METRICS, STATUS_LABELS
from .taxonomy import CLUSTER_SPECIES_QUERY

LOGGER = logging.getLogger(__name__)
METRIC_NAMES = (
    "Exact identity (%)", "Centroid coverage (%)", "Member coverage (%)", "E-value", "Bit score",
)


def _family_lengths(
    *, connection: duckdb.DuckDBPyConnection, fasta: Path, output: Path,
) -> None:
    """Register complete sequence lengths and verify exact FASTA membership.

    Args:
        connection: DuckDB connection exposing the verified membership relation.
        fasta: Saved input family FASTA.
        output: Private temporary TSV used for a bounded-memory join.

    Raises:
        ResearchError: If FASTA and audited membership contain different identifiers.
    """
    with output.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("sequence_id", "length"))
        writer.writerows((identifier, len(sequence)) for identifier, sequence in iter_fasta(
            path=fasta,
        ))
    connection.read_csv(
        str(output), delimiter="\t", header=True,
        columns={"sequence_id": "VARCHAR", "length": "BIGINT"},
    ).create_view(view_name="protein_lengths")
    valid = connection.execute("""
        SELECT (SELECT count(*) FROM protein_lengths) =
               (SELECT count(DISTINCT sequence_id) FROM protein_lengths)
           AND (SELECT count(*) FROM protein_lengths) = (SELECT count(*) FROM membership)
           AND NOT EXISTS (
               SELECT 1 FROM membership ANTI JOIN protein_lengths USING (sequence_id)
           )
    """).fetchone()[0]
    if not valid:
        raise ResearchError("The saved FASTA and audited membership have different proteins.")


def _species_counts(
    *, connection: duckdb.DuckDBPyConnection, relation: duckdb.DuckDBPyRelation, group: str,
) -> pd.DataFrame:
    """Read complete species counts and aggregate the same reviewed taxa for both scopes.

    Args:
        connection: Research statistics connection.
        relation: Saved or recovered per-subcluster species counts.
        group: Exact selected subcluster, or empty for all input proteins.

    Returns:
        Reviewed taxon counts and recorded species without taxon IDs.
    """
    if not {"cluster_id", "species", "taxon_id", "member_count"}.issubset(relation.columns):
        raise ResearchError("The saved species table lacks taxonomy count fields.")
    relation.create_view(view_name="species_counts")
    return connection.execute("""
        WITH counts AS (
            SELECT cluster_id, species, try_cast(taxon_id AS BIGINT) AS taxon_id,
                   try_cast(member_count AS BIGINT) AS proteins
            FROM species_counts
        ), labelled AS (
            SELECT *, CASE WHEN taxon_id > 0 THEN taxon_id END AS reviewed_taxon_id,
                   CASE WHEN reviewed_taxon_id IS NULL THEN
                       coalesce(nullif(nullif(species, 'UNCLASSIFIED'), ''), 'Unclassified')
                   END AS recorded_species
            FROM counts
        )
        SELECT reviewed_taxon_id, coalesce(recorded_species, min(species)) AS species,
               sum(proteins)::BIGINT AS input_family,
               coalesce(sum(proteins) FILTER (WHERE cluster_id = ?), 0)::BIGINT
                   AS selected_subcluster
        FROM labelled GROUP BY reviewed_taxon_id, recorded_species
        ORDER BY input_family DESC, reviewed_taxon_id, species
    """, [group]).fetchdf()


def subcluster_statistics(
    *, membership: Path, fasta: Path | None, taxonomy: Path | None = None, group: str = "",
    member_taxonomy: Path | None = None,
    recovered_taxonomy: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, pd.DataFrame]:
    """Summarise all saved assignments and compare one subcluster with its input family.

    Args:
        membership: Complete, verified audited Parquet or TSV membership.
        fasta: Verified unaligned input FASTA, when present.
        taxonomy: Optional verified per-subcluster species count TSV.
        group: Exact audited subcluster ID, or empty for whole-family statistics.
        member_taxonomy: Optional checksummed per-protein taxonomy TSV saved with the job.
        recovered_taxonomy: Exact member evidence recovered from a published HOG.

    Returns:
        Partition, family comparison, audit counts, centroid metrics and optional species tables.

    Raises:
        ResearchError: If a required result, selection or source identity is invalid.
    """
    try:
        with (
            TemporaryDirectory(prefix="e3-subcluster-statistics-") as temporary,
            duckdb.connect(config={"threads": 2}) as connection,
        ):
            relation = (
                connection.read_parquet(str(membership)) if membership.suffix == ".parquet"
                else connection.read_csv(
                    str(membership), delimiter="\t", header=True, all_varchar=True,
                )
            )
            if not set((*ID_COLUMNS, *METRICS, "native_representative_id")).issubset(
                relation.columns
            ):
                raise ResearchError("The saved membership lacks the complete centroid audit.")
            relation.create_view(view_name="membership")
            partition = connection.execute("""
                WITH sizes AS (
                    SELECT 0 AS stage, count(*) AS size
                    FROM membership GROUP BY native_representative_id
                    UNION ALL
                    SELECT 1 AS stage, count(*) AS size
                    FROM membership GROUP BY subcluster_id
                )
                SELECT CASE WHEN stage = 0 THEN 'Native DIAMOND' ELSE 'After exact audit' END
                           AS partition,
                       count(*) AS clusters, count(*) FILTER (WHERE size > 1) AS multi_member,
                       count(*) FILTER (WHERE size = 1) AS singletons,
                       min(size) AS smallest_cluster, median(size) AS median_cluster_size,
                       max(size) AS largest_cluster
                FROM sizes GROUP BY stage ORDER BY stage
            """).fetchdf()
            if partition.empty:
                raise ResearchError("The saved audit contains no proteins.")
            counts = connection.execute("""
                SELECT alignment_status, count(*) AS input_family,
                       count(*) FILTER (WHERE subcluster_id = ?) AS selected_subcluster
                FROM membership GROUP BY alignment_status ORDER BY alignment_status
            """, [group]).fetchdf()
            counts["audit_outcome"] = counts.pop("alignment_status").replace(STATUS_LABELS)
            counts = counts[["audit_outcome", "input_family", "selected_subcluster"]]
            total = int(counts["input_family"].sum())
            selected_count = int(counts["selected_subcluster"].sum())
            if group and not selected_count:
                raise ResearchError("The selected subcluster is absent from the saved audit.")
            comparison = pd.DataFrame([
                {"scope": "Input family", "proteins": total, "input_family_percent": 100.0},
                *([{
                    "scope": "Selected subcluster", "proteins": selected_count,
                    "input_family_percent": 100.0 * selected_count / total,
                }] if group else []),
            ]).set_index("scope")
            if fasta is not None:
                _family_lengths(
                    connection=connection, fasta=fasta, output=Path(temporary) / "lengths.tsv",
                )
                lengths = connection.execute("""
                    WITH scoped AS (
                        SELECT 'Input family' AS scope, length FROM protein_lengths
                        UNION ALL
                        SELECT 'Selected subcluster' AS scope, length
                        FROM protein_lengths JOIN membership USING (sequence_id)
                        WHERE subcluster_id = ?
                    )
                    SELECT scope, min(length) AS minimum_length, avg(length) AS mean_length,
                           median(length) AS median_length, max(length) AS maximum_length
                    FROM scoped GROUP BY scope
                """, [group]).fetchdf()
                comparison = comparison.join(lengths.set_index("scope"))
            expressions = ", ".join(
                f"{stat}(try_cast({field} AS DOUBLE))"
                for field in METRICS for stat in ("count", "min", "median", "max")
            )
            values = connection.execute(
                f"SELECT {expressions} FROM membership "
                "WHERE alignment_status = 'EXACT_THRESHOLDS_PASS' "
                "AND sequence_id <> audited_representative_id "
                "AND (? = '' OR subcluster_id = ?)",
                [group, group],
            ).fetchone()
            alignment = pd.DataFrame(
                [(name, *values[i * 4:i * 4 + 4]) for i, name in enumerate(METRIC_NAMES)],
                columns=("metric", "passing_alignments", "minimum", "median", "maximum"),
            )
            tables = {"partition": partition, "centroid_metrics": alignment}
            if recovered_taxonomy or member_taxonomy is not None:
                if recovered_taxonomy:
                    metadata = pd.DataFrame([
                        {"sequence_id": identifier, **record}
                        for identifier, record in recovered_taxonomy.items()
                    ]).astype({"taxon_id": "Int64"})
                    connection.register("member_species", metadata)
                else:
                    connection.read_csv(
                        str(member_taxonomy), delimiter="\t", header=True, all_varchar=True,
                    ).create_view(view_name="member_species")
                tables["member_taxonomy"] = connection.execute("""
                    SELECT m.sequence_id, m.subcluster_id, t.species,
                           try_cast(t.taxon_id AS BIGINT) AS taxon_id,
                           CASE WHEN try_cast(t.taxon_id AS BIGINT) > 0 THEN 'REVIEWED'
                                WHEN t.species IS NOT NULL THEN 'RECORDED_SPECIES'
                                ELSE 'UNCLASSIFIED' END AS mapping_status
                    FROM membership m LEFT JOIN member_species t USING(sequence_id)
                    WHERE (? = '' OR m.subcluster_id = ?)
                    ORDER BY m.subcluster_id, m.sequence_id
                """, [group, group]).fetchdf()
            if "member_taxonomy" in tables or taxonomy is not None:
                if "member_taxonomy" in tables:
                    species_relation = connection.sql(CLUSTER_SPECIES_QUERY)
                else:
                    species_relation = connection.read_csv(
                        str(taxonomy), delimiter="\t", header=True, all_varchar=True,
                    )
                species = _species_counts(
                    connection=connection, relation=species_relation, group=group,
                )
                reviewed = species.loc[species["reviewed_taxon_id"].notna()]
                for scope, column in (
                    ("Input family", "input_family"),
                    ("Selected subcluster", "selected_subcluster"),
                ):
                    if scope in comparison.index:
                        count = int(reviewed[column].sum())
                        comparison.loc[scope, "reviewed_taxa"] = int(reviewed[column].gt(0).sum())
                        comparison.loc[scope, "proteins_with_reviewed_taxonomy"] = count
                tables["species_counts"] = species
            if not group:
                counts = counts.drop(columns="selected_subcluster")
                if "species_counts" in tables:
                    tables["species_counts"] = tables["species_counts"].drop(
                        columns="selected_subcluster",
                    )
            tables["input_family_comparison"] = comparison.reset_index()
            tables["audit_outcomes"] = counts
            LOGGER.info("Summarised %d audited proteins for subcluster %s", total, group or "all")
            return tables
    except (duckdb.Error, OSError, UnicodeError) as exc:
        raise ResearchError(
            f"Could not read the saved subcluster statistics inputs. {exc}"
        ) from exc
