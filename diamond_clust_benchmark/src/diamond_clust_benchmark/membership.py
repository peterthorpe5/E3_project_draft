"""Summarise and compare DIAMOND cluster-membership tables."""

from __future__ import annotations

import csv
import gzip
import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple

from diamond_clust_benchmark.exceptions import DataValidationError

_HEADERS = {
    ("centroid", "member"),
    ("representative", "member"),
    ("cluster", "member"),
}


def _open_membership(path: Path):
    """Open a membership table as plain or gzip-compressed text."""

    source = Path(path)
    if source.suffix.lower() == ".gz":
        return gzip.open(source, "rt", encoding="utf-8", newline="")
    return source.open("r", encoding="utf-8", newline="")


def _membership_header(path: Path) -> Tuple[str, str]:
    """Read and validate the two membership column names."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Membership table does not exist: {source}")
    with _open_membership(source) as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise DataValidationError(
                f"Membership table is empty: {source}"
            ) from error
    if header not in _HEADERS:
        raise DataValidationError(
            f"Unrecognised membership header in {source}: {header!r}"
        )
    return header


def iter_membership(path: Path) -> Iterator[Tuple[str, str]]:
    """Yield validated representative-member pairs.

    Args:
        path: Headered two-column DIAMOND membership table.

    Yields:
        ``(representative, member)`` pairs.

    Raises:
        FileNotFoundError: If the table does not exist.
        DataValidationError: If the table has an invalid header or row.
    """

    source = Path(path)
    expected_header = _membership_header(source)
    with _open_membership(source) as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = tuple(next(reader))
        if header != expected_header:
            raise DataValidationError(
                f"Membership header changed while reading: {source}"
            )
        for line_number, row in enumerate(reader, start=2):
            if len(row) != 2 or not row[0] or not row[1]:
                raise DataValidationError(
                    f"Invalid membership row at {source}:{line_number}"
                )
            yield row[0], row[1]


def membership_sha256(path: Path) -> str:
    """Calculate a SHA-256 checksum for a membership table."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summarise_membership_small(path: Path) -> Dict[str, object]:
    """Summarise a small membership table in memory."""

    counts: Counter[str] = Counter()
    members: Set[str] = set()
    rows = 0
    self_rows = 0
    for representative, member in iter_membership(path):
        if member in members:
            raise DataValidationError(f"Duplicate member identifier: {member}")
        members.add(member)
        counts[representative] += 1
        rows += 1
        if representative == member:
            self_rows += 1
    if rows == 0:
        raise DataValidationError(f"Membership table has no data rows: {path}")
    return {
        "membership_rows": rows,
        "unique_members": len(members),
        "cluster_count": len(counts),
        "singleton_clusters": sum(size == 1 for size in counts.values()),
        "largest_cluster_size": max(counts.values()),
        "representative_self_rows": self_rows,
    }


def _duckdb_view_sql(path: Path, view_name: str) -> str:
    """Build SQL for a normalised, validated DuckDB membership view."""

    representative_column, member_column = _membership_header(path)
    source = _sql_path(path)
    return f"""
        CREATE VIEW {view_name} AS
        SELECT
            \"{representative_column}\" AS centroid,
            \"{member_column}\" AS member
        FROM read_csv(
            '{source}', delim='\t', header=true, all_varchar=true
        )
    """


def _summarise_membership_duckdb(path: Path, duckdb_module) -> Dict[str, object]:
    """Summarise a membership table with bounded Python memory."""

    connection = duckdb_module.connect(":memory:")
    try:
        connection.execute(_duckdb_view_sql(path, "membership"))
        row = connection.execute(
            """
            WITH sizes AS (
                SELECT centroid, count(*)::BIGINT AS n
                FROM membership
                GROUP BY centroid
            )
            SELECT
                (SELECT count(*) FROM membership),
                (SELECT count(DISTINCT member) FROM membership),
                (SELECT count(*) FROM sizes),
                (SELECT count(*) FROM sizes WHERE n = 1),
                (SELECT max(n) FROM sizes),
                (SELECT count(*) FROM membership WHERE centroid = member)
            """
        ).fetchone()
    finally:
        connection.close()
    rows, unique_members, clusters, singletons, largest, self_rows = row
    if rows == 0:
        raise DataValidationError(f"Membership table has no data rows: {path}")
    if rows != unique_members:
        raise DataValidationError("A membership table contains duplicate members")
    return {
        "membership_rows": rows,
        "unique_members": unique_members,
        "cluster_count": clusters,
        "singleton_clusters": singletons,
        "largest_cluster_size": largest,
        "representative_self_rows": self_rows,
    }


def summarise_membership(
    path: Path,
    small_file_limit_bytes: int = 64 * 1024 * 1024,
) -> Dict[str, object]:
    """Calculate scalable structural counts for a membership table.

    Args:
        path: Headered DIAMOND membership table.
        small_file_limit_bytes: Maximum bytes accepted by the in-memory
            fallback when DuckDB is unavailable.

    Returns:
        Row, cluster, singleton, largest-cluster and checksum metrics.

    Raises:
        RuntimeError: If DuckDB is unavailable for a large table.
        DataValidationError: If members are duplicated or no rows are present.
    """

    source = Path(path)
    if small_file_limit_bytes < 1:
        raise ValueError("small_file_limit_bytes must be positive")
    try:
        import duckdb
    except ImportError as error:
        if source.stat().st_size > small_file_limit_bytes:
            raise RuntimeError(
                "DuckDB is required to summarise large membership tables"
            ) from error
        summary = _summarise_membership_small(source)
    else:
        summary = _summarise_membership_duckdb(source, duckdb)
    return {
        "membership_path": str(source.resolve()),
        "membership_sha256": membership_sha256(source),
        **summary,
    }


def _combination_two(value: int) -> int:
    """Return the number of unordered pairs from ``value`` items."""

    return value * (value - 1) // 2


def _load_mapping(path: Path) -> Dict[str, str]:
    """Load a small membership fixture into a member-to-cluster mapping."""

    mapping: Dict[str, str] = {}
    for representative, member in iter_membership(path):
        if member in mapping:
            raise DataValidationError(f"Duplicate member identifier: {member}")
        mapping[member] = representative
    return mapping


def _pair_metrics(
    baseline_counts: Counter[str],
    candidate_counts: Counter[str],
    contingency: Counter[Tuple[str, str]],
    member_count: int,
) -> Dict[str, float]:
    """Calculate pairwise precision, recall, F1 and adjusted Rand index."""

    baseline_pairs = sum(_combination_two(value) for value in baseline_counts.values())
    candidate_pairs = sum(
        _combination_two(value) for value in candidate_counts.values()
    )
    shared_pairs = sum(_combination_two(value) for value in contingency.values())
    precision = shared_pairs / candidate_pairs if candidate_pairs else 1.0
    recall = shared_pairs / baseline_pairs if baseline_pairs else 1.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    all_pairs = _combination_two(member_count)
    expected = (
        baseline_pairs * candidate_pairs / all_pairs if all_pairs else 0.0
    )
    maximum = 0.5 * (baseline_pairs + candidate_pairs)
    denominator = maximum - expected
    adjusted_rand = (
        (shared_pairs - expected) / denominator
        if denominator
        else 1.0
    )
    return {
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_f1": f1,
        "adjusted_rand_index": adjusted_rand,
    }


def _read_sentinel_ids(path: Optional[Path]) -> Set[str]:
    """Read a one-column, headered sentinel identifier TSV."""

    if path is None:
        return set()
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "sequence_id" not in reader.fieldnames:
            raise DataValidationError(
                "Sentinel TSV must contain a sequence_id column"
            )
        values = {str(row["sequence_id"]).strip() for row in reader}
    values.discard("")
    if not values:
        raise DataValidationError("Sentinel TSV contains no sequence identifiers")
    return values


def compare_memberships_small(
    baseline_path: Path,
    candidate_path: Path,
    sentinel_ids_tsv: Optional[Path] = None,
) -> Dict[str, object]:
    """Compare two membership tables in memory for tests and small pilots.

    Args:
        baseline_path: Reference membership table.
        candidate_path: Candidate membership table.
        sentinel_ids_tsv: Optional one-column sentinel identifier TSV.

    Returns:
        Concordance and optional sentinel-neighbourhood metrics.

    Raises:
        DataValidationError: If member identifier sets differ.
    """

    baseline = _load_mapping(baseline_path)
    candidate = _load_mapping(candidate_path)
    if baseline.keys() != candidate.keys():
        missing = len(baseline.keys() - candidate.keys())
        extra = len(candidate.keys() - baseline.keys())
        raise DataValidationError(
            f"Membership identifier sets differ: missing={missing}, extra={extra}"
        )
    baseline_counts = Counter(baseline.values())
    candidate_counts = Counter(candidate.values())
    contingency = Counter(
        (baseline[member], candidate[member]) for member in baseline
    )
    metrics: Dict[str, object] = {
        "member_count": len(baseline),
        "baseline_cluster_count": len(baseline_counts),
        "candidate_cluster_count": len(candidate_counts),
        **_pair_metrics(
            baseline_counts,
            candidate_counts,
            contingency,
            len(baseline),
        ),
    }
    sentinels = _read_sentinel_ids(sentinel_ids_tsv)
    if sentinels:
        matched = sentinels.intersection(baseline).intersection(candidate)
        if not matched:
            raise DataValidationError("No sentinel identifier matched both tables")
        baseline_clusters = {baseline[value] for value in matched}
        candidate_clusters = {candidate[value] for value in matched}
        baseline_neighbours = {
            member
            for member, cluster in baseline.items()
            if cluster in baseline_clusters
        }
        candidate_neighbours = {
            member
            for member, cluster in candidate.items()
            if cluster in candidate_clusters
        }
        intersection = len(baseline_neighbours.intersection(candidate_neighbours))
        union = len(baseline_neighbours.union(candidate_neighbours))
        metrics.update(
            {
                "sentinel_count": len(sentinels),
                "matched_sentinel_count": len(matched),
                "sentinel_baseline_neighbours": len(baseline_neighbours),
                "sentinel_candidate_neighbours": len(candidate_neighbours),
                "sentinel_recall": (
                    intersection / len(baseline_neighbours)
                    if baseline_neighbours
                    else 1.0
                ),
                "sentinel_jaccard": intersection / union if union else 1.0,
            }
        )
    else:
        metrics.update(
            {
                "sentinel_count": 0,
                "matched_sentinel_count": 0,
                "sentinel_baseline_neighbours": "",
                "sentinel_candidate_neighbours": "",
                "sentinel_recall": "",
                "sentinel_jaccard": "",
            }
        )
    return metrics


def _sql_path(path: Path) -> str:
    """Escape an absolute path for a DuckDB SQL string literal."""

    return str(Path(path).resolve()).replace("'", "''")


def compare_memberships(
    baseline_path: Path,
    candidate_path: Path,
    sentinel_ids_tsv: Optional[Path] = None,
    small_file_limit_bytes: int = 64 * 1024 * 1024,
) -> Dict[str, object]:
    """Compare memberships with DuckDB at scale and a small-file fallback.

    Args:
        baseline_path: Reference membership table.
        candidate_path: Candidate membership table.
        sentinel_ids_tsv: Optional sentinel identifier TSV.
        small_file_limit_bytes: Maximum combined bytes for the pure-Python
            fallback when DuckDB is unavailable.

    Returns:
        Concordance and sentinel-neighbourhood metrics.

    Raises:
        RuntimeError: If DuckDB is missing for large inputs.
        DataValidationError: If memberships are incomplete or duplicated.
    """

    if small_file_limit_bytes < 1:
        raise ValueError("small_file_limit_bytes must be positive")
    try:
        import duckdb
    except ImportError as error:
        total_size = (
            Path(baseline_path).stat().st_size
            + Path(candidate_path).stat().st_size
        )
        if total_size <= small_file_limit_bytes:
            return compare_memberships_small(
                baseline_path,
                candidate_path,
                sentinel_ids_tsv,
            )
        raise RuntimeError(
            "DuckDB is required to compare large membership tables"
        ) from error
    connection = duckdb.connect(":memory:")
    connection.execute(_duckdb_view_sql(baseline_path, "baseline"))
    connection.execute(_duckdb_view_sql(candidate_path, "candidate"))
    audit = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM baseline),
            (SELECT count(DISTINCT member) FROM baseline),
            (SELECT count(*) FROM candidate),
            (SELECT count(DISTINCT member) FROM candidate),
            (SELECT count(*) FROM baseline b ANTI JOIN candidate c USING (member)),
            (SELECT count(*) FROM candidate c ANTI JOIN baseline b USING (member))
        """
    ).fetchone()
    if audit[0] != audit[1] or audit[2] != audit[3]:
        raise DataValidationError("A membership table contains duplicate members")
    if audit[4] or audit[5] or audit[0] != audit[2]:
        raise DataValidationError(
            f"Membership identifier sets differ: missing={audit[4]}, extra={audit[5]}"
        )
    row = connection.execute(
        """
        WITH joined AS (
            SELECT b.centroid AS b_cluster, c.centroid AS c_cluster
            FROM baseline b JOIN candidate c USING (member)
        ),
        b_counts AS (
            SELECT b_cluster, count(*)::BIGINT AS n FROM joined GROUP BY b_cluster
        ),
        c_counts AS (
            SELECT c_cluster, count(*)::BIGINT AS n FROM joined GROUP BY c_cluster
        ),
        cells AS (
            SELECT b_cluster, c_cluster, count(*)::BIGINT AS n
            FROM joined GROUP BY b_cluster, c_cluster
        )
        SELECT
            (SELECT count(*) FROM joined) AS member_count,
            (SELECT count(*) FROM b_counts) AS baseline_clusters,
            (SELECT count(*) FROM c_counts) AS candidate_clusters,
            (SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM b_counts) AS b_pairs,
            (SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM c_counts) AS c_pairs,
            (SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM cells) AS shared_pairs
        """
    ).fetchone()
    member_count, b_clusters, c_clusters, b_pairs, c_pairs, shared_pairs = row
    precision = shared_pairs / c_pairs if c_pairs else 1.0
    recall = shared_pairs / b_pairs if b_pairs else 1.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    all_pairs = _combination_two(member_count)
    expected = b_pairs * c_pairs / all_pairs if all_pairs else 0.0
    maximum = 0.5 * (b_pairs + c_pairs)
    adjusted_rand = (
        (shared_pairs - expected) / (maximum - expected)
        if maximum != expected
        else 1.0
    )
    metrics: Dict[str, object] = {
        "member_count": member_count,
        "baseline_cluster_count": b_clusters,
        "candidate_cluster_count": c_clusters,
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_f1": f1,
        "adjusted_rand_index": adjusted_rand,
    }
    sentinels = _read_sentinel_ids(sentinel_ids_tsv)
    if sentinels:
        connection.execute("CREATE TABLE sentinels(sequence_id VARCHAR PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO sentinels VALUES (?)",
            [(value,) for value in sorted(sentinels)],
        )
        sentinel_row = connection.execute(
            """
            WITH matched AS (
                SELECT s.sequence_id
                FROM sentinels s
                JOIN baseline b ON b.member = s.sequence_id
                JOIN candidate c ON c.member = s.sequence_id
            ),
            bn AS (
                SELECT DISTINCT b2.member
                FROM baseline b1
                JOIN matched m ON m.sequence_id = b1.member
                JOIN baseline b2 ON b2.centroid = b1.centroid
            ),
            cn AS (
                SELECT DISTINCT c2.member
                FROM candidate c1
                JOIN matched m ON m.sequence_id = c1.member
                JOIN candidate c2 ON c2.centroid = c1.centroid
            ),
            intersection_count AS (
                SELECT count(*)::BIGINT AS n FROM bn JOIN cn USING (member)
            ),
            union_count AS (
                SELECT count(*)::BIGINT AS n FROM (
                    SELECT member FROM bn UNION SELECT member FROM cn
                )
            )
            SELECT
                (SELECT count(*) FROM sentinels),
                (SELECT count(*) FROM matched),
                (SELECT count(*) FROM bn),
                (SELECT count(*) FROM cn),
                (SELECT n FROM intersection_count),
                (SELECT n FROM union_count)
            """
        ).fetchone()
        total, matched, baseline_n, candidate_n, intersection, union = sentinel_row
        if matched == 0:
            raise DataValidationError("No sentinel identifier matched both tables")
        metrics.update(
            {
                "sentinel_count": total,
                "matched_sentinel_count": matched,
                "sentinel_baseline_neighbours": baseline_n,
                "sentinel_candidate_neighbours": candidate_n,
                "sentinel_recall": intersection / baseline_n if baseline_n else 1.0,
                "sentinel_jaccard": intersection / union if union else 1.0,
            }
        )
    else:
        metrics.update(
            {
                "sentinel_count": 0,
                "matched_sentinel_count": 0,
                "sentinel_baseline_neighbours": "",
                "sentinel_candidate_neighbours": "",
                "sentinel_recall": "",
                "sentinel_jaccard": "",
            }
        )
    connection.close()
    for key, value in tuple(metrics.items()):
        if isinstance(value, float) and not math.isfinite(value):
            raise DataValidationError(f"Non-finite quality metric: {key}")
    return metrics
