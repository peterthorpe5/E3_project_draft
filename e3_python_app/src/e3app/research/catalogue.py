"""Indexed DeepClust access with audited, many-to-many sequence mappings."""

from __future__ import annotations

from contextlib import contextmanager
import csv
import hashlib
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Iterator, Sequence

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .common import ResearchConfig, ResearchError, bounded_number, normalise_protein, write_tsv

LOGGER = logging.getLogger(__name__)
SOURCE_URL = "https://objectstore.hpccloud.mpcdf.mpg.de/deepclust/index.html"


def _column(*, columns: Sequence[str], choices: Sequence[str], required: bool = True) -> str:
    """Resolve a documented source column without fuzzy matching.

    Args:
        columns: Physical table column names.
        choices: Explicit accepted aliases in preference order.
        required: Require a matching column.

    Returns:
        Quoted exact identifier, or a typed-null expression for an optional field.

    Raises:
        ResearchError: If a required contract cannot be resolved.
    """
    selected = next((name for name in choices if name in columns), None)
    if selected is None:
        if required:
            raise ResearchError("DeepClust source requires one of: " + ", ".join(choices))
        return "NULL"
    return '"' + selected.replace('"', '""') + '"'


def _source_view(*, connection: object, path: str, name: str) -> list[str]:
    """Open a local/mounted Parquet or TSV as a lazy DuckDB view.

    Args:
        connection: Isolated query connection.
        path: Configured existing source file.
        name: Internal fixed view identifier.

    Returns:
        Source column names without collecting its rows.

    Raises:
        ResearchError: If the configured source is missing or unreadable.
    """
    source = Path(path).expanduser()
    if not path or not source.is_file():
        raise ResearchError(f"Configure an existing mounted source file for {name}: {path}")
    try:
        relation = (
            connection.read_csv(str(source), delimiter="\t", header=True, all_varchar=True)
            if source.suffix.lower() == ".tsv"
            else connection.read_parquet(str(source))
        )
        relation.create_view(view_name=name)
        return relation.columns
    except duckdb.Error as exc:
        raise ResearchError(f"Could not inspect DeepClust source {name}") from exc


@contextmanager
def open_catalogue(
    *, config: ResearchConfig, require_index: bool = True
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Create bounded-memory views over the official release and optional reviewed bridges.

    Args:
        config: Operator profile; source files are never modified.
        require_index: Require a global cluster index for discovery operations.

    Yields:
        Connection with canonical clusters, sequence_map and optional taxonomy views.
    """
    config.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    spill = Path(os.environ.get("TMPDIR", config.workspace / "temporary")).resolve()
    spill.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(
        config={
            "threads": config.threads,
            "memory_limit": f"{config.memory_gb}GB",
            "temp_directory": str(spill),
        }
    )
    try:
        if require_index or config.index:
            columns = _source_view(connection=connection, path=config.index, name="index_source")
        else:
            columns = []
        if columns:
            _create_cluster_view(connection=connection, columns=columns)
        if config.sequence_map:
            columns = _source_view(
                connection=connection, path=config.sequence_map, name="map_source"
            )
            sequence = _column(
                columns=columns,
                choices=(
                    "sequence_id",
                    "SeqID",
                    "SeqId",
                    "SequenceID",
                    "SEQID",
                    "seq_id",
                    "f0",
                ),
            )
            cluster = _column(
                columns=columns,
                choices=(
                    "cluster_id",
                    "CLUSTER",
                    "CLUSTERID",
                    "ClustID",
                    "ClusterID",
                    "ClustId",
                    "f2",
                    "f1",
                ),
            )
            connection.execute(
                "CREATE VIEW sequence_map AS SELECT DISTINCT "
                f"CAST({sequence} AS VARCHAR) AS sequence_id, "
                f"CAST({cluster} AS VARCHAR) AS cluster_id "
                "FROM map_source"
            )
        _create_optional_views(connection=connection, config=config)
        yield connection
    except duckdb.Error as exc:
        LOGGER.exception("DeepClust query failed")
        raise ResearchError("DeepClust sources do not satisfy their configured schema") from exc
    finally:
        connection.close()


def _create_cluster_view(*, connection: object, columns: Sequence[str]) -> None:
    """Create a canonical cluster view over the official index.

    Args:
        connection: Open catalogue connection.
        columns: Actual index column names.
    """
    cluster = _column(columns=columns, choices=("CLUSTER", "cluster_id", "ClusterID", "f2"))
    count = _column(columns=columns, choices=("NMEMBER", "member_count", "size"))
    start = _column(columns=columns, choices=("RowStart", "row_start"), required=False)
    groups = _column(columns=columns, choices=("RowGroup", "row_groups"), required=False)
    connection.execute(
        f"CREATE VIEW clusters AS SELECT CAST({cluster} AS VARCHAR) AS cluster_id, "
        f"TRY_CAST({count} AS BIGINT) AS member_count, TRY_CAST({start} AS BIGINT) AS row_start, "
        f"CAST({groups} AS VARCHAR) AS row_groups FROM index_source"
    )


def _create_optional_views(*, connection: object, config: ResearchConfig) -> None:
    """Expose explicitly configured identifier and reviewed taxonomy tables.

    Args:
        connection: Open catalogue connection.
        config: Trusted profile.
    """
    if config.identifier_bridge:
        _source_view(connection=connection, path=config.identifier_bridge, name="identifier_bridge")
        connection.execute("SELECT input_id,sequence_id FROM identifier_bridge LIMIT 0")
    if config.taxonomy:
        columns = _source_view(connection=connection, path=config.taxonomy, name="taxonomy_source")
        required = {"sequence_id", "species", "taxon_id"}
        if not required.issubset(columns):
            raise ResearchError("Sequence taxonomy requires sequence_id, species and taxon_id")
        lineage = _column(columns=columns, choices=("lineage_taxon_ids",), required=False)
        reviewed = "WHERE upper(mapping_status)='REVIEWED'" if "mapping_status" in columns else ""
        connection.execute(
            "CREATE VIEW taxonomy AS SELECT DISTINCT CAST(sequence_id AS VARCHAR) AS sequence_id, "
            "CAST(species AS VARCHAR) AS species, TRY_CAST(taxon_id AS BIGINT) AS taxon_id, "
            f"CAST({lineage} AS VARCHAR) AS lineage_taxon_ids FROM taxonomy_source {reviewed}"
        )
    if config.cluster_taxonomy:
        _source_view(connection=connection, path=config.cluster_taxonomy, name="cluster_taxonomy")
        connection.execute("SELECT cluster_id,taxon_id,species FROM cluster_taxonomy LIMIT 0")


def sequence_aliases(*, identifier: str, prefixes: Sequence[str] = ()) -> tuple[str, ...]:
    """Create explicit namespace aliases while retaining the exact original identifier.

    Args:
        identifier: Protein input identifier, including a possible UniProt FASTA header ID.
        prefixes: Operator-declared DeepClust source prefixes.

    Returns:
        Exact original, parsed UniProt accession when applicable, and declared aliases.

    Raises:
        ResearchError: If an identifier is blank or includes control characters.
    """
    value = str(identifier).strip()
    if (
        not value
        or len(value) > 2_000
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise ResearchError("Sequence identifiers must be non-empty and contain no whitespace")
    values = [value]
    parts = value.split("|")
    if len(parts) >= 3 and parts[0] in {"sp", "tr"} and parts[1]:
        values.append(parts[1])
    return tuple(
        dict.fromkeys([*values, *(prefix + item for prefix in prefixes for item in values)])
    )


def resolve_sequence_ids(
    *, connection: object, identifiers: Sequence[str], prefixes: Sequence[str] = ()
) -> pd.DataFrame:
    """Map input sequences to all matching global clusters with explicit unmatched rows.

    Args:
        connection: Open canonical catalogue.
        identifiers: At most 10,000 input accessions or exact source IDs.
        prefixes: Explicit accepted source namespaces.

    Returns:
        One-to-many mapping with alias, global sequence, cluster size and mapping status.

    Raises:
        ResearchError: If inputs exceed bounds or no sequence index is configured.
    """
    if not identifiers or len(identifiers) > 10_000:
        raise ResearchError("Resolve between 1 and 10000 sequence identifiers per request")
    names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    if "sequence_map" not in names:
        raise ResearchError(
            "Configure the DeepClust sequence-to-cluster map before resolving inputs"
        )
    aliases = pd.DataFrame(
        data=[
            {"input_id": str(identifier).strip(), "query_alias": alias}
            for identifier in dict.fromkeys(identifiers)
            for alias in sequence_aliases(identifier=identifier, prefixes=prefixes)
        ]
    )
    connection.register(view_name="input_aliases", python_object=aliases)
    bridge = (
        "UNION SELECT a.input_id,b.sequence_id AS query_alias FROM input_aliases a "
        "JOIN identifier_bridge b ON b.input_id=a.query_alias"
        if "identifier_bridge" in names
        else ""
    )
    try:
        matches = connection.execute(f"""
            WITH aliases AS (SELECT * FROM input_aliases {bridge}), hits AS (
                SELECT DISTINCT a.input_id,a.query_alias,m.sequence_id,m.cluster_id,c.member_count
                FROM aliases a JOIN sequence_map m ON m.sequence_id=a.query_alias
                LEFT JOIN clusters c ON c.cluster_id=m.cluster_id
            ), counts AS (
                SELECT input_id,count(DISTINCT cluster_id) AS global_cluster_count
                FROM hits GROUP BY input_id
            )
            SELECT i.input_id,h.query_alias AS matched_alias,
                h.sequence_id,h.cluster_id,h.member_count,
                coalesce(c.global_cluster_count,0) AS global_cluster_count,
                CASE WHEN h.cluster_id IS NULL THEN 'UNMATCHED'
                     WHEN h.member_count IS NULL THEN 'MAPPED_WITHOUT_ROW_GROUP_INDEX'
                     WHEN c.global_cluster_count > 1 THEN 'MULTIPLE_GLOBAL_CLUSTERS'
                     WHEN h.query_alias=i.input_id THEN 'EXACT_ID'
                     ELSE 'EXPLICIT_ALIAS' END AS mapping_status
            FROM (SELECT DISTINCT input_id FROM input_aliases) i
            LEFT JOIN hits h USING(input_id) LEFT JOIN counts c USING(input_id)
            ORDER BY i.input_id,h.cluster_id,h.sequence_id,h.query_alias
        """).fetchdf()
    finally:
        connection.unregister(view_name="input_aliases")
    LOGGER.info("Resolved %d protein IDs to %d mapping rows", len(identifiers), len(matches))
    return matches


def browse_clusters(
    *,
    connection: object,
    minimum_members: int = 1,
    cluster_ids: Sequence[str] = (),
    taxon_ids: Sequence[int] = (),
    require_all_taxa: bool = False,
    any_annotated_species: bool = False,
    limit: int = 200,
) -> pd.DataFrame:
    """Rank global clusters by size and optional exact membership/taxonomy constraints.

    Args:
        connection: Open catalogue connection.
        minimum_members: Minimum published cluster size.
        cluster_ids: Optional exact global cluster IDs, e.g. from sequence resolution.
        taxon_ids: Required represented exact species/taxon IDs.
        require_all_taxa: Require every selected taxon, otherwise any selected taxon.
        any_annotated_species: Require at least one reviewed taxonomic assignment.
        limit: Bounded preview size; does not truncate extracted clusters.

    Returns:
        Size-ranked cluster summaries with unlimited qualifying count.

    Raises:
        ResearchError: If controls or the taxonomic index are unavailable.
    """
    minimum = bounded_number(
        value=minimum_members,
        label="Minimum cluster size",
        minimum=1,
        maximum=100_000_000_000,
        integer=True,
    )
    maximum = bounded_number(
        value=limit, label="Cluster result limit", minimum=1, maximum=10_000, integer=True
    )
    predicates = ["member_count >= ?"]
    parameters: list[object] = [minimum]
    if cluster_ids:
        predicates.append("cluster_id IN (SELECT unnest(?))")
        parameters.append(list(cluster_ids))
    if taxon_ids or any_annotated_species:
        names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        if "cluster_taxonomy" not in names:
            raise ResearchError("Species selection requires a reviewed cluster-taxonomy index")
        if taxon_ids:
            taxa = sorted(
                {
                    bounded_number(
                        value=value,
                        label="Taxon ID",
                        minimum=1,
                        maximum=10_000_000_000,
                        integer=True,
                    )
                    for value in taxon_ids
                }
            )
            predicates.append(
                "cluster_id IN (SELECT cluster_id FROM cluster_taxonomy WHERE "
                "TRY_CAST(taxon_id AS BIGINT) IN (SELECT unnest(?)) GROUP BY cluster_id "
                "HAVING count(DISTINCT taxon_id) >= ?)"
            )
            parameters.extend([taxa, len(taxa) if require_all_taxa else 1])
        else:
            predicates.append(
                "cluster_id IN (SELECT cluster_id FROM cluster_taxonomy "
                "WHERE TRY_CAST(taxon_id AS BIGINT)>0)"
            )
    query = "SELECT *,count(*) OVER() AS qualifying_cluster_count FROM clusters WHERE "
    query += " AND ".join(predicates) + " ORDER BY member_count DESC,cluster_id LIMIT ?"
    return connection.execute(query, [*parameters, maximum]).fetchdf()


def _row_groups(*, value: object, maximum: int) -> tuple[int, ...]:
    """Parse row-group references, including comma-separated official multi-group entries.

    Args:
        value: Published index reference.
        maximum: Number of physical Parquet row groups.

    Returns:
        Unique sorted valid row-group offsets.

    Raises:
        ResearchError: If references are missing, malformed or out of range.
    """
    if value is None or pd.isna(value):
        raise ResearchError("Selected cluster has no published row-group index")
    tokens = [token for token in re.split(r"[,;\s\[\]]+", str(value)) if token]
    if not tokens or any(not token.isdigit() for token in tokens):
        raise ResearchError("DeepClust row-group index is malformed")
    groups = tuple(sorted({int(token) for token in tokens}))
    if any(group >= maximum for group in groups):
        raise ResearchError("DeepClust row-group reference exceeds the sequence Parquet")
    return groups


def extract_clusters(
    *, config: ResearchConfig, cluster_ids: Sequence[str], output: Path
) -> dict[str, Path]:
    """Retrieve complete indexed clusters, reading only their physical Parquet row groups.

    Args:
        config: Mounted official release and extraction bounds.
        cluster_ids: One to 1,000 exact global centroid identifiers.
        output: New owned job directory.

    Returns:
        Artifact names mapped to complete FASTA, member metadata and retrieval audit paths.

    Raises:
        ResearchError: If limits are exceeded, IDs are unindexed or counts disagree.
    """
    selected = sorted(set(cluster_ids))
    if not selected or len(selected) > 1_000:
        raise ResearchError("Retrieve between 1 and 1000 exact clusters per job")
    with open_catalogue(config=config) as connection:
        index = connection.execute(
            "SELECT * FROM clusters WHERE cluster_id IN (SELECT unnest(?))",
            [selected],
        ).fetchdf()
    if set(index["cluster_id"]) != set(selected) or index["cluster_id"].duplicated().any():
        raise ResearchError("Selected cluster IDs are absent or duplicated in the row-group index")
    if index["member_count"].isna().any() or (index["member_count"] < 1).any():
        raise ResearchError("DeepClust index contains invalid member counts")
    if int(index["member_count"].sum()) > config.max_sequences:
        raise ResearchError(
            "Complete selected clusters exceed max_sequences; select fewer clusters"
        )
    source = Path(config.sequences).expanduser()
    if not source.is_file():
        raise ResearchError("Configure the mounted DeepClust sequence Parquet before retrieval")
    parquet = pq.ParquetFile(source)
    columns = parquet.schema_arrow.names
    identifier = _column(columns=columns, choices=("f0", "sequence_id")).strip('"')
    sequence = _column(columns=columns, choices=("f1", "protein_sequence", "sequence")).strip('"')
    cluster = _column(columns=columns, choices=("f2", "cluster_id")).strip('"')
    groups = sorted(
        {
            group
            for value in index["row_groups"]
            for group in _row_groups(value=value, maximum=parquet.num_row_groups)
        }
    )
    artifacts: dict[str, Path] = {"members.tsv": output / "members.tsv"}
    counts = dict.fromkeys(selected, 0)
    names = {
        value: f"cluster_{hashlib.sha256(value.encode()).hexdigest()[:24]}.fasta"
        for value in selected
    }
    for name in names.values():
        path = output / name
        if path.exists():
            raise ResearchError("Refusing to overwrite an existing cluster extraction")
        path.touch()
        artifacts[name] = path
    database = sqlite3.connect(database=output / "member_identity.sqlite")
    database.execute("CREATE TABLE members(sequence_id TEXT PRIMARY KEY,cluster_id TEXT NOT NULL)")
    try:
        with (output / "members.tsv").open(mode="w", encoding="utf-8", newline="") as table:
            writer = csv.writer(table, delimiter="\t", lineterminator="\n")
            writer.writerow(
                ["sequence_id", "cluster_id", "sequence_length", "terminal_stop_removed"]
            )
            for batch in parquet.iter_batches(
                batch_size=8_192, row_groups=groups, columns=[identifier, sequence, cluster]
            ):
                filtered = batch.filter(
                    pc.is_in(batch.column(cluster), value_set=pa.array(selected))
                )
                by_cluster: dict[str, list[str]] = {}
                for row in filtered.to_pylist():
                    key = str(row[identifier])
                    sequence_aliases(identifier=key)
                    raw = str(row[sequence]) if row[sequence] is not None else ""
                    protein = normalise_protein(sequence=raw)
                    parent = str(row[cluster])
                    try:
                        database.execute("INSERT INTO members VALUES (?,?)", (key, parent))
                    except sqlite3.IntegrityError as exc:
                        raise ResearchError(
                            "DeepClust extraction contains duplicate sequence IDs"
                        ) from exc
                    by_cluster.setdefault(parent, []).append(f">{key}\n{protein}\n")
                    writer.writerow([key, parent, len(protein), raw.rstrip().endswith("*")])
                    counts[parent] += 1
                for parent, records in by_cluster.items():
                    with (output / names[parent]).open(mode="a", encoding="utf-8") as handle:
                        handle.writelines(records)
                database.commit()
        expected = dict(zip(index["cluster_id"], index["member_count"], strict=True))
        if counts != expected:
            raise ResearchError("Extracted sequence counts disagree with the published index")
    finally:
        database.close()
        parquet.close()
    audit = [
        {
            "cluster_id": value,
            "published_members": counts[value],
            "retrieved_members": counts[value],
            "fasta_artifact": names[value],
            "source_url": SOURCE_URL,
        }
        for value in selected
    ]
    write_tsv(path=output / "clusters.tsv", rows=audit, columns=list(audit[0]))
    artifacts["clusters.tsv"] = output / "clusters.tsv"
    artifacts.update(cluster_statistics(config=config, output=output))
    LOGGER.info(
        "Retrieved %d complete global clusters (%d sequences; %d row groups)",
        len(selected),
        sum(counts.values()),
        len(groups),
    )
    return artifacts


def cluster_statistics(*, config: ResearchConfig, output: Path) -> dict[str, Path]:
    """Summarise complete extracted proteins and optional reviewed taxonomic evidence.

    Args:
        config: Bounded-memory profile and optional taxonomy.
        output: Retrieval directory containing the complete members.tsv.

    Returns:
        Length summary and, when available, species counts and unclassified counts.
    """
    artifacts = {}
    with open_catalogue(config=config, require_index=False) as connection:
        connection.read_csv(
            str(output / "members.tsv"), delimiter="\t", header=True, all_varchar=True
        ).create_view("retrieved_members")
        connection.sql("""
            SELECT cluster_id,count(*) AS sequence_count,
                min(sequence_length::BIGINT) AS minimum_length,
                max(sequence_length::BIGINT) AS maximum_length,
                avg(sequence_length::BIGINT) AS mean_length,
                median(sequence_length::BIGINT) AS median_length,
                count(*) FILTER(WHERE lower(terminal_stop_removed)='true') AS terminal_stops_removed
            FROM retrieved_members GROUP BY cluster_id ORDER BY sequence_count DESC,cluster_id
        """).write_csv(str(output / "cluster_summary.tsv"), sep="\t", header=True)
        artifacts["cluster_summary.tsv"] = output / "cluster_summary.tsv"
        if config.taxonomy:
            connection.sql("""
                WITH reviewed AS (
                    SELECT sequence_id,min(species) AS species,min(taxon_id) AS taxon_id
                    FROM taxonomy WHERE taxon_id>0 GROUP BY sequence_id
                    HAVING count(DISTINCT taxon_id)=1
                )
                SELECT m.cluster_id,coalesce(t.species,'UNCLASSIFIED') AS species,
                    t.taxon_id,count(*) AS member_count
                FROM retrieved_members m LEFT JOIN reviewed t USING(sequence_id)
                GROUP BY m.cluster_id,t.species,t.taxon_id ORDER BY m.cluster_id,member_count DESC
            """).write_csv(str(output / "cluster_species.tsv"), sep="\t", header=True)
            artifacts["cluster_species.tsv"] = output / "cluster_species.tsv"
    return artifacts


def build_cluster_taxonomy(*, config: ResearchConfig, output: Path) -> Path:
    """Build a reusable cluster/species index by joining reviewed sequence taxonomy.

    Args:
        config: Profile with sequence map and reviewed sequence taxonomy.
        output: New owned job output directory.

    Returns:
        Parquet path; unknown taxonomy remains absent rather than being inferred from IDs.

    Raises:
        ResearchError: If required reviewed sources are unavailable.
    """
    with open_catalogue(config=config) as connection:
        names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        if not {"sequence_map", "taxonomy"}.issubset(names):
            raise ResearchError(
                "Taxonomy indexing requires sequence_map and reviewed sequence taxonomy"
            )
        ambiguous = connection.execute(
            "SELECT sequence_id FROM taxonomy GROUP BY sequence_id "
            "HAVING count(DISTINCT taxon_id)>1 LIMIT 1"
        ).fetchone()
        if ambiguous:
            raise ResearchError("Reviewed sequence taxonomy contains conflicting taxon IDs")
        destination = output / "cluster_taxonomy.parquet"
        relation = connection.sql(
            "SELECT m.cluster_id,t.taxon_id,min(t.species) AS species, "
            "count(DISTINCT m.sequence_id)::BIGINT AS annotated_member_count "
            "FROM sequence_map m JOIN taxonomy t USING(sequence_id) WHERE t.taxon_id>0 "
            "GROUP BY m.cluster_id,t.taxon_id"
        )
        relation.write_parquet(str(destination), compression="zstd")
    LOGGER.info("Built reviewed cluster-taxonomy index at %s", destination)
    return destination
